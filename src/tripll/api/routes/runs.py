"""tripll.api.routes.runs — run lifecycle, HITL, inject, reconcile, and PR routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from tripll.api._auth import require_auth
from tripll.api._inject import (
    inject_error_to_status,
    list_run_injects,
    parse_owned_paths,
    run_hotfix_inject,
    run_reconcile_graph,
)
from tripll.api._runs import RunDetail, RunSummary, _find_ledger, _is_run_live, _list_all_runs
from tripll.api.deps import (
    _assert_run_exists,
    _read_config,
    _read_pid,
    _spawn_tripll,
    _tripll_argv,
)
from tripll.api.models import HitlResponsesIn, InjectIn, InjectOut, ReconcileIn, ReconcileOut, RunIn
from tripll.inject import InjectError
from tripll.ledger import get_run, open_ledger
from tripll.pipeline import RunsRoot  # noqa: TC001
from tripll.profiles import control_plane_db_path, get_profile, open_profile_store

router = APIRouter()


@router.get("/api/runs", response_model=list[RunSummary], tags=["runs"])
async def list_runs(
    request: Request,
    _auth: None = Depends(require_auth),
) -> list[RunSummary]:
    """List all runs (processing, processed, failed).

    Returns:
        list[RunSummary]: Summary rows for all known runs.
    """
    rr: RunsRoot = request.app.state.runs_root
    return _list_all_runs(rr)


@router.post("/api/runs", response_model=RunDetail, status_code=202, tags=["runs"])
async def launch_run(
    data: RunIn,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
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
    import tripll.api.app as api_app

    proc = api_app.subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=api_app.subprocess.DEVNULL,
        stderr=api_app.subprocess.DEVNULL,
    )
    logger.info("api: spawned engine pid={}", proc.pid)

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


@router.get("/api/runs/{run_id}", response_model=RunDetail, tags=["runs"])
async def get_run_detail(
    run_id: str,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
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


@router.post("/api/runs/{run_id}/approve", status_code=202, tags=["runs"])
async def approve_run(
    run_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, str]:
    """Approve the Pre-0 gate for a run.

    Spawns ``tripll approve <run_id>`` as a detached subprocess.

    Args:
        run_id (str): Run identifier.

    Returns:
        dict[str, str]: Confirmation message.
    """
    rr: RunsRoot = request.app.state.runs_root
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


@router.get("/api/runs/{run_id}/hitl", tags=["runs"])
async def get_hitl(
    run_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, Any]:
    """Return HITL form, responses, and completion status for a run."""
    rr: RunsRoot = request.app.state.runs_root
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    from tripll import hitl

    return hitl.hitl_status(run_dir)


@router.put("/api/runs/{run_id}/hitl/responses", tags=["runs"])
async def put_hitl_responses(
    run_id: str,
    body: HitlResponsesIn,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, Any]:
    """Save draft or submitted HITL responses."""
    rr: RunsRoot = request.app.state.runs_root
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


@router.post("/api/runs/{run_id}/hitl/submit", tags=["runs"])
async def submit_hitl(
    run_id: str,
    body: HitlResponsesIn,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, Any]:
    """Validate responses and rewrite pre0-decisions.md."""
    rr: RunsRoot = request.app.state.runs_root
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


@router.post("/api/runs/{run_id}/hitl/approve", status_code=202, tags=["runs"])
async def approve_hitl(
    run_id: str,
    request: Request,
    body: HitlResponsesIn | None = None,
    _auth: None = Depends(require_auth),
) -> dict[str, str]:
    """Submit responses (if provided) and approve the pending HITL gate."""
    rr: RunsRoot = request.app.state.runs_root
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


@router.post("/api/runs/{run_id}/resume", status_code=202, tags=["runs"])
async def resume_run(
    run_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, str]:
    """Resume a paused or failed run.

    Spawns ``tripll resume <run_id>`` as a detached subprocess.

    Args:
        run_id (str): Run identifier.

    Returns:
        dict[str, str]: Confirmation message.
    """
    rr: RunsRoot = request.app.state.runs_root
    _assert_run_exists(rr, run_id)
    from tripll.run_dispatch import resume_cli_extra_argv

    run_dir = rr.find_run_dir(run_id)
    assert run_dir is not None
    extra = resume_cli_extra_argv(run_dir)
    _spawn_tripll(["resume", run_id, *extra, "--runs-root", str(rr.root)])
    return {"message": f"Resuming run {run_id}"}


@router.get("/api/runs/{run_id}/pr/status", tags=["pr"])
async def get_pr_status(
    run_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, Any]:
    """Return PR phase state and merge-gate markers for a run."""
    from tripll.loops.l1_pr import pr_status

    rr: RunsRoot = request.app.state.runs_root
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return pr_status(run_dir=run_dir)


@router.post("/api/runs/{run_id}/pr/shepherd", status_code=202, tags=["pr"])
async def pr_shepherd(
    run_id: str,
    request: Request,
    phase: str = "investigate_and_fix",
    _auth: None = Depends(require_auth),
) -> dict[str, str]:
    """Spawn ``tripll pr shepherd --run <id>`` for one PR loop step."""
    rr: RunsRoot = request.app.state.runs_root
    _assert_run_exists(rr, run_id)
    _spawn_tripll(
        ["pr", "shepherd", "--run", run_id, "--phase", phase, "--runs-root", str(rr.root)]
    )
    return {"message": f"PR shepherd started for {run_id}"}


@router.post("/api/runs/{run_id}/pr/approve-merge", status_code=202, tags=["pr"])
async def pr_approve_merge(
    run_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, Any]:
    """Approve the human merge gate — never auto-merges without this call."""
    from tripll.loops.l1_pr import approve_merge_gate, pr_status

    rr: RunsRoot = request.app.state.runs_root
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


@router.post("/api/runs/{run_id}/pause", status_code=202, tags=["runs"])
async def pause_run(
    run_id: str,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
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


@router.post("/api/runs/{run_id}/inject", response_model=InjectOut, status_code=202, tags=["runs"])
async def inject_run(
    run_id: str,
    data: InjectIn,
    request: Request,
    _auth: None = Depends(require_auth),
) -> InjectOut:
    """Apply a hotfix inject (same logic as ``tripll run inject``)."""
    rr: RunsRoot = request.app.state.runs_root
    if rr.find_run_dir(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    owned = parse_owned_paths(data.owned_paths)
    if not owned:
        raise HTTPException(status_code=400, detail="owned_paths must be non-empty")
    try:
        task = run_hotfix_inject(
            rr,
            run_id,
            brief=data.brief.strip(),
            owned_paths=owned,
            after=data.after.strip(),
            verify_target=data.verify_target,
            provider=data.provider,
            model=data.model,
            agent=data.agent,
            dry_run=data.dry_run,
            injected_by="api",
            cost_budget_usd=_read_config().cost_budget_usd,
            force_after_drain=data.force_after_drain,
        )
    except InjectError as exc:
        raise HTTPException(
            status_code=inject_error_to_status(exc),
            detail=str(exc),
        ) from exc
    msg = (
        f"Dry-run hotfix plan valid — node {task.node_id}"
        if data.dry_run
        else f"Inject applied: {task.node_id} (task {task.task_id})"
    )
    return InjectOut(
        task_id=task.task_id,
        node_id=task.node_id,
        run_id=run_id,
        dry_run=data.dry_run,
        message=msg,
    )


@router.get("/api/runs/{run_id}/injects", tags=["runs"])
async def get_run_injects(
    run_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> dict[str, object]:
    """List inject artefacts and related ledger events for a run."""
    rr: RunsRoot = request.app.state.runs_root
    if rr.find_run_dir(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return list_run_injects(rr, run_id)


@router.post(
    "/api/runs/{run_id}/reconcile-graph",
    response_model=ReconcileOut,
    status_code=202,
    tags=["runs"],
)
async def reconcile_run_graph_api(
    run_id: str,
    data: ReconcileIn,
    request: Request,
    _auth: None = Depends(require_auth),
) -> ReconcileOut:
    """Reconcile parsed plan files with ledger waves (same logic as CLI reconcile)."""
    rr: RunsRoot = request.app.state.runs_root
    if rr.find_run_dir(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    try:
        result = run_reconcile_graph(
            rr,
            run_id,
            dry_run=data.dry_run,
            force_after_drain=data.force_after_drain,
        )
    except InjectError as exc:
        raise HTTPException(
            status_code=inject_error_to_status(exc),
            detail=str(exc),
        ) from exc
    inserted = list(result.inserted)
    orphans = list(result.orphans)
    msg = (
        f"[dry-run] Reconcile valid — would insert {inserted} orphan {orphans}"
        if data.dry_run
        else f"Reconcile applied: inserted {inserted}"
    )
    return ReconcileOut(
        run_id=run_id,
        dry_run=data.dry_run,
        inserted=inserted,
        orphans=orphans,
        message=msg,
    )
