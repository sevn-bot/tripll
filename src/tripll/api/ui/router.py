"""tripll.api.ui.router — Dashboard page routes (W5 + W1 + W2).

Server-rendered HTML pages:

- ``GET /`` — runs home: launch-run form, runs list, backends (W2).
- ``GET /runs/{run_id}`` — run detail (W1).
- ``GET /agents``, ``/agents/new``, ``/agents/{id}/edit`` — profile CRUD (W2).
- ``GET /settings`` — runtime config form (W2).

Fragment routes (W1-W4):

- ``GET /runs/{run_id}/timeline`` — event timeline partial (W1.3).
- ``GET /runs/{run_id}/waves/{node_id}/log`` — log tail viewer (W1.4, D4).
- ``GET /runs/{run_id}/batch-timeline`` — batch swimlane chart (W4.1).
- ``GET /runs/{run_id}/report`` — report.md embed (W4.3).
- ``GET /runs/{run_id}/orchestrator`` — orchestrator panel + feed (W5).

Auth
----
When ``TRIPLL_API_TOKEN`` is set, the token is injected into the rendered
page (inside the EventSource URL query-parameter and htmx hx-headers) so the
browser can authenticate against the SSE and action endpoints.  Fragment GETs
accept the same ``?token=`` query param (D12).  In dev mode (no token)
everything works without credentials.

No Node / build toolchain
--------------------------
``htmx.min.js`` and ``htmx-sse.js`` are vendored under ``src/tripll/api/ui/static/``.
The CSS is minimal and fully inline inside the base template.

Exports:
    make_ui_router — factory that returns the configured ``APIRouter``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from tripll.api._artefacts import (
    MAX_LOG_FULL_BYTES,
    MAX_LOG_PANEL_BYTES,
    TIMELINE_EVENT_LIMIT,
    LogPathError,
    build_batch_timeline,
    parse_escalation_reasons,
    read_log_file,
    read_log_file_from_offset,
    read_pause_banners,
    read_report_markdown,
    render_report_markdown,
    resolve_attempt_log_path,
    tail_log_file,
)
from tripll.api._auth import require_auth
from tripll.api._csrf import ensure_csrf_token, require_csrf
from tripll.api._l1_panels import build_l1_panels
from tripll.api._orchestrator_ui import build_orchestrator_view
from tripll.api._runs import RunSummary, _find_ledger, _is_run_live, _list_all_runs
from tripll.api._worktree_status import (
    WORKTREE_POLL_INTERVAL_S,
    WorktreeStatusError,
    collect_worktree_status,
    load_wave_plan_text_for_node,
    resolve_wave_worktree_path,
    should_poll_worktree,
)
from tripll.api.app import _read_config, _slug_profile_id, _tripll_argv
from tripll.ledger import (
    EventRow,
    WaveRow,
    get_run,
    get_run_cost,
    latest_events_by_node,
    list_attempts,
    list_events,
    list_fired_exit_ids,
    list_waves,
    open_ledger,
)
from tripll.profiles import (
    ProfileRow,
    control_plane_db_path,
    get_profile,
    list_profiles,
    open_profile_store,
    upsert_profile,
)
from tripll.wave_task import WaveTaskResult, infer_active_task

if TYPE_CHECKING:
    from tripll.ledger import LedgerConnection
    from tripll.pipeline import RunsRoot

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def fragment_url(run_id: str, node_id: str, suffix: str, *, api_token: str = "") -> str:
    """Build an htmx-safe fragment URL for *node_id* (auth via ``hx-headers``)."""
    _ = api_token  # callers pass token for template symmetry; auth is header-based (R6)
    return f"/runs/{run_id}/waves/{quote(node_id, safe='')}/{suffix}"


def log_full_page_url(
    run_id: str,
    node_id: str,
    attempt_n: int,
    *,
    api_token: str = "",
) -> str:
    """Build URL for the full-page attempt log viewer."""
    _ = api_token
    return f"/runs/{run_id}/waves/{quote(node_id, safe='')}/log/full?attempt={attempt_n}"


def log_append_url(run_id: str, node_id: str, *, api_token: str = "") -> str:
    """Build append-only log poll URL for *node_id*."""
    return fragment_url(run_id, node_id, "log/append", api_token=api_token)


def log_fragment_url(run_id: str, node_id: str, *, api_token: str = "") -> str:
    """Build an htmx-safe log fragment URL for *node_id*."""
    return fragment_url(run_id, node_id, "log", api_token=api_token)


def make_ui_router() -> APIRouter:
    """Construct the dashboard ``APIRouter``.

    The returned router must be ``app.include_router(...)``'d from
    ``create_app()`` **after** ``app.state.runs_root`` is set.

    Returns:
        APIRouter: Router with dashboard and fragment routes.

    Examples:
        >>> from tripll.api.ui import make_ui_router
        >>> router = make_ui_router()
        >>> router.routes  # doctest: +ELLIPSIS
        [...]
    """
    router = APIRouter(include_in_schema=False)
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["log_full_page_url"] = log_full_page_url

    # ------------------------------------------------------------------
    # GET / — dashboard home
    # ------------------------------------------------------------------

    @router.get("/", response_class=HTMLResponse)
    async def dashboard_home(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the dashboard home page.

        Displays all runs (active, processed, failed), agent profiles, and
        backend availability.

        Args:
            request (Request): Incoming FastAPI request (needed by Jinja2).

        Returns:
            HTMLResponse: Rendered ``index.html`` template.
        """
        rr: RunsRoot = request.app.state.runs_root

        # Runs.
        runs: list[RunSummary] = _list_all_runs(rr)

        # Agent profiles.
        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with open_profile_store(db_path) as store:
            profiles = list_profiles(store)

        # Backends — import lazily so ui router doesn't force adapters at import time.
        from tripll.adapters import BACKENDS, get_adapter

        backends: list[dict[str, Any]] = []
        for name in sorted(BACKENDS):
            try:
                adapter = get_adapter(name)
                caps = adapter.capabilities()
                backends.append(
                    {
                        "name": name,
                        "available": caps.available,
                        "detail": caps.detail,
                        "streaming": caps.streaming,
                    }
                )
            except Exception as exc:
                backends.append(
                    {"name": name, "available": False, "detail": str(exc), "streaming": False}
                )

        ctx: dict[str, Any] = _ui_context(
            request,
            nav_section="runs",
            runs=runs,
            profiles=profiles,
            backends=backends,
            input_sets=rr.list_input(),
        )
        return templates.TemplateResponse(request, "index.html", ctx)

    # ------------------------------------------------------------------
    # POST /launch — launch run form (W2.3)
    # ------------------------------------------------------------------

    @router.post("/launch")
    async def launch_run_form(
        request: Request,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Accept launch-run form POST; spawn engine and redirect to run detail."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        input_path_str = str(form.get("input_path_custom", "")).strip()
        if not input_path_str:
            input_path_str = str(form.get("input_path", "")).strip()
        profile_id = str(form.get("profile_id", "")).strip()

        if not input_path_str or not profile_id:
            return RedirectResponse("/", status_code=303)

        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                profile = get_profile(store, profile_id)
            except KeyError:
                return RedirectResponse("/", status_code=303)

        input_path = Path(input_path_str)
        if not input_path.exists():  # noqa: ASYNC240
            return RedirectResponse("/", status_code=303)

        argv = [
            *_tripll_argv(),
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
        subprocess.Popen(  # noqa: ASYNC220
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        slug = input_path.name
        for _ in range(15):
            await asyncio.sleep(0.2)
            runs: list[RunSummary] = _list_all_runs(rr)
            for run in reversed(runs):
                if run.slug == slug and run.is_live:
                    return RedirectResponse(f"/runs/{run.run_id}", status_code=303)

        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------------
    # GET /agents — profile list (W2.4)
    # ------------------------------------------------------------------

    @router.get("/agents", response_class=HTMLResponse)
    async def agents_list(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the agent profiles list page."""
        rr: RunsRoot = request.app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with open_profile_store(db_path) as store:
            profiles = list_profiles(store)
        ctx = _ui_context(request, nav_section="agents", profiles=profiles)
        return templates.TemplateResponse(request, "agents.html", ctx)

    # ------------------------------------------------------------------
    # GET/POST /agents/new — create profile (W2.4)
    # ------------------------------------------------------------------

    @router.get("/agents/new", response_class=HTMLResponse)
    async def agents_new_form(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the new-agent profile form."""
        ctx = _ui_context(
            request,
            nav_section="agents",
            form_title="New agent profile",
            form_action="/agents/new",
            submit_label="Create profile",
            is_new=True,
            profile=_empty_profile_form(),
            backends=_backend_names(),
        )
        return templates.TemplateResponse(request, "agent_form.html", ctx)

    @router.post("/agents/new")
    async def agents_new_submit(
        request: Request,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Create an agent profile from form POST."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        parsed = _parse_agent_form(form)
        if parsed is None:
            return RedirectResponse("/agents/new", status_code=303)

        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        raw_id = str(form.get("profile_id", "")).strip()
        profile_id = _slug_profile_id(raw_id) if raw_id else _slug_profile_id(parsed["name"])

        with open_profile_store(db_path) as store:
            try:
                get_profile(store, profile_id)
            except KeyError:
                pass
            else:
                base_id = profile_id
                suffix = 1
                while True:
                    try:
                        get_profile(store, profile_id)
                        profile_id = f"{base_id}-{suffix}"
                        suffix += 1
                    except KeyError:
                        break
            upsert_profile(store, profile_id=profile_id, **parsed)

        return RedirectResponse("/agents", status_code=303)

    # ------------------------------------------------------------------
    # GET/POST /agents/{profile_id}/edit — edit profile (W2.4)
    # ------------------------------------------------------------------

    @router.get("/agents/{profile_id}/edit", response_class=HTMLResponse)
    async def agents_edit_form(
        request: Request,
        profile_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the edit-agent profile form."""
        rr: RunsRoot = request.app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                row = get_profile(store, profile_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail=f"Profile not found: {profile_id}"
                ) from exc

        ctx = _ui_context(
            request,
            nav_section="agents",
            form_title=f"Edit {row.name}",
            form_action=f"/agents/{profile_id}/edit",
            submit_label="Save changes",
            is_new=False,
            profile=_profile_form_from_row(row),
            backends=_backend_names(),
        )
        return templates.TemplateResponse(request, "agent_form.html", ctx)

    @router.post("/agents/{profile_id}/edit")
    async def agents_edit_submit(
        request: Request,
        profile_id: str,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Update an agent profile from form POST."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        parsed = _parse_agent_form(form)
        if parsed is None:
            return RedirectResponse(f"/agents/{profile_id}/edit", status_code=303)

        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                get_profile(store, profile_id)
            except KeyError:
                return RedirectResponse("/agents", status_code=303)
            upsert_profile(store, profile_id=profile_id, **parsed)

        return RedirectResponse("/agents", status_code=303)

    # ------------------------------------------------------------------
    # GET/POST /settings — runtime config (W2.5)
    # ------------------------------------------------------------------

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the settings form bound to runtime config env vars."""
        saved = request.query_params.get("saved") == "1"
        ctx = _ui_context(request, nav_section="settings", config=_read_config(), saved=saved)
        return templates.TemplateResponse(request, "settings.html", ctx)

    @router.post("/settings")
    async def settings_submit(
        request: Request,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Update runtime config from form POST."""
        form = await request.form()
        model_default = str(form.get("model_default", "")).strip()
        if model_default:
            os.environ["TRIPLL_DEFAULT_MODEL"] = model_default
        cost_raw = str(form.get("cost_budget_usd", "")).strip()
        if cost_raw:
            os.environ["TRIPLL_COST_BUDGET_USD"] = cost_raw
        max_raw = str(form.get("max_parallel", "")).strip()
        if max_raw:
            os.environ["TRIPLL_MAX_PARALLEL"] = max_raw
        return RedirectResponse("/settings?saved=1", status_code=303)

    # ------------------------------------------------------------------
    # GET /runs/{run_id} — run detail
    # ------------------------------------------------------------------

    @router.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the hydrated run-detail page for *run_id* (W1.1).

        Shows a per-wave table merged with ``latest_events_by_node`` (D2),
        run header, event timeline replay, and live SSE row updates.

        Args:
            request (Request): Incoming FastAPI request.
            run_id (str): Run identifier.

        Returns:
            HTMLResponse: Rendered ``run_detail.html`` template.

        Raises:
            HTTPException: 404 when the run is not found.
        """
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_run_detail_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        ctx.update(_ui_context(request, nav_section="runs"))
        ctx["sse_url"] = f"/api/runs/{run_id}/events/stream"
        return templates.TemplateResponse(request, "run_detail.html", ctx)

    # ------------------------------------------------------------------
    # Fragment routes (timeline, log, worktree, tasks, batch-timeline, report)
    # ------------------------------------------------------------------

    @router.get("/runs/{run_id}/timeline", response_class=HTMLResponse)
    async def run_timeline_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Scrollable event timeline partial (W1.3, D3)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        with open_ledger(ledger_path) as lc:
            timeline_events = _timeline_events(lc, run_id)
        return templates.TemplateResponse(
            request,
            "_timeline.html",
            {"timeline_events": timeline_events},
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/log", response_class=HTMLResponse)
    async def wave_log_fragment(
        request: Request,
        run_id: str,
        node_id: str,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Per-wave log tail viewer partial (W1.4, D4). Accepts ``?token=`` when auth set (D12)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
                latest = latest_events_by_node(lc, run_id).get(node_id)
                wave = _get_wave_row(lc, run_id, node_id)
            if not attempts:
                run_dir = rr.find_run_dir(run_id)
                escalation_reasons = parse_escalation_reasons(run_dir)
                phase = latest.phase if latest is not None else (wave.state if wave else "queued")
                last_action = latest.last_action if latest and latest.last_action else ""
                status_detail = _wave_status_detail(
                    node_id=node_id,
                    wave_id=wave.wave_id if wave else node_id.split(":")[-1],
                    phase=phase,
                    last_action=last_action,
                    attempts=[],
                    escalation_reasons=escalation_reasons,
                )
                log_message = status_detail or "No agent log yet — wave not dispatched."
                return templates.TemplateResponse(
                    request,
                    "_log_viewer.html",
                    {
                        "attempt_n": None,
                        "log_content": log_message,
                        "truncated": False,
                        "log_available": False,
                    },
                )
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            content, truncated = tail_log_file(log_path, max_bytes=MAX_LOG_PANEL_BYTES)
            log_byte_offset = log_path.stat().st_size
        except LogPathError:
            return templates.TemplateResponse(
                request,
                "_log_viewer.html",
                {
                    "attempt_n": attempt_n,
                    "log_content": (
                        f"Log file missing for attempt {attempt_n} (engine may still be writing)."
                    ),
                    "truncated": False,
                    "log_available": False,
                },
            )

        token = _get_token()
        return templates.TemplateResponse(
            request,
            "_log_viewer.html",
            {
                "attempt_n": attempt_n,
                "log_content": content,
                "truncated": truncated,
                "log_available": True,
                "run_id": run_id,
                "node_id": node_id,
                "full_log_url": log_full_page_url(
                    run_id,
                    node_id,
                    attempt_n,
                    api_token=token,
                ),
                "log_append_url": log_append_url(run_id, node_id, api_token=token),
                "log_byte_offset": log_byte_offset,
            },
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/log/append")
    async def wave_log_append(
        request: Request,
        run_id: str,
        node_id: str,
        offset: int = 0,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> JSONResponse:
        """Append-only log bytes for live panel polling (preserves scroll position)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
            if not attempts:
                return JSONResponse({"text": "", "offset": 0, "truncated": False})
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            text, new_offset, truncated = read_log_file_from_offset(log_path, offset)
        except LogPathError:
            return JSONResponse({"text": "", "offset": offset, "truncated": False})

        return JSONResponse(
            {
                "text": text,
                "offset": new_offset,
                "truncated": truncated,
                "attempt_n": attempt_n,
            }
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/log/full", response_class=HTMLResponse)
    async def wave_log_full_page(
        request: Request,
        run_id: str,
        node_id: str,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Full attempt log in a standalone page (opens in new tab)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
            if not attempts:
                raise HTTPException(status_code=404, detail="No attempts for this wave")
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            content, truncated = read_log_file(log_path, max_bytes=MAX_LOG_FULL_BYTES)
        except LogPathError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return templates.TemplateResponse(
            request,
            "log_full.html",
            {
                "run_id": run_id,
                "node_id": node_id,
                "attempt_n": attempt_n,
                "log_content": content,
                "truncated": truncated,
                "full_log_url": None,
                "log_available": True,
                **_ui_context(request, nav_section="runs"),
            },
        )

    @router.get("/runs/{run_id}/waves-table", response_class=HTMLResponse)
    async def waves_table_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Refreshable waves table body for SSE terminal-state sync."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_run_detail_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(
            request,
            "_waves_tbody.html",
            ctx,
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/worktree", response_class=HTMLResponse)
    async def wave_worktree_fragment(
        request: Request,
        run_id: str,
        node_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Git worktree status partial (W3.4, D5). Poll every 5s while running."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_worktree_fragment_context(rr, run_id, node_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_worktree_panel.html", ctx)

    @router.get("/runs/{run_id}/waves/{node_id:path}/tasks", response_class=HTMLResponse)
    async def wave_tasks_fragment(
        request: Request,
        run_id: str,
        node_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Wave-task checklist partial (W3.3, D6). Reload on SSE ``last_action`` change."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_tasks_fragment_context(rr, run_id, node_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_wave_tasks.html", ctx)

    @router.get("/runs/{run_id}/batch-timeline", response_class=HTMLResponse)
    async def batch_timeline_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Batch swimlane partial from ``graph.json`` / ``report.md`` (W4.1, D9)."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_batch_timeline_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_batch_timeline.html", ctx)

    @router.get("/runs/{run_id}/report", response_class=HTMLResponse)
    async def run_report_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Rendered ``report.md`` embed partial (W4.3)."""
        rr: RunsRoot = request.app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        report_text = read_report_markdown(run_dir)
        if report_text is None:
            raise HTTPException(status_code=404, detail="report.md not found")
        return templates.TemplateResponse(
            request,
            "_report.html",
            {"report_html": render_report_markdown(report_text)},
        )

    @router.get("/runs/{run_id}/orchestrator", response_class=HTMLResponse)
    async def run_orchestrator_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Orchestrator panel + turn feed partial (W5.3, D13)."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_orchestrator_fragment_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_orchestrator.html", ctx)

    return router


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_token() -> str:
    """Return the configured API token, or empty string in dev mode.

    Returns:
        str: The ``TRIPLL_API_TOKEN`` value, or ``""`` when unset.
    """
    return os.environ.get("TRIPLL_API_TOKEN", "").strip()


def _ui_context(request: Request, *, nav_section: str, **extra: Any) -> dict[str, Any]:
    """Build common template context with nav chrome (W2.1 + W3 CSRF).

    Args:
        request (Request): Active request (CSRF token + cookie pairing).
        nav_section (str): Active nav item (``runs``, ``agents``, ``settings``).
        **extra: Additional template variables.

    Returns:
        dict[str, Any]: Context dict including ``api_token``, ``csrf_token``, and
        ``nav_section``.
    """
    ctx: dict[str, Any] = {"api_token": _get_token(), "nav_section": nav_section}
    if _get_token():
        ctx["csrf_token"] = ensure_csrf_token(request)
    ctx.update(extra)
    return ctx


def _backend_names() -> list[str]:
    """Return sorted registered backend names for form selects.

    Returns:
        list[str]: Backend identifiers.
    """
    from tripll.adapters import BACKENDS

    return sorted(BACKENDS)


def _empty_profile_form() -> dict[str, str]:
    """Default field values for a new agent profile form.

    Returns:
        dict[str, str]: Template-ready profile dict.
    """
    return {
        "profile_id": "",
        "name": "",
        "backend": "claude_code",
        "model": "claude-sonnet-5",
        "agent": "wave-plan-executor",
        "skills_text": "[]",
    }


def _profile_form_from_row(row: ProfileRow) -> dict[str, str]:
    """Convert a profile row to agent form field dict.

    Args:
        row (ProfileRow): Stored profile.

    Returns:
        dict[str, str]: Template-ready profile dict.
    """
    return {
        "profile_id": row.profile_id,
        "name": row.name,
        "backend": row.backend,
        "model": row.model,
        "agent": row.agent,
        "skills_text": json.dumps(row.skills),
    }


def _parse_skills(raw: str) -> list[str]:
    """Parse skills from JSON array or comma-separated text.

    Args:
        raw (str): Raw form field value.

    Returns:
        list[str]: Parsed skill names.
    """
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _parse_agent_form(form: Any) -> dict[str, Any] | None:
    """Parse agent profile fields from a submitted form.

    Args:
        form: Starlette form data.

    Returns:
        dict[str, Any] | None: Fields for :func:`~tripll.profiles.upsert_profile`,
        or ``None`` when required fields are missing.
    """
    name = str(form.get("name", "")).strip()
    backend = str(form.get("backend", "")).strip()
    model = str(form.get("model", "")).strip()
    agent = str(form.get("agent", "")).strip()
    if not name or not backend or not model or not agent:
        return None
    return {
        "name": name,
        "backend": backend,
        "model": model,
        "agent": agent,
        "skills": _parse_skills(str(form.get("skills", ""))),
    }


def _timeline_events(lc: LedgerConnection, run_id: str) -> list[EventRow]:
    """Return the last :data:`TIMELINE_EVENT_LIMIT` events for *run_id*.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        list[EventRow]: Events ordered by ``event_id`` ascending.
    """
    events = list_events(lc, run_id)
    if len(events) > TIMELINE_EVENT_LIMIT:
        return events[-TIMELINE_EVENT_LIMIT:]
    return events


def _model_from_brief_path(brief_path: str | None) -> str | None:
    """Read ``model`` from a dispatch brief JSON file when present."""
    if not brief_path:
        return None
    try:
        data = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    model = str(data.get("model") or "").strip()
    return model or None


def _format_attempt_started(started_at: str | None) -> str:
    if not started_at:
        return "—"
    text = started_at.replace("T", " ").replace("Z", "")
    return text[:19] if len(text) >= 19 else text


def _attempt_display_rows(attempts: list[Any]) -> list[dict[str, Any]]:
    """Template-ready attempt rows with model, tokens, and timestamps."""
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        model = _model_from_brief_path(getattr(attempt, "brief_path", None)) or "—"
        inp = getattr(attempt, "input_tokens", None)
        out = getattr(attempt, "output_tokens", None)
        if inp is not None and out is not None:
            tokens = f"{inp}→{out}"
        elif inp is not None or out is not None:
            tokens = f"{inp or 0}→{out or 0}"
        else:
            tokens = "—"
        rows.append(
            {
                "attempt_n": attempt.attempt_n,
                "attempt_id": attempt.attempt_id,
                "started_at": _format_attempt_started(getattr(attempt, "started_at", None)),
                "outcome": attempt.outcome or "—",
                "evidence": attempt.evidence or "—",
                "cost_usd": attempt.cost_usd,
                "model": model,
                "backend": getattr(attempt, "backend", "") or "—",
                "tokens": tokens,
            }
        )
    return rows


def _wave_model_label(attempts: list[Any]) -> str:
    for attempt in reversed(attempts):
        model = _model_from_brief_path(getattr(attempt, "brief_path", None))
        if model:
            return model
    return "—"


def _is_human_gate_done(*, wave_id: str, phase: str, has_attempts: bool) -> bool:
    """True when a human-gate wave finished without agent dispatch."""
    return phase == "done" and not has_attempts and wave_id in ("W0", "Pre-0")


def _wave_status_detail(
    *,
    node_id: str,
    wave_id: str,
    phase: str,
    last_action: str,
    attempts: list[Any],
    escalation_reasons: dict[str, str],
) -> str | None:
    """Return a human-readable status or failure reason for dashboard panels."""
    if _is_human_gate_done(wave_id=wave_id, phase=phase, has_attempts=bool(attempts)):
        return "Human gate completed — no agent dispatch required."

    if phase == "gate_pending":
        return "Awaiting human gate approval before dispatch."

    for attempt in reversed(attempts):
        evidence = getattr(attempt, "evidence", None)
        if evidence:
            return str(evidence)

    if last_action:
        return last_action

    reason = escalation_reasons.get(node_id)
    if reason:
        return reason

    if phase == "blocked":
        return "Wave blocked — see escalation.md for details."
    if phase == "failed":
        return "Wave failed — see escalation.md for details."

    return None


def _build_wave_rows(
    waves: list[WaveRow],
    latest: dict[str, EventRow],
    *,
    rr: RunsRoot,
    run_id: str,
    lc: LedgerConnection,
) -> list[dict[str, Any]]:
    """Merge wave ledger rows with collapsed event state (D2) and W3 panels.

    Args:
        waves (list[WaveRow]): Wave rows from the ledger.
        latest (dict[str, EventRow]): Collapsed events per node.
        rr (RunsRoot): Configured runs root.
        run_id (str): Parent run identifier.
        lc (LedgerConnection): Open ledger connection.

    Returns:
        list[dict[str, Any]]: Template-ready wave row dicts.
    """
    run_dir = rr.find_run_dir(run_id)
    escalation_reasons = parse_escalation_reasons(run_dir)
    rows: list[dict[str, Any]] = []
    for w in waves:
        ev = latest.get(w.node_id)
        phase = ev.phase if ev is not None else w.state
        last_action = ev.last_action if ev and ev.last_action else ""
        attempt_ctx = _attempt_panel_context(lc, run_id, w.node_id, phase, w.attempt_count)
        task_result = _infer_wave_tasks(rr, run_id, w, last_action, phase)
        poll_worktree = should_poll_worktree(phase)
        has_attempts = len(attempt_ctx["attempts"]) > 0
        is_human_gate_done = _is_human_gate_done(
            wave_id=w.wave_id,
            phase=phase,
            has_attempts=has_attempts,
        )
        is_gate_only = (
            not has_attempts and phase in ("queued", "gate_pending") and not is_human_gate_done
        )
        status_detail = _wave_status_detail(
            node_id=w.node_id,
            wave_id=w.wave_id,
            phase=phase,
            last_action=last_action,
            attempts=attempt_ctx["attempts"],
            escalation_reasons=escalation_reasons,
        )
        show_log_panel = has_attempts or phase in (
            "running",
            "verifying",
            "done",
            "failed",
            "blocked",
            "dispatched",
        )
        rows.append(
            {
                "node_id": w.node_id,
                "lane": w.lane,
                "wave_id": w.wave_id,
                "phase": phase,
                "last_action": last_action,
                "display_action": last_action or status_detail or "—",
                "status_detail": status_detail,
                "model": _wave_model_label(attempt_ctx["attempts"]),
                "input_tokens": ev.input_tokens if ev else None,
                "output_tokens": ev.output_tokens if ev else None,
                "cost_usd": ev.cost_usd if ev else None,
                "poll_worktree": poll_worktree,
                "poll_log": phase in ("running", "verifying", "dispatched"),
                "log_poll_s": 3,
                "worktree_poll_s": WORKTREE_POLL_INTERVAL_S,
                "has_attempts": has_attempts,
                "is_gate_only": is_gate_only,
                "is_human_gate_done": is_human_gate_done,
                "show_log_panel": show_log_panel,
                **attempt_ctx,
                "task_result": task_result,
            }
        )
    return rows


def _build_run_detail_context(rr: RunsRoot, run_id: str) -> dict[str, Any] | None:
    """Build template context for ``run_detail.html``.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier.

    Returns:
        dict[str, Any] | None: Context dict, or ``None`` when the run is missing.
    """
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None

    run_dir = rr.find_run_dir(run_id)
    is_live = _is_run_live(run_dir)
    logs_dir = run_dir / "logs" if run_dir is not None else None
    log_file_count = 0
    if logs_dir is not None and logs_dir.is_dir():
        log_file_count = sum(1 for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".log")
    report_exists = run_dir is not None and (run_dir / "report.md").is_file()
    pause_banners = read_pause_banners(run_dir)

    with open_ledger(ledger_path) as lc:
        run_row = get_run(lc, run_id)
        waves = list_waves(lc, run_id)
        latest = latest_events_by_node(lc, run_id)
        timeline_events = _timeline_events(lc, run_id)
        run_cost = get_run_cost(lc, run_id)
        fired_exit_ids = list_fired_exit_ids(lc, run_id)
        wave_rows = _build_wave_rows(waves, latest, rr=rr, run_id=run_id, lc=lc)
        ledger_node_ids = [w.node_id for w in waves]
        batch_timeline = build_batch_timeline(
            run_dir,
            latest=latest,
            ledger_node_ids=ledger_node_ids,
        )
        wave_to_node = {w.wave_id: w.node_id for w in waves}
        orch = build_orchestrator_view(
            run_dir,
            run_id=run_id,
            wave_to_node=wave_to_node,
            is_live=is_live,
            api_token=_get_token(),
        )

    from tripll import hitl
    from tripll.repo_root import resolve_repo_root

    hitl_info = hitl.hitl_status(run_dir) if run_dir is not None else {"pending": False}
    l1 = build_l1_panels(
        run_dir=run_dir,
        waves=waves,
        run_cost=run_cost,
        repo_root=resolve_repo_root(),
        fired_exit_ids=fired_exit_ids,
    )

    return {
        "run_id": run_id,
        "run_state": run_row.state,
        "run_cost": run_cost,
        "is_live": is_live,
        "log_file_count": log_file_count,
        "report_exists": report_exists,
        "pause_banners": pause_banners,
        "batch_timeline": batch_timeline,
        "waves": wave_rows,
        "timeline_events": timeline_events,
        "orch": orch,
        "wave_summary": orch.wave_summary,
        "hitl": hitl_info,
        "l1": l1,
    }


def _build_orchestrator_fragment_context(
    rr: RunsRoot,
    run_id: str,
) -> dict[str, Any] | None:
    """Build template context for ``_orchestrator.html`` (W5)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None
    run_dir = rr.find_run_dir(run_id)
    is_live = _is_run_live(run_dir)
    with open_ledger(ledger_path) as lc:
        waves = list_waves(lc, run_id)
        wave_to_node = {w.wave_id: w.node_id for w in waves}
    orch = build_orchestrator_view(
        run_dir,
        run_id=run_id,
        wave_to_node=wave_to_node,
        is_live=is_live,
        api_token=_get_token(),
    )
    return {"orch": orch, "run_id": run_id}


def _build_batch_timeline_context(rr: RunsRoot, run_id: str) -> dict[str, Any] | None:
    """Build template context for ``_batch_timeline.html`` (W4.1)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None
    run_dir = rr.find_run_dir(run_id)
    with open_ledger(ledger_path) as lc:
        waves = list_waves(lc, run_id)
        latest = latest_events_by_node(lc, run_id)
        batch_timeline = build_batch_timeline(
            run_dir,
            latest=latest,
            ledger_node_ids=[w.node_id for w in waves],
        )
    return {"batch_timeline": batch_timeline}


def _attempt_panel_context(
    lc: LedgerConnection,
    run_id: str,
    node_id: str,
    phase: str,
    attempt_count: int,
) -> dict[str, Any]:
    """Build attempt-history context for one wave row (W3.1)."""
    attempts = list_attempts(lc, run_id, node_id)
    attempt_rows = _attempt_display_rows(attempts)
    current_attempt_n = max((a.attempt_n for a in attempts), default=0) or max(attempt_count, 0)
    starting_new_attempt = (
        phase == "dispatched"
        and len(attempts) >= 2
        and attempts[-1].outcome is None
        and attempts[-2].outcome in ("failed", "timed_out", "scope_breach", "quota_exhausted")
    )
    return {
        "attempts": attempts,
        "attempt_rows": attempt_rows,
        "current_attempt_n": current_attempt_n,
        "starting_new_attempt": starting_new_attempt,
    }


def _infer_wave_tasks(
    rr: RunsRoot,
    run_id: str,
    wave: WaveRow,
    last_action: str,
    phase: str,
) -> WaveTaskResult | None:
    """Infer wave-task checklist for one wave when a staged plan slice exists (D6)."""
    plan_text = load_wave_plan_text_for_node(
        rr,
        run_id,
        wave_id=wave.wave_id,
        lane=wave.lane,
        plan_id=wave.plan_id,
    )
    if not plan_text:
        return None
    return infer_active_task(
        plan_text,
        last_action=last_action or None,
        phase=phase,
    )


def _get_wave_row(lc: LedgerConnection, run_id: str, node_id: str) -> WaveRow | None:
    """Return the ledger wave row for *node_id*, or ``None`` when missing."""
    for w in list_waves(lc, run_id):
        if w.node_id == node_id:
            return w
    return None


def _build_worktree_fragment_context(
    rr: RunsRoot,
    run_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Build template context for ``_worktree_panel.html`` (W3.4)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None

    run_dir = rr.find_run_dir(run_id)
    escalation_reasons = parse_escalation_reasons(run_dir)

    with open_ledger(ledger_path) as lc:
        wave = _get_wave_row(lc, run_id, node_id)
        if wave is None:
            return {
                "status": None,
                "worktree_error": f"Unknown wave node: {node_id}",
                "status_detail": None,
            }
        latest = latest_events_by_node(lc, run_id).get(node_id)
        phase = latest.phase if latest is not None else wave.state
        last_action = latest.last_action if latest and latest.last_action else ""
        attempts = list_attempts(lc, run_id, node_id)
        status_detail = _wave_status_detail(
            node_id=node_id,
            wave_id=wave.wave_id,
            phase=phase,
            last_action=last_action,
            attempts=attempts,
            escalation_reasons=escalation_reasons,
        )
        wt_path = resolve_wave_worktree_path(
            rr,
            run_id,
            lane=wave.lane,
            wave_id=wave.wave_id,
            plan_id=wave.plan_id,
        )

    if wt_path is None:
        return {"status": None, "worktree_error": None, "status_detail": status_detail}

    try:
        status = collect_worktree_status(wt_path)
    except WorktreeStatusError as exc:
        return {"status": None, "worktree_error": str(exc), "status_detail": status_detail}

    return {"status": status, "worktree_error": None, "status_detail": status_detail}


def _build_tasks_fragment_context(
    rr: RunsRoot,
    run_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Build template context for ``_wave_tasks.html`` (W3.3)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None

    run_dir = rr.find_run_dir(run_id)
    escalation_reasons = parse_escalation_reasons(run_dir)

    with open_ledger(ledger_path) as lc:
        wave = _get_wave_row(lc, run_id, node_id)
        if wave is None:
            return {"task_result": None, "status_detail": None}
        latest = latest_events_by_node(lc, run_id).get(node_id)
        phase = latest.phase if latest is not None else wave.state
        last_action = latest.last_action if latest and latest.last_action else ""
        attempts = list_attempts(lc, run_id, node_id)
        status_detail = _wave_status_detail(
            node_id=node_id,
            wave_id=wave.wave_id,
            phase=phase,
            last_action=last_action,
            attempts=attempts,
            escalation_reasons=escalation_reasons,
        )
        task_result = _infer_wave_tasks(rr, run_id, wave, last_action, phase)

    return {"task_result": task_result, "status_detail": status_detail}
