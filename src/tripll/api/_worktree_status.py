"""tripll.api._worktree_status — git worktree status for dashboard poll (D5).

Read-only summary of a wave worktree: branch, changed paths, diff stat vs HEAD.
htmx polls every :data:`WORKTREE_POLL_INTERVAL_S` while the wave phase is
``running`` or ``verifying``; polling stops on terminal phases.

Exports:
    WORKTREE_POLL_INTERVAL_S — htmx poll interval in seconds.
    WorktreeStatus — JSON-serialisable response schema.
    should_poll_worktree — whether the UI should keep polling.
    resolve_wave_worktree_path — locate a wave checkout under a run directory.
    collect_worktree_status — build status from a worktree checkout path.
    WorktreeStatusError — raised when git inspection fails.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tripll.worktrees import WorktreeError, _slug, changed_paths

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.pipeline import RunsRoot

WORKTREE_POLL_INTERVAL_S = 5
_ACTIVE_POLL_PHASES = frozenset({"running", "verifying"})
_TERMINAL_POLL_PHASES = frozenset(
    {"done", "failed", "blocked", "deferred", "gate_pending", "queued", "dispatched", "paused"}
)


class WorktreeStatusError(RuntimeError):
    """Raised when worktree status cannot be collected."""


@dataclass(frozen=True, slots=True)
class WorktreeStatus:
    """Git worktree summary returned by ``GET /api/runs/{id}/waves/{node_id}/worktree``.

    Args:
        branch (str): Checked-out branch name (``git rev-parse --abbrev-ref HEAD``).
        changed_count (int): Number of changed paths (porcelain summary).
        changed_paths (list[str]): Repo-relative changed paths (sorted).
        diff_stat_lines (list[str]): Lines from ``git diff --stat HEAD``.
        head_sha (str): Full commit SHA at HEAD.
    """

    branch: str
    changed_count: int
    changed_paths: list[str]
    diff_stat_lines: list[str]
    head_sha: str


def should_poll_worktree(phase: str) -> bool:
    """Return True when the dashboard should poll worktree status (D5).

    Poll while ``phase`` ∈ ``{running, verifying}``; stop when the wave reaches
    any terminal or pre-dispatch phase.

    Args:
        phase (str): Current wave phase from the ledger.

    Returns:
        bool: True when htmx ``every 5s`` polling should remain active.

    Examples:
        >>> should_poll_worktree("running")
        True
        >>> should_poll_worktree("done")
        False
    """
    if phase in _ACTIVE_POLL_PHASES:
        return True
    if phase in _TERMINAL_POLL_PHASES:
        return False
    return False


def resolve_wave_worktree_path(
    rr: RunsRoot,
    run_id: str,
    *,
    lane: str,
    wave_id: str,
    plan_id: str | None = None,
) -> Path | None:
    """Return the git worktree checkout path for one wave node, if present.

    Worktrees live at ``<run-dir>/worktrees/<lane-slug>-<wave-slug>/`` (D5).
    The engine allocates using ``plan_id`` as the lane slug; orchestrator mode
    may use a shared ``worktrees/integration/`` checkout (D8).

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Parent run identifier.
        lane (str): Lane label from the ledger wave row.
        wave_id (str): Wave id from the ledger wave row.
        plan_id (str | None): Plan slug from the ledger (preferred match key).

    Returns:
        Path | None: Worktree root when the directory exists, else ``None``.

    Examples:
        >>> from pathlib import Path
        >>> from tripll.pipeline import RunsRoot
        >>> rr = RunsRoot(Path("/tmp/runs"))
        >>> resolve_wave_worktree_path(rr, "missing", lane="core", wave_id="W1") is None
        True
    """
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        return None
    worktrees_dir = run_dir / "worktrees"
    if not worktrees_dir.is_dir():
        return None

    prefixes: list[str] = []
    if plan_id:
        prefixes.append(_slug(plan_id))
    lane_slug = _slug(lane)
    if lane_slug and lane_slug not in prefixes:
        prefixes.append(lane_slug)

    wave_slug = _slug(wave_id)
    for prefix in prefixes:
        candidate = worktrees_dir / f"{prefix}-{wave_slug}"
        if candidate.is_dir():
            return candidate

    integration = worktrees_dir / "integration"
    if integration.is_dir():
        return integration

    for child in sorted(worktrees_dir.iterdir()):
        if child.is_dir() and (child.name == wave_slug or child.name.endswith(f"-{wave_slug}")):
            return child
    return None


def load_wave_plan_text_for_node(
    rr: RunsRoot,
    run_id: str,
    *,
    wave_id: str,
    lane: str,
    plan_id: str,
) -> str | None:
    """Load staged or run-dir plan slice text for one wave (D6 fallback).

    Prefers ``plan/tripll/*-wave-{wave_id}.md`` inside the resolved worktree;
    falls back to extracting the wave section from ``*-wave-plan.md`` in the run
    directory when no worktree exists yet (e.g. human-gate W0 before dispatch).
    """
    from tripll.worktrees import _extract_wave_section

    wt_path = resolve_wave_worktree_path(
        rr,
        run_id,
        lane=lane,
        wave_id=wave_id,
        plan_id=plan_id,
    )
    if wt_path is not None:
        staged = load_staged_wave_plan_text(wt_path, wave_id)
        if staged:
            return staged

    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        return None
    for plan_src in sorted(run_dir.glob("*-wave-plan.md")):
        body = _extract_wave_section(plan_src.read_text(encoding="utf-8"), wave_id)
        if body.strip():
            return body
    return None


def load_staged_wave_plan_text(worktree_path: Path, wave_id: str) -> str | None:
    """Read the staged plan slice for *wave_id* from a worktree checkout.

    Args:
        worktree_path (Path): Worktree root containing ``plan/tripll/``.
        wave_id (str): Wave label (e.g. ``W3``).

    Returns:
        str | None: Markdown slice text, or ``None`` when no staged file exists.
    """
    staged_dir = worktree_path / "plan" / "tripll"
    if not staged_dir.is_dir():
        return None
    matches = sorted(staged_dir.glob(f"*-wave-{wave_id}.md"))
    if not matches:
        return None
    return matches[0].read_text(encoding="utf-8")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    git_bin = shutil.which("git") or "git"
    return subprocess.run(
        [git_bin, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def collect_worktree_status(worktree_path: Path) -> WorktreeStatus:
    """Collect git status for one wave worktree checkout (D5).

    Args:
        worktree_path (Path): Worktree root (must exist).

    Returns:
        WorktreeStatus: Hydrated status payload.

    Raises:
        WorktreeStatusError: When *worktree_path* is missing or git fails.

    Examples:
        >>> callable(collect_worktree_status)
        True
    """
    if not worktree_path.is_dir():
        raise WorktreeStatusError(f"Worktree path not found: {worktree_path}")

    try:
        paths = changed_paths(worktree_path)
    except WorktreeError as exc:
        raise WorktreeStatusError(str(exc)) from exc

    branch_proc = _git(worktree_path, "rev-parse", "--abbrev-ref", "HEAD")
    if branch_proc.returncode != 0:
        raise WorktreeStatusError(branch_proc.stderr.strip() or "git rev-parse branch failed")
    branch = branch_proc.stdout.strip()

    head_proc = _git(worktree_path, "rev-parse", "HEAD")
    if head_proc.returncode != 0:
        raise WorktreeStatusError(head_proc.stderr.strip() or "git rev-parse HEAD failed")
    head_sha = head_proc.stdout.strip()

    diff_proc = _git(worktree_path, "diff", "--stat", "HEAD")
    diff_lines = [ln for ln in diff_proc.stdout.splitlines() if ln.strip()]

    return WorktreeStatus(
        branch=branch,
        changed_count=len(paths),
        changed_paths=paths,
        diff_stat_lines=diff_lines,
        head_sha=head_sha,
    )
