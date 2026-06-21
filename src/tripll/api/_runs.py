"""tripll.api._runs — run-listing helpers and response models (W4).

Shared helpers for reading run state from the ledger and the filesystem,
plus Pydantic response models used by the runs endpoints.

Exports:
    RunSummary — lightweight run list entry.
    RunDetail — full run detail including liveness.
    _find_ledger — locate the ledger.db for a run_id across all folders.
    _is_run_live — check whether the engine process for a run is still alive.
    _list_all_runs — build the full runs list from the runs root.
"""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003

from pydantic import BaseModel

from tripll.ledger import get_run, open_ledger
from tripll.pipeline import RunsRoot  # noqa: TC001


class RunSummary(BaseModel):
    """Lightweight run list entry.

    Args:
        run_id (str): Run identifier.
        slug (str): Sanitised slug.
        state (str): Run state (``active`` | ``done`` | ``failed`` | ``paused``).
        created_at (str): ISO-8601 UTC creation timestamp.
        updated_at (str): ISO-8601 UTC last-update timestamp.
        cost_usd (float): Cumulative cost in USD.
        is_live (bool): True if the engine process is currently running.
    """

    run_id: str
    slug: str
    state: str
    created_at: str
    updated_at: str
    cost_usd: float
    is_live: bool


class RunDetail(BaseModel):
    """Full run detail with liveness and engine PID.

    Args:
        run_id (str): Run identifier.
        slug (str): Sanitised slug.
        state (str): Run state.
        input_path (str): Original input directory path.
        created_at (str): ISO-8601 UTC creation timestamp.
        updated_at (str): ISO-8601 UTC last-update timestamp.
        cost_usd (float): Cumulative cost in USD.
        is_live (bool): True if the engine process is currently running.
        engine_pid (int | None): PID from ``engine.pid`` if present.
    """

    run_id: str
    slug: str
    state: str
    input_path: str
    created_at: str
    updated_at: str
    cost_usd: float
    is_live: bool
    engine_pid: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_ledger(rr: RunsRoot, run_id: str) -> Path | None:
    """Locate the ledger.db for *run_id* across all run folders.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier.

    Returns:
        Path | None: Path to ``ledger.db`` when found, else ``None``.
    """
    for folder in (rr.processing_dir, rr.processed_dir, rr.failed_dir):
        path = folder / run_id / "ledger.db"
        if path.exists():
            return path
    return None


def _is_run_live(run_dir: Path | None) -> bool:
    """Return True if the engine process recorded in ``engine.pid`` is alive.

    A run is "live" when:
    - ``engine.pid`` exists in the run directory, AND
    - The recorded PID corresponds to a running OS process.

    Args:
        run_dir (Path | None): Run directory (``None`` → not live).

    Returns:
        bool: True when the engine process is alive.
    """
    if run_dir is None:
        return False
    pid_file = run_dir / "engine.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)  # signal 0: checks existence without killing
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _list_all_runs(rr: RunsRoot) -> list[RunSummary]:
    """Build the full run list from all three pipeline folders.

    Args:
        rr (RunsRoot): Configured runs root.

    Returns:
        list[RunSummary]: Summary rows for all known runs, sorted by run_id.
    """
    results: list[RunSummary] = []
    for folder in (rr.processing_dir, rr.processed_dir, rr.failed_dir):
        if not folder.exists():
            continue
        for run_dir in sorted(folder.iterdir()):
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            ledger_path = run_dir / "ledger.db"
            if not ledger_path.exists():
                continue
            try:
                with open_ledger(ledger_path) as lc:
                    row = get_run(lc, run_id)
            except Exception:
                continue
            results.append(
                RunSummary(
                    run_id=row.run_id,
                    slug=row.slug,
                    state=row.state,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    cost_usd=row.cost_usd,
                    is_live=_is_run_live(run_dir),
                )
            )
    return results
