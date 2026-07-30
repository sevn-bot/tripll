"""tripll.api.deps — shared helpers for API route handlers."""

from __future__ import annotations

import os
import sys
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from fastapi import HTTPException
from loguru import logger

from tripll.api._worktree_status import load_staged_wave_plan_text, resolve_wave_worktree_path
from tripll.api.models import ConfigOut, EventOut
from tripll.ledger import EventRow, get_wave
from tripll.pipeline import RunsRoot, resolve_runs_root
from tripll.wave_task import infer_active_task

if TYPE_CHECKING:
    from tripll.ledger import LedgerConnection


def _resolve_runs_root(runs_root: Path | None) -> RunsRoot:
    """Resolve the runs root from an explicit path or env/default.

    Delegates to :func:`~tripll.pipeline.resolve_runs_root` so CLI and API share
    the same repo-anchored default (``.tripll/runs`` for target repos,
    ``runs/`` for the tripll dev checkout).

    Args:
        runs_root (Path | None): Explicit override, or ``None`` to use default.

    Returns:
        RunsRoot: Configured runs root instance.
    """
    return resolve_runs_root(runs_root)


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
    import tripll.api.app as api_app

    api_app.subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=api_app.subprocess.DEVNULL,
        stderr=api_app.subprocess.DEVNULL,
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
