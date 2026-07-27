"""tripll.api.app — FastAPI control-plane application factory (W4 + W5).

Implements the full HTTP API surface defined in ``docs/control-plane-design.md``
§6.  All state reads open the ledger read-only; run-mutating operations
(launch, approve, resume, pause) spawn the ``tripll`` CLI as a detached
subprocess so runs **outlive the server**.

In addition, W5 mounts the Jinja2 + htmx + SSE web dashboard:

- ``GET /`` — dashboard home (runs list, profiles, backends).
- ``GET /runs/{run_id}`` — run detail with live per-agent wave table.
- Static assets served from ``/static/`` (htmx vendored; zero Node build).

Auth model
----------
A single Bearer token read from the ``TRIPLL_API_TOKEN`` environment
variable.  If the env var is unset, localhost requests are allowed without
auth (dev mode).  All other origins require the token.

For the SSE endpoint (``GET /api/runs/{id}/events/stream``), browsers cannot
set custom ``Authorization`` headers on ``EventSource``.  When a token is set
the dashboard injects it as a ``?token=`` query parameter; the SSE handler
accepts either ``Authorization: Bearer <tok>`` or ``?token=<tok>``.

Process model (§1)
-------------------
``POST /api/runs`` and ``POST /api/runs/{id}/approve|resume`` spawn
``tripll <subcmd>`` via ``subprocess.Popen(start_new_session=True)``.
The child PID is written to ``<run_dir>/engine.pid``.  A run is "live" if
``engine.pid`` exists and the PID is alive.

Exports:
    create_app — construct and return the configured FastAPI instance.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from tripll.api._artefacts import LogPathError, resolve_attempt_log_path, tail_log_file
from tripll.api._auth import require_auth
from tripll.api._csrf import apply_csrf_cookie
from tripll.api._runs import (
    RunDetail,
    RunSummary,
    _find_ledger,
    _is_run_live,
    _list_all_runs,
)
from tripll.api._worktree_status import (
    WorktreeStatusError,
    collect_worktree_status,
    load_staged_wave_plan_text,
    resolve_wave_worktree_path,
)
from tripll.ledger import (
    EventRow,
    get_run,
    get_wave,
    list_attempts,
    list_events,
    list_waves,
    open_ledger,
)
from tripll.pipeline import RunsRoot
from tripll.profiles import (
    ProfileRow,
    control_plane_db_path,
    delete_profile,
    get_profile,
    list_profiles,
    open_profile_store,
    upsert_profile,
)
from tripll.wave_task import infer_active_task

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tripll.ledger import LedgerConnection


def _slug_profile_id(source: str) -> str:
    """Slugify *source* into a profile id (lowercase, dash-separated).

    Args:
        source (str): Raw id or name to slugify.

    Returns:
        str: A non-empty slug (``"profile"`` when *source* has no usable chars),
        truncated to 48 characters.

    Examples:
        >>> _slug_profile_id("My Agent!")
        'my-agent'
        >>> _slug_profile_id("___")
        'profile'
    """
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:48]
    return slug or "profile"


# ---------------------------------------------------------------------------
# Pydantic models — request / response bodies
# ---------------------------------------------------------------------------


class ProfileIn(BaseModel):
    """Request body for creating / patching an agent profile."""

    name: str
    backend: str
    profile_id: str | None = Field(
        default=None,
        description=(
            "Explicit profile id (slugified). When omitted, an id is derived "
            "from name. Creating with an id that already exists returns 409."
        ),
    )
    model: str = "claude-sonnet-5"
    agent: str = "wave-plan-executor"
    skills: list[str] = Field(default_factory=list)
    scope: dict[str, Any] = Field(default_factory=dict)


class ProfileOut(BaseModel):
    """Response body for an agent profile."""

    profile_id: str
    name: str
    backend: str
    model: str
    agent: str
    skills: list[str]
    scope: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: ProfileRow) -> ProfileOut:
        """Construct from a :class:`~tripll.profiles.ProfileRow`.

        Args:
            row (ProfileRow): Hydrated profile row.

        Returns:
            ProfileOut: API response model.
        """
        return cls(
            profile_id=row.profile_id,
            name=row.name,
            backend=row.backend,
            model=row.model,
            agent=row.agent,
            skills=row.skills,
            scope=row.scope,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class HitlAnswerIn(BaseModel):
    """One HITL answer in a PUT/POST body."""

    question_id: str
    option_id: str | None = None
    checked: bool | None = None
    notes: str = ""


class HitlResponsesIn(BaseModel):
    """Operator HITL responses payload."""

    status: str = "draft"
    answers: list[HitlAnswerIn] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    """Partial update body for an agent profile (all fields optional)."""

    name: str | None = None
    backend: str | None = None
    model: str | None = None
    agent: str | None = None
    skills: list[str] | None = None
    scope: dict[str, Any] | None = None


class RunIn(BaseModel):
    """Request body to launch a new run."""

    input_path: str = Field(
        ...,
        description="Absolute path to the input directory (parallel-wave set or plain wave folder).",
    )
    profile_id: str = Field(
        ...,
        description="Profile to use for the run. Must exist in the profile store.",
    )
    runs_root: str | None = Field(
        default=None,
        description="Override runs root; defaults to the server's configured runs root.",
    )


class EventOut(BaseModel):
    """Response body for a single event row."""

    event_id: int
    run_id: str
    node_id: str
    ts: str
    phase: str
    last_action: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    attempt_n: int | None = None
    task_id: str | None = None
    metadata: str | None = None


class WaveOut(BaseModel):
    """Response body for a single wave row."""

    node_id: str
    run_id: str
    plan_id: str
    wave_id: str
    lane: str
    state: str
    attempt_count: int
    created_at: str
    updated_at: str


class ConfigOut(BaseModel):
    """Response body for API config."""

    model_default: str
    cost_budget_usd: float
    max_parallel: int


class ConfigIn(BaseModel):
    """Request body to update config env vars (runtime only — not persisted to disk)."""

    model_default: str | None = None
    cost_budget_usd: float | None = None
    max_parallel: int | None = None


class BackendOut(BaseModel):
    """Response body for a backend availability entry."""

    name: str
    available: bool
    detail: str
    streaming: bool


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    runs_root: Path | None = None,
) -> FastAPI:
    """Construct and return the configured FastAPI application.

    Args:
        runs_root (Path | None): Override the runs root directory.  Defaults to
            the ``TRIPLL_RUNS`` env var or ``wave-orchestrator/runs/``.

    Returns:
        FastAPI: Configured application instance.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> app = create_app(runs_root=None)
        >>> client = TestClient(app)
        >>> client.get("/health").status_code
        200
    """
    app = FastAPI(
        title="tripll control plane",
        description=(
            "FastAPI control plane for the wave-orchestrator.  "
            "Launches, observes, and controls headless wave-plan runs."
        ),
        version="0.5.0",
    )

    # Resolve runs root once at startup; share via app state.
    _runs_root = _resolve_runs_root(runs_root)
    app.state.runs_root = _runs_root

    # ---------------------------------------------------------------------------
    # W5 — Web dashboard (Jinja2 + htmx + SSE; zero Node build)
    # ---------------------------------------------------------------------------

    # Vendor static assets (htmx.min.js, htmx-sse.js) under /static/.
    from tripll.api.ui import make_ui_router, static_path

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    app.include_router(make_ui_router())

    from tripll.api.ui.errors import register_html_exception_handlers

    register_html_exception_handlers(app)

    @app.middleware("http")
    async def csrf_cookie_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Mirror ``request.state.csrf_token`` into the ``tripll_csrf`` cookie (W3, R5)."""
        response = await call_next(request)
        apply_csrf_cookie(request, response)
        return response

    # ---------------------------------------------------------------------------
    # Health
    # ---------------------------------------------------------------------------

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Health check — returns status 200 with ``{"status": "ok"}``."""
        return {"status": "ok"}

    # ---------------------------------------------------------------------------
    # Agent profiles
    # ---------------------------------------------------------------------------

    @app.get("/api/agents", response_model=list[ProfileOut], tags=["agents"])
    async def list_agents(
        _auth: None = Depends(require_auth),
    ) -> list[ProfileOut]:
        """List all agent profiles.

        Returns:
            list[ProfileOut]: All profiles ordered by creation time.
        """
        rr: RunsRoot = app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with open_profile_store(db_path) as store:
            profiles = list_profiles(store)
        return [ProfileOut.from_row(p) for p in profiles]

    @app.post("/api/agents", response_model=ProfileOut, status_code=201, tags=["agents"])
    async def create_agent(
        data: ProfileIn,
        _auth: None = Depends(require_auth),
    ) -> ProfileOut:
        """Create a new agent profile.

        Args:
            data (ProfileIn): Profile configuration.

        Returns:
            ProfileOut: The created profile.
        """
        rr: RunsRoot = app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        explicit = data.profile_id is not None
        profile_id = _slug_profile_id(data.profile_id if data.profile_id is not None else data.name)
        with open_profile_store(db_path) as store:
            if explicit:
                # Honour the caller's id exactly; a collision is a 409, not a
                # silent rename.
                try:
                    get_profile(store, profile_id)
                except KeyError:
                    pass
                else:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Profile already exists: {profile_id}",
                    )
            else:
                # Derived from name: de-duplicate by suffixing on collision.
                base_id = profile_id
                suffix = 1
                while True:
                    try:
                        get_profile(store, profile_id)
                        profile_id = f"{base_id}-{suffix}"
                        suffix += 1
                    except KeyError:
                        break
            row = upsert_profile(
                store,
                profile_id=profile_id,
                name=data.name,
                backend=data.backend,
                model=data.model,
                agent=data.agent,
                skills=data.skills,
                scope=data.scope,
            )
        return ProfileOut.from_row(row)

    @app.get("/api/agents/{profile_id}", response_model=ProfileOut, tags=["agents"])
    async def get_agent(
        profile_id: str,
        _auth: None = Depends(require_auth),
    ) -> ProfileOut:
        """Fetch a single agent profile by ID.

        Args:
            profile_id (str): Profile primary key.

        Returns:
            ProfileOut: The profile.

        Raises:
            HTTPException: 404 if not found.
        """
        rr: RunsRoot = app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                row = get_profile(store, profile_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail=f"Profile not found: {profile_id}"
                ) from exc
        return ProfileOut.from_row(row)

    @app.patch("/api/agents/{profile_id}", response_model=ProfileOut, tags=["agents"])
    async def patch_agent(
        profile_id: str,
        data: ProfilePatch,
        _auth: None = Depends(require_auth),
    ) -> ProfileOut:
        """Partially update an agent profile.

        Only supplied fields are updated; omitted fields are preserved.

        Args:
            profile_id (str): Profile primary key.
            data (ProfilePatch): Partial update fields.

        Returns:
            ProfileOut: The updated profile.

        Raises:
            HTTPException: 404 if not found.
        """
        rr: RunsRoot = app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                existing = get_profile(store, profile_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail=f"Profile not found: {profile_id}"
                ) from exc
            row = upsert_profile(
                store,
                profile_id=profile_id,
                name=data.name if data.name is not None else existing.name,
                backend=data.backend if data.backend is not None else existing.backend,
                model=data.model if data.model is not None else existing.model,
                agent=data.agent if data.agent is not None else existing.agent,
                skills=data.skills if data.skills is not None else existing.skills,
                scope=data.scope if data.scope is not None else existing.scope,
            )
        return ProfileOut.from_row(row)

    @app.delete("/api/agents/{profile_id}", status_code=204, tags=["agents"])
    async def delete_agent(
        profile_id: str,
        _auth: None = Depends(require_auth),
    ) -> Response:
        """Delete an agent profile.

        Args:
            profile_id (str): Profile primary key.

        Returns:
            Response: 204 No Content.

        Raises:
            HTTPException: 404 if not found.
        """
        rr: RunsRoot = app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                delete_profile(store, profile_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail=f"Profile not found: {profile_id}"
                ) from exc
        return Response(status_code=204)

    # ---------------------------------------------------------------------------
    # Runs
    # ---------------------------------------------------------------------------

    @app.get("/api/runs", response_model=list[RunSummary], tags=["runs"])
    async def list_runs(
        _auth: None = Depends(require_auth),
    ) -> list[RunSummary]:
        """List all runs (processing, processed, failed).

        Returns:
            list[RunSummary]: Summary rows for all known runs.
        """
        rr: RunsRoot = app.state.runs_root
        return _list_all_runs(rr)

    @app.post("/api/runs", response_model=RunDetail, status_code=202, tags=["runs"])
    async def launch_run(
        data: RunIn,
        _auth: None = Depends(require_auth),
    ) -> RunDetail:
        """Launch a new run as a detached subprocess.

        The engine process is spawned via ``subprocess.Popen(start_new_session=True)``
        so it **outlives the FastAPI server**.  The child PID is written to
        ``<run_dir>/engine.pid``.

        Args:
            data (RunIn): Input path and profile_id.

        Returns:
            RunDetail: Initial run detail (state=launching until engine starts).

        Raises:
            HTTPException: 400 if profile not found or input path is invalid.
            HTTPException: 409 if a run for this input is already processing.
        """
        rr: RunsRoot = app.state.runs_root
        # Validate profile exists.
        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                profile = get_profile(store, data.profile_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=400, detail=f"Profile not found: {data.profile_id}"
                ) from exc

        input_path = Path(data.input_path)
        if not input_path.exists():  # noqa: ASYNC240
            raise HTTPException(status_code=400, detail=f"Input path not found: {data.input_path}")

        # Build argv for tripll run.
        tripll_bin = _tripll_argv()
        argv = [
            *tripll_bin,
            "run",
            str(input_path),
            "--backend",
            profile.backend,
            "--model",
            profile.model,
            "--agent",
            profile.agent,
            "--runs-root",
            str(rr.root),
        ]
        logger.info("api: launching run: {}", " ".join(argv))
        # Spawn detached — process must outlive the server; start_new_session=True
        # puts it in its own session immediately (fast fork, no wait).
        proc = subprocess.Popen(  # noqa: ASYNC220
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("api: spawned engine pid={}", proc.pid)

        # We can't know the run_id yet (engine derives it from the dir name + clock).
        # Return a placeholder; the client should poll GET /api/runs to find the new run.
        return RunDetail(
            run_id="(pending — poll GET /api/runs)",
            slug=input_path.name,
            state="active",
            input_path=str(input_path),
            created_at="",
            updated_at="",
            cost_usd=0.0,
            is_live=True,
            engine_pid=proc.pid,
        )

    @app.get("/api/runs/{run_id}", response_model=RunDetail, tags=["runs"])
    async def get_run_detail(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> RunDetail:
        """Fetch detailed status for a single run.

        Args:
            run_id (str): Run identifier.

        Returns:
            RunDetail: Run detail with liveness flag.

        Raises:
            HTTPException: 404 if run not found.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        with open_ledger(ledger_path) as lc:
            row = get_run(lc, run_id)
        run_dir = rr.find_run_dir(run_id)
        pid = _read_pid(run_dir)
        live = _is_run_live(run_dir)
        return RunDetail(
            run_id=row.run_id,
            slug=row.slug,
            state=row.state,
            input_path=row.input_path,
            created_at=row.created_at,
            updated_at=row.updated_at,
            cost_usd=row.cost_usd,
            is_live=live,
            engine_pid=pid,
        )

    @app.post("/api/runs/{run_id}/approve", status_code=202, tags=["runs"])
    async def approve_run(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, str]:
        """Approve the Pre-0 gate for a run.

        Spawns ``tripll approve <run_id>`` as a detached subprocess.

        Args:
            run_id (str): Run identifier.

        Returns:
            dict[str, str]: Confirmation message.
        """
        rr: RunsRoot = app.state.runs_root
        _assert_run_exists(rr, run_id)
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        from tripll import hitl

        form = hitl.load_form(run_dir)
        if form is not None and not hitl.responses_complete(run_dir):
            raise HTTPException(
                status_code=409,
                detail="HITL responses incomplete — complete the form before approve",
            )
        _spawn_tripll(["approve", run_id, "--runs-root", str(rr.root)])
        return {"message": f"Approving run {run_id}"}

    @app.get("/api/runs/{run_id}/hitl", tags=["runs"])
    async def get_hitl(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        """Return HITL form, responses, and completion status for a run."""
        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        from tripll import hitl

        return hitl.hitl_status(run_dir)

    @app.put("/api/runs/{run_id}/hitl/responses", tags=["runs"])
    async def put_hitl_responses(
        run_id: str,
        body: HitlResponsesIn,
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        """Save draft or submitted HITL responses."""
        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        from tripll import hitl

        form = hitl.load_form(run_dir)
        if form is None:
            raise HTTPException(status_code=404, detail="No HITL form for this run")
        responses = hitl.HitlResponses(
            run_id=run_id,
            form_id=form.form_id,
            gate_kind=form.gate_kind,
            status=body.status,
            answers=[
                hitl.HitlAnswer(
                    question_id=a.question_id,
                    option_id=a.option_id,
                    checked=a.checked,
                    notes=a.notes,
                )
                for a in body.answers
            ],
        )
        hitl.save_responses(run_dir, responses)
        errors = hitl.validate_responses(form, responses)
        return {
            "saved": True,
            "complete": not errors,
            "errors": errors,
        }

    @app.post("/api/runs/{run_id}/hitl/submit", tags=["runs"])
    async def submit_hitl(
        run_id: str,
        body: HitlResponsesIn,
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        """Validate responses and rewrite pre0-decisions.md."""
        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        from tripll import hitl

        form = hitl.load_form(run_dir)
        if form is None:
            raise HTTPException(status_code=404, detail="No HITL form for this run")
        responses = hitl.HitlResponses(
            run_id=run_id,
            form_id=form.form_id,
            gate_kind=form.gate_kind,
            status="submitted",
            answers=[
                hitl.HitlAnswer(
                    question_id=a.question_id,
                    option_id=a.option_id,
                    checked=a.checked,
                    notes=a.notes,
                )
                for a in body.answers
            ],
        )
        errors = hitl.validate_responses(form, responses)
        if errors:
            raise HTTPException(status_code=409, detail={"errors": errors})
        hitl.save_responses(run_dir, responses)
        if form.gate_kind == hitl.GateKind.PRE0.value:
            hitl.write_decisions_sheet(run_dir, form, responses)
        return {"submitted": True, "complete": True}

    @app.post("/api/runs/{run_id}/hitl/approve", status_code=202, tags=["runs"])
    async def approve_hitl(
        run_id: str,
        body: HitlResponsesIn | None = None,
        _auth: None = Depends(require_auth),
    ) -> dict[str, str]:
        """Submit responses (if provided) and approve the pending HITL gate."""
        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        from tripll import hitl
        from tripll.adapters import get_adapter
        from tripll.engine import Engine
        from tripll.repo_root import resolve_repo_root

        if body is not None:
            form = hitl.load_form(run_dir)
            if form is None:
                raise HTTPException(status_code=404, detail="No HITL form for this run")
            responses = hitl.HitlResponses(
                run_id=run_id,
                form_id=form.form_id,
                gate_kind=form.gate_kind,
                status="submitted",
                answers=[
                    hitl.HitlAnswer(
                        question_id=a.question_id,
                        option_id=a.option_id,
                        checked=a.checked,
                        notes=a.notes,
                    )
                    for a in body.answers
                ],
            )
            errors = hitl.validate_responses(form, responses)
            if errors:
                raise HTTPException(status_code=409, detail={"errors": errors})
            hitl.save_responses(run_dir, responses)
            if form.gate_kind == hitl.GateKind.PRE0.value:
                hitl.write_decisions_sheet(run_dir, form, responses)

        pending = hitl.detect_pending_gate(run_dir)
        if pending is None:
            raise HTTPException(status_code=409, detail="No pending HITL gate for this run")
        gate_kind = pending.kind.value

        engine = Engine(
            adapter=get_adapter("claude_code"),
            runs_root=rr,
            repo_root=resolve_repo_root(),
        )
        try:
            engine.approve(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"message": f"HITL gate approved ({gate_kind}) for {run_id}"}

    @app.post("/api/runs/{run_id}/resume", status_code=202, tags=["runs"])
    async def resume_run(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, str]:
        """Resume a paused or failed run.

        Spawns ``tripll resume <run_id>`` as a detached subprocess.

        Args:
            run_id (str): Run identifier.

        Returns:
            dict[str, str]: Confirmation message.
        """
        rr: RunsRoot = app.state.runs_root
        _assert_run_exists(rr, run_id)
        from tripll.run_dispatch import resume_cli_extra_argv

        run_dir = rr.find_run_dir(run_id)
        assert run_dir is not None  # guarded by _assert_run_exists
        extra = resume_cli_extra_argv(run_dir)
        _spawn_tripll(["resume", run_id, *extra, "--runs-root", str(rr.root)])
        return {"message": f"Resuming run {run_id}"}

    @app.get("/api/runs/{run_id}/pr/status", tags=["pr"])
    async def get_pr_status(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        """Return PR phase state and merge-gate markers for a run."""
        from tripll.loops.l1_pr import pr_status

        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return pr_status(run_dir=run_dir)

    @app.post("/api/runs/{run_id}/pr/shepherd", status_code=202, tags=["pr"])
    async def pr_shepherd(
        run_id: str,
        phase: str = "investigate_and_fix",
        _auth: None = Depends(require_auth),
    ) -> dict[str, str]:
        """Spawn ``tripll pr shepherd --run <id>`` for one PR loop step."""
        rr: RunsRoot = app.state.runs_root
        _assert_run_exists(rr, run_id)
        _spawn_tripll(
            ["pr", "shepherd", "--run", run_id, "--phase", phase, "--runs-root", str(rr.root)]
        )
        return {"message": f"PR shepherd started for {run_id}"}

    @app.post("/api/runs/{run_id}/pr/approve-merge", status_code=202, tags=["pr"])
    async def pr_approve_merge(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        """Approve the human merge gate — never auto-merges without this call."""
        from tripll.loops.l1_pr import approve_merge_gate, pr_status

        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        try:
            approve_merge_gate(run_dir=run_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "message": f"Merge gate approved for {run_id}",
            "status": pr_status(run_dir=run_dir),
        }

    @app.post("/api/runs/{run_id}/pause", status_code=202, tags=["runs"])
    async def pause_run(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, str]:
        """Request a pause for a run.

        Writes a ``pause-requested.md`` marker file in the run directory.  The
        engine checks this marker at safe dispatch points (before starting each
        new wave) and transitions the run to ``paused``.  In-flight waves are
        **not** killed — they run to completion.

        Args:
            run_id (str): Run identifier.

        Returns:
            dict[str, str]: Confirmation message.
        """
        rr: RunsRoot = app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        marker = run_dir / "pause-requested.md"
        marker.write_text(
            "# Pause requested\n\nThis marker was written by the API control plane.\n"
            "The engine will stop dispatching new waves at the next safe checkpoint.\n"
        )
        logger.info("api: wrote pause marker for run {}", run_id)
        return {"message": f"Pause requested for run {run_id} (marker written)"}

    # ---------------------------------------------------------------------------
    # Waves
    # ---------------------------------------------------------------------------

    @app.get("/api/runs/{run_id}/waves", response_model=list[WaveOut], tags=["waves"])
    async def list_run_waves(
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> list[WaveOut]:
        """List all waves for a run.

        Args:
            run_id (str): Parent run identifier.

        Returns:
            list[WaveOut]: All wave rows ordered by creation time.

        Raises:
            HTTPException: 404 if run not found.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        with open_ledger(ledger_path) as lc:
            waves = list_waves(lc, run_id)
        return [
            WaveOut(
                node_id=w.node_id,
                run_id=w.run_id,
                plan_id=w.plan_id,
                wave_id=w.wave_id,
                lane=w.lane,
                state=w.state,
                attempt_count=w.attempt_count,
                created_at=w.created_at,
                updated_at=w.updated_at,
            )
            for w in waves
        ]

    @app.get("/api/waves/{run_id}/{node_id:path}", response_model=WaveOut, tags=["waves"])
    async def get_wave_detail(
        run_id: str,
        node_id: str,
        _auth: None = Depends(require_auth),
    ) -> WaveOut:
        """Fetch detailed status for a single wave node.

        Args:
            run_id (str): Parent run identifier.
            node_id (str): Node identifier (e.g. ``plan:W1``).

        Returns:
            WaveOut: Wave detail including attempt count and state.

        Raises:
            HTTPException: 404 if wave not found.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        with open_ledger(ledger_path) as lc:
            try:
                w = get_wave(lc, run_id, node_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Wave not found: run={run_id} node={node_id}",
                ) from exc
        return WaveOut(
            node_id=w.node_id,
            run_id=w.run_id,
            plan_id=w.plan_id,
            wave_id=w.wave_id,
            lane=w.lane,
            state=w.state,
            attempt_count=w.attempt_count,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )

    @app.get("/api/runs/{run_id}/waves/{node_id:path}/log", tags=["waves"])
    async def get_wave_log(
        run_id: str,
        node_id: str,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> dict[str, object]:
        """Return a read-only tail of one attempt log (W1.4, D4).

        Args:
            run_id (str): Parent run identifier.
            node_id (str): Wave node identifier.
            attempt (int | None): 1-based attempt number; defaults to latest.

        Returns:
            dict[str, object]: Log tail payload with ``content``, ``attempt_n``,
            and ``truncated`` flag.

        Raises:
            HTTPException: 404 when the run or log file is not found.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
            if not attempts:
                return {
                    "run_id": run_id,
                    "node_id": node_id,
                    "attempt_n": None,
                    "content": "No agent log yet — wave not dispatched.",
                    "truncated": False,
                    "available": False,
                }
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            content, truncated = tail_log_file(log_path)
        except LogPathError:
            return {
                "run_id": run_id,
                "node_id": node_id,
                "attempt_n": attempt_n,
                "content": f"Log file missing for attempt {attempt_n} (engine may still be writing).",
                "truncated": False,
                "available": False,
            }

        return {
            "run_id": run_id,
            "node_id": node_id,
            "attempt_n": attempt_n,
            "content": content,
            "truncated": truncated,
            "available": True,
        }

    @app.get("/api/runs/{run_id}/waves/{node_id:path}/worktree", tags=["waves"])
    async def get_wave_worktree(
        run_id: str,
        node_id: str,
        _auth: None = Depends(require_auth),
    ) -> dict[str, object]:
        """Return git worktree status for one wave node (W3.4, D5).

        Args:
            run_id (str): Parent run identifier.
            node_id (str): Wave node identifier.

        Returns:
            dict[str, object]: Worktree status payload.

        Raises:
            HTTPException: 404 when the run, wave, or worktree is missing.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        with open_ledger(ledger_path) as lc:
            try:
                wave = get_wave(lc, run_id, node_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Wave not found: run={run_id} node={node_id}",
                ) from exc

        wt_path = resolve_wave_worktree_path(rr, run_id, lane=wave.lane, wave_id=wave.wave_id)
        if wt_path is None:
            raise HTTPException(status_code=404, detail=f"Worktree not found for node {node_id}")

        try:
            status = collect_worktree_status(wt_path)
        except WorktreeStatusError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return {
            "run_id": run_id,
            "node_id": node_id,
            "branch": status.branch,
            "changed_count": status.changed_count,
            "changed_paths": status.changed_paths,
            "diff_stat_lines": status.diff_stat_lines,
            "head_sha": status.head_sha,
        }

    # ---------------------------------------------------------------------------
    # Events — poll + SSE
    # ---------------------------------------------------------------------------

    @app.get("/api/runs/{run_id}/events", response_model=list[EventOut], tags=["events"])
    async def poll_events(
        run_id: str,
        after: int = 0,
        _auth: None = Depends(require_auth),
    ) -> list[EventOut]:
        """Poll events for a run (paged by event_id cursor).

        Args:
            run_id (str): Parent run identifier.
            after (int): Return only events with ``event_id > after`` (default 0 = all).

        Returns:
            list[EventOut]: Events ordered by event_id ascending.

        Raises:
            HTTPException: 404 if run not found.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        with open_ledger(ledger_path) as lc:
            events = list_events(lc, run_id, after_event_id=after)
            return [_event_out(rr, lc, e) for e in events]

    @app.get("/api/runs/{run_id}/events/stream", tags=["events"])
    async def stream_events(
        run_id: str,
        request: Request,
        after: int = 0,
        token: str | None = None,
        _auth: None = Depends(require_auth),
    ) -> StreamingResponse:
        """Server-Sent Events stream for live run events.

        Replays events from ``after`` / ``Last-Event-ID`` header, then polls
        for new events every second until the client disconnects.  Each SSE
        event carries the JSON-encoded :class:`EventOut` payload.

        The ``id:`` field of each SSE event is the ``event_id`` so browsers
        and clients can resume with ``Last-Event-ID`` across reconnects.

        Auth note: browsers cannot set ``Authorization`` headers on
        ``EventSource``.  When ``TRIPLL_API_TOKEN`` is set the dashboard
        injects the token as ``?token=<tok>``; the ``require_auth`` dependency
        checks ``Authorization: Bearer`` first, then falls back to the ``token``
        query parameter so the web UI can authenticate.

        Args:
            run_id (str): Parent run identifier.
            request (Request): FastAPI request (used to detect disconnect).
            after (int): Start cursor; overridden by ``Last-Event-ID`` header.
            token (str | None): Optional query-param bearer token for browser
                ``EventSource`` clients that cannot set custom headers.

        Returns:
            StreamingResponse: text/event-stream response.

        Raises:
            HTTPException: 404 if run not found.
        """
        rr: RunsRoot = app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        # Honour Last-Event-ID for reconnect.
        last_id_header = request.headers.get("Last-Event-ID")
        cursor = int(last_id_header) if last_id_header else after

        async def _event_generator() -> AsyncIterator[str]:
            nonlocal cursor, ledger_path
            # Allow env override for faster polling in tests (TRIPLL_SSE_POLL=0.05).
            try:
                poll_interval = float(os.environ.get("TRIPLL_SSE_POLL", "1.0") or "1.0")
            except ValueError:
                poll_interval = 1.0
            while True:
                if await request.is_disconnected():
                    break
                with open_ledger(ledger_path) as lc:
                    events = list_events(lc, run_id, after_event_id=cursor)
                    # If no new events and run is in a terminal state, close the stream.
                    if not events:
                        try:
                            row = get_run(lc, run_id)
                            if row.state in ("done", "failed", "paused"):
                                break
                        except KeyError:
                            break
                    for e in events:
                        payload = json.dumps(_event_payload(rr, lc, e))
                        yield f"id: {e.event_id}\ndata: {payload}\n\n"
                        cursor = e.event_id
                await asyncio.sleep(poll_interval)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ---------------------------------------------------------------------------
    # Config
    # ---------------------------------------------------------------------------

    @app.get("/api/config", response_model=ConfigOut, tags=["config"])
    async def get_config(
        _auth: None = Depends(require_auth),
    ) -> ConfigOut:
        """Return current runtime configuration (env-var based).

        Returns:
            ConfigOut: Model default, cost budget, and max parallelism.
        """
        return _read_config()

    @app.put("/api/config", response_model=ConfigOut, tags=["config"])
    async def put_config(
        data: ConfigIn,
        _auth: None = Depends(require_auth),
    ) -> ConfigOut:
        """Update runtime configuration (mutates environment variables in-process).

        Changes apply to newly spawned subprocesses; running engines are not
        affected.

        Args:
            data (ConfigIn): Fields to update (omitted = unchanged).

        Returns:
            ConfigOut: Updated configuration.
        """
        if data.model_default is not None:
            os.environ["TRIPLL_DEFAULT_MODEL"] = data.model_default
        if data.cost_budget_usd is not None:
            os.environ["TRIPLL_COST_BUDGET_USD"] = str(data.cost_budget_usd)
        if data.max_parallel is not None:
            os.environ["TRIPLL_MAX_PARALLEL"] = str(data.max_parallel)
        return _read_config()

    # ---------------------------------------------------------------------------
    # Backends
    # ---------------------------------------------------------------------------

    @app.get("/api/backends", response_model=list[BackendOut], tags=["config"])
    async def list_backends(
        _auth: None = Depends(require_auth),
    ) -> list[BackendOut]:
        """List available backends and their availability status.

        Returns:
            list[BackendOut]: One entry per registered backend.
        """
        from tripll.adapters import BACKENDS, get_adapter

        results: list[BackendOut] = []
        for name in sorted(BACKENDS):
            try:
                adapter = get_adapter(name)
                caps = adapter.capabilities()
                results.append(
                    BackendOut(
                        name=name,
                        available=caps.available,
                        detail=caps.detail,
                        streaming=caps.streaming,
                    )
                )
            except Exception as exc:
                results.append(
                    BackendOut(name=name, available=False, detail=str(exc), streaming=False)
                )
        return results

    return app


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_runs_root(runs_root: Path | None) -> RunsRoot:
    """Resolve the runs root from an explicit path or env/default.

    Uses the same repo-root-anchored default as the CLI so the runs directory
    is identical whether tripll is invoked via ``tripll serve`` from the
    repo root, from inside ``wave-orchestrator/``, or from any other CWD.

    The default path is ``<repo_root>/wave-orchestrator/runs/`` where
    *repo_root* is resolved by :func:`~tripll.repo_root.resolve_repo_root`
    (honours ``TRIPLL_REPO_ROOT`` env, then walks up for ``.git``).

    Args:
        runs_root (Path | None): Explicit override, or ``None`` to use default.

    Returns:
        RunsRoot: Configured runs root instance.
    """
    if runs_root is not None:
        return RunsRoot(runs_root)
    env_path = os.environ.get("TRIPLL_RUNS")
    if env_path:
        return RunsRoot(Path(env_path))
    from tripll.repo_root import resolve_repo_root

    repo_root = resolve_repo_root()
    return RunsRoot((repo_root / "wave-orchestrator" / "runs").resolve())


def _tripll_argv() -> list[str]:
    """Return the base argv to invoke the ``tripll`` CLI.

    Uses the same Python interpreter so the installed package is found.

    Returns:
        list[str]: Base argv (e.g. ``[sys.executable, "-m", "tripll.cli"]``).
    """
    return [sys.executable, "-m", "tripll.cli"]


def _spawn_tripll(args: list[str]) -> None:
    """Spawn a detached ``tripll`` subprocess with *args*.

    Args:
        args (list[str]): Arguments to pass after the base ``tripll`` argv.
    """
    argv = [*_tripll_argv(), *args]
    logger.info("api: spawning tripll {}", args)
    subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _assert_run_exists(rr: RunsRoot, run_id: str) -> None:
    """Raise 404 HTTPException if *run_id* is not found.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier to check.

    Raises:
        HTTPException: 404 if run not found.
    """
    if rr.find_run_dir(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


def _read_pid(run_dir: Path | None) -> int | None:
    """Read the engine PID from ``engine.pid`` if present.

    Args:
        run_dir (Path | None): Run directory, or ``None`` if run dir not found.

    Returns:
        int | None: PID integer, or ``None`` if the file is absent or malformed.
    """
    if run_dir is None:
        return None
    pid_file = run_dir / "engine.pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _infer_task_id(rr: RunsRoot, lc: LedgerConnection, e: EventRow) -> str | None:
    """Optionally infer ``task_id`` from staged plan + ``last_action`` (W3.5)."""
    if not e.last_action or e.phase not in ("running", "verifying"):
        return None
    try:
        wave = get_wave(lc, e.run_id, e.node_id)
    except KeyError:
        return None
    wt_path = resolve_wave_worktree_path(rr, e.run_id, lane=wave.lane, wave_id=wave.wave_id)
    if wt_path is None:
        return None
    plan_text = load_staged_wave_plan_text(wt_path, wave.wave_id)
    if not plan_text:
        return None
    return infer_active_task(
        plan_text,
        last_action=e.last_action,
        phase=e.phase,
    ).inferred_task_id


def _event_payload(rr: RunsRoot, lc: LedgerConnection, e: EventRow) -> dict[str, object]:
    """Serialize one event for poll/SSE with optional W3 fields (backward compatible)."""
    task_id = _infer_task_id(rr, lc, e)
    payload: dict[str, object] = {
        "event_id": e.event_id,
        "run_id": e.run_id,
        "node_id": e.node_id,
        "ts": e.ts,
        "phase": e.phase,
        "last_action": e.last_action,
        "input_tokens": e.input_tokens,
        "output_tokens": e.output_tokens,
        "cost_usd": e.cost_usd,
    }
    if e.attempt_n is not None:
        payload["attempt_n"] = e.attempt_n
    if e.metadata is not None:
        payload["metadata"] = e.metadata
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def _event_out(rr: RunsRoot, lc: LedgerConnection, e: EventRow) -> EventOut:
    """Build :class:`EventOut` with optional W3 enrichment fields."""
    return EventOut(
        event_id=e.event_id,
        run_id=e.run_id,
        node_id=e.node_id,
        ts=e.ts,
        phase=e.phase,
        last_action=e.last_action,
        input_tokens=e.input_tokens,
        output_tokens=e.output_tokens,
        cost_usd=e.cost_usd,
        attempt_n=e.attempt_n,
        task_id=_infer_task_id(rr, lc, e),
        metadata=e.metadata,
    )


def _read_config() -> ConfigOut:
    """Read current config from environment variables.

    Returns:
        ConfigOut: Current model default, budget, and parallelism.
    """
    model_default = os.environ.get("TRIPLL_DEFAULT_MODEL", "claude-sonnet-5")
    try:
        cost_budget = float(os.environ.get("TRIPLL_COST_BUDGET_USD", "0") or "0")
    except ValueError:
        cost_budget = 0.0
    try:
        max_parallel = int(os.environ.get("TRIPLL_MAX_PARALLEL", "3") or "3")
    except ValueError:
        max_parallel = 3
    return ConfigOut(
        model_default=model_default,
        cost_budget_usd=cost_budget,
        max_parallel=max_parallel,
    )
