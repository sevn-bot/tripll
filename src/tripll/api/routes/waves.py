"""tripll.api.routes.waves — wave listing, detail, log, and worktree routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from tripll.api._artefacts import LogPathError, resolve_attempt_log_path, tail_log_file
from tripll.api._auth import require_auth
from tripll.api._runs import _find_ledger
from tripll.api._worktree_status import WorktreeStatusError
from tripll.api.models import WaveOut
from tripll.ledger import get_wave, list_attempts, list_waves, open_ledger
from tripll.pipeline import RunsRoot  # noqa: TC001

router = APIRouter()


@router.get("/api/runs/{run_id}/waves", response_model=list[WaveOut], tags=["waves"])
async def list_run_waves(
    run_id: str,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
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


@router.get("/api/waves/{run_id}/{node_id:path}", response_model=WaveOut, tags=["waves"])
async def get_wave_detail(
    run_id: str,
    node_id: str,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
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


@router.get("/api/runs/{run_id}/waves/{node_id:path}/log", tags=["waves"])
async def get_wave_log(
    run_id: str,
    node_id: str,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
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


@router.get("/api/runs/{run_id}/waves/{node_id:path}/worktree", tags=["waves"])
async def get_wave_worktree(
    run_id: str,
    node_id: str,
    request: Request,
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
    rr: RunsRoot = request.app.state.runs_root
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    import tripll.api.app as api_app

    with open_ledger(ledger_path) as lc:
        try:
            wave = get_wave(lc, run_id, node_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Wave not found: run={run_id} node={node_id}",
            ) from exc

    wt_path = api_app.resolve_wave_worktree_path(rr, run_id, lane=wave.lane, wave_id=wave.wave_id)
    if wt_path is None:
        raise HTTPException(status_code=404, detail=f"Worktree not found for node {node_id}")

    try:
        status = api_app.collect_worktree_status(wt_path)
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
