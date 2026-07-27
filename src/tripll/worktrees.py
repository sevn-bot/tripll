"""tripll.worktrees — per-lane git worktree allocation + scope-breach guard.

Allocates a throwaway git worktree per lane-wave under
``runs/<run-id>/worktrees/<lane>-<wave>`` on a branch ``wave/<run-id>/<lane>-<wave>``
(D5), cleans it up, and detects/reverts edits that touch forbidden paths (D9).

The git invocation pattern mirrors ``sevn.evolution.worktree._git`` (fixed
argv, no shell, captured output).

Exports:
    WorktreeError — raised on git failures.
    Worktree — handle to an allocated worktree (path + branch + lane/wave).
    branch_name — derive the per-lane-wave branch name.
    allocate_worktree — ``git worktree add`` on a fresh per-lane branch.
    allocate_feature_branch_worktree — single integration branch worktree (D8).
    cleanup_worktree — ``git worktree remove`` (force).
    cleanup_run_worktrees — remove all worktrees under a run directory.
    stage_dispatch_context — copy run-dir plan context into a worktree.
    checkpoint_message — deterministic commit subject for an attempt.
    checkpoint_worktree — commit all changes in a worktree (no-op when clean).
    recover_worktree — commit orphaned work with a recovery subject.
    changed_paths — list working-tree + staged changed paths in a worktree.
    detect_scope_breach — changed paths that fall under forbidden paths.
    revert_breach — restore breached files to HEAD and unstage them.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


class WorktreeError(RuntimeError):
    """Raised when a git worktree operation fails."""


@dataclass(frozen=True, slots=True)
class Worktree:
    """Handle to an allocated git worktree.

    Args:
        path (Path): Worktree checkout root.
        branch (str): Branch name checked out in the worktree.
        lane_id (str): Owning lane id.
        wave_id (str): Wave id this worktree serves.
    """

    path: Path
    branch: str
    lane_id: str
    wave_id: str


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git subprocess in *cwd* with captured text output.

    Args:
        cwd (Path): Repository or worktree root.
        args (str): Git subcommand and arguments (variadic).

    Returns:
        subprocess.CompletedProcess[str]: Completed process.

    Examples:
        >>> _git.__name__
        '_git'
    """
    git_bin = shutil.which("git") or "git"
    return subprocess.run(
        [git_bin, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _slug(value: str) -> str:
    """Return a branch-safe slug for *value*.

    Args:
        value (str): Raw lane or wave label.

    Returns:
        str: Lowercase ``[a-z0-9-]`` slug.

    Examples:
        >>> _slug("W0->Final")
        'w0-final'
    """
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _branch_exists(repo_root: Path, branch: str) -> bool:
    """Return True when *branch* exists as a local ref in *repo_root*."""
    return _git(repo_root, "show-ref", "--verify", f"refs/heads/{branch}").returncode == 0


def _is_git_worktree(path: Path) -> bool:
    """Return True when *path* is a linked git worktree checkout."""
    return (path / ".git").is_file()


def _worktree_head_branch(worktree_path: Path) -> str | None:
    """Return the checked-out branch name, or None when *worktree_path* is invalid."""
    proc = _git(worktree_path, "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def branch_name(run_id: str, lane_id: str, wave_id: str) -> str:
    """Return the per-lane-wave branch name ``wave/<run-id>/<lane>-<wave>``.

    Args:
        run_id (str): Run identifier.
        lane_id (str): Lane id.
        wave_id (str): Wave id.

    Returns:
        str: Branch name.

    Examples:
        >>> branch_name("dev-eval-20260615", "telemetry", "W1")
        'wave/dev-eval-20260615/telemetry-w1'
    """
    return f"wave/{run_id}/{_slug(lane_id)}-{_slug(wave_id)}"


def allocate_worktree(
    repo_root: Path,
    worktrees_dir: Path,
    *,
    run_id: str,
    lane_id: str,
    wave_id: str,
    base_ref: str = "HEAD",
) -> Worktree:
    """Allocate a git worktree on a per-lane-wave branch.

    Creates a new branch with ``git worktree add -b`` when none exists; otherwise
    attaches an existing branch (resume after interrupted cleanup) or reuses an
    already-registered worktree at *path*.

    Args:
        repo_root (Path): The target repository git checkout.
        worktrees_dir (Path): Directory under which the worktree is created.
        run_id (str): Run identifier (for the branch name).
        lane_id (str): Lane id.
        wave_id (str): Wave id.
        base_ref (str): Git ref to branch from.

    Returns:
        Worktree: Handle to the allocated worktree.

    Raises:
        WorktreeError: If ``git worktree add`` fails.

    Examples:
        >>> callable(allocate_worktree)
        True
    """
    branch = branch_name(run_id, lane_id, wave_id)
    path = worktrees_dir / f"{_slug(lane_id)}-{_slug(wave_id)}"
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    if path.exists() and _is_git_worktree(path):
        head = _worktree_head_branch(path)
        if head == branch:
            return Worktree(path=path, branch=branch, lane_id=lane_id, wave_id=wave_id)
        msg = f"worktree {path} is on {head!r}, expected {branch!r}"
        raise WorktreeError(msg)

    if path.exists() and not _is_git_worktree(path):
        shutil.rmtree(path)

    if _branch_exists(repo_root, branch):
        proc = _git(repo_root, "worktree", "add", str(path), branch)
    else:
        proc = _git(repo_root, "worktree", "add", "-b", branch, str(path), base_ref)
    if proc.returncode != 0:
        raise WorktreeError(f"git worktree add failed: {proc.stderr.strip()}")
    return Worktree(path=path, branch=branch, lane_id=lane_id, wave_id=wave_id)


def allocate_feature_branch_worktree(
    repo_root: Path,
    worktree_path: Path,
    *,
    branch: str,
    base_ref: str = "HEAD",
) -> Worktree:
    """Allocate one integration worktree on *branch* (orchestrator single-branch D8)."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists() and _is_git_worktree(worktree_path):
        head = _worktree_head_branch(worktree_path)
        if head == branch:
            return Worktree(
                path=worktree_path,
                branch=branch,
                lane_id="integration",
                wave_id="all",
            )
        msg = f"worktree {worktree_path} is on {head!r}, expected {branch!r}"
        raise WorktreeError(msg)

    if worktree_path.exists() and not _is_git_worktree(worktree_path):
        shutil.rmtree(worktree_path)

    if _branch_exists(repo_root, branch):
        proc = _git(repo_root, "worktree", "add", str(worktree_path), branch)
    else:
        proc = _git(repo_root, "worktree", "add", "-b", branch, str(worktree_path), base_ref)
    if proc.returncode != 0:
        raise WorktreeError(f"git worktree add failed: {proc.stderr.strip()}")
    return Worktree(
        path=worktree_path,
        branch=branch,
        lane_id="integration",
        wave_id="all",
    )


def _extract_wave_section(plan_text: str, wave_id: str) -> str:
    """Return markdown for ``## Wave <wave_id>`` through the next wave heading."""
    pattern = rf"(?ms)^## Wave {re.escape(wave_id)}\b.*?(?=^## Wave |\Z)"
    match = re.search(pattern, plan_text)
    if match:
        return match.group(0).strip() + "\n"
    return f"## Wave {wave_id}\n\n(Wave section not found in plan file.)\n"


def _extract_execution_graph(plan_text: str) -> str:
    """Return the execution graph table block (small scheduling context)."""
    from tripll.parse.plan_files import _slice_section
    from tripll.parse.wave_plan_v1 import EXEC_GRAPH_HEADING

    section = _slice_section(plan_text, EXEC_GRAPH_HEADING)
    if not section:
        return ""
    return f"## {EXEC_GRAPH_HEADING}\n\n{section.strip()}\n"


def stage_dispatch_context(
    run_dir: Path,
    worktree_path: Path,
    plan_file: str,
    *,
    wave_id: str,
) -> Path:
    """Stage narrow plan context for one wave under ``plan/tripll/``.

    Copies only the current wave's plan slice, a compact execution-graph
    excerpt, and ``pre0-decisions.md`` when present. Does **not** copy every
    ``*-wave-plan.md`` in the run directory.

    Args:
        run_dir (Path): Run directory (outside the worktree).
        worktree_path (Path): Worktree checkout root.
        plan_file (str): Primary plan filename for this node.
        wave_id (str): Wave label (e.g. ``W0``, ``R1``).

    Returns:
        Path: Staged directory ``<worktree>/plan/tripll/``.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     run = Path(d) / "run"
        ...     wt = Path(d) / "wt"
        ...     run.mkdir()
        ...     wt.mkdir()
        ...     (run / "demo-wave-plan.md").write_text("## Wave W0\\n\\nDo W0.\\n")
        ...     dest = stage_dispatch_context(run, wt, "demo-wave-plan.md", wave_id="W0")
        ...     any(dest.glob("*-wave-W0.md"))
        True
    """
    dest = worktree_path / "plan" / "tripll"
    dest.mkdir(parents=True, exist_ok=True)
    plan_name = Path(plan_file).name
    plan_src = run_dir / plan_name
    plan_stem = Path(plan_name).stem
    slice_name = f"{plan_stem}-wave-{wave_id}.md"

    if plan_src.is_file():
        from tripll.plan_paths import normalize_plan_refs

        plan_text = plan_src.read_text(encoding="utf-8")
        graph_excerpt = _extract_execution_graph(plan_text)
        wave_body = _extract_wave_section(plan_text, wave_id)
        repo_root = worktree_path.resolve()
        wave_body, _ = normalize_plan_refs(wave_body, repo_root)
        if graph_excerpt:
            graph_excerpt, _ = normalize_plan_refs(graph_excerpt, repo_root)
        header = f"# {plan_stem} — wave {wave_id} (staged slice)\n\n"
        (dest / slice_name).write_text(header + wave_body, encoding="utf-8")
        if graph_excerpt:
            (dest / "execution-graph.md").write_text(graph_excerpt, encoding="utf-8")
    for name in ("pre0-decisions.md",):
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, dest / name)
    readme = (
        f"# tripll staged context — {wave_id}\n\n"
        f"- Wave slice: `{slice_name}`\n"
        f"- Execution graph: `execution-graph.md` (when present)\n"
        f"- Pre-0 decisions: `pre0-decisions.md` (when present)\n"
    )
    (dest / "README.md").write_text(readme, encoding="utf-8")
    return dest


def staged_wave_plan_path(worktree_path: Path, plan_file: str, wave_id: str) -> Path:
    """Return the staged plan slice path for *wave_id* in *worktree_path*."""
    plan_stem = Path(plan_file).stem
    return worktree_path / "plan" / "tripll" / f"{plan_stem}-wave-{wave_id}.md"


def checkpoint_message(*, run_id: str, node_id: str, attempt: int) -> str:
    """Return a deterministic commit subject for an attempt checkpoint.

    Args:
        run_id (str): Run identifier.
        node_id (str): Wave node id.
        attempt (int): 1-based attempt number.

    Returns:
        str: Commit subject (stable across reruns).

    Examples:
        >>> checkpoint_message(run_id="r1", node_id="plan:W0", attempt=2)
        'tripll: r1 plan:W0 attempt-2'
    """
    return f"tripll: {run_id} {node_id} attempt-{attempt}"


def checkpoint_worktree(
    worktree_path: Path,
    *,
    message: str,
    author_name: str = "tripll",
    author_email: str = "tripll@local",
) -> str | None:
    """Commit all tracked and untracked changes in *worktree_path*.

    Args:
        worktree_path (Path): Worktree checkout root.
        message (str): Commit subject.
        author_name (str): Git author name for the checkpoint commit.
        author_email (str): Git author email for the checkpoint commit.

    Returns:
        str | None: Commit SHA when a commit was created, else ``None`` when clean.

    Raises:
        WorktreeError: If ``git commit`` fails with staged changes.

    Examples:
        >>> callable(checkpoint_worktree)
        True
    """
    status = _git(worktree_path, "status", "--porcelain")
    if status.returncode != 0:
        raise WorktreeError(f"git status failed: {status.stderr.strip()}")
    if not status.stdout.strip():
        return None
    add = _git(worktree_path, "add", "-A")
    if add.returncode != 0:
        raise WorktreeError(f"git add failed: {add.stderr.strip()}")
    commit = _git(
        worktree_path,
        "-c",
        f"user.name={author_name}",
        "-c",
        f"user.email={author_email}",
        "commit",
        "--no-verify",
        "-m",
        message,
    )
    if commit.returncode != 0:
        raise WorktreeError(f"git commit failed: {commit.stderr.strip()}")
    sha = _git(worktree_path, "rev-parse", "HEAD")
    if sha.returncode != 0:
        raise WorktreeError(f"git rev-parse failed: {sha.stderr.strip()}")
    return sha.stdout.strip()


def recover_worktree(
    worktree_path: Path,
    *,
    run_id: str,
    node_id: str,
) -> str | None:
    """Commit any orphaned work in *worktree_path* after a crash or failed checkpoint.

    Uses ``--no-verify`` so pre-commit hooks cannot block saving agent work; verify
    targets enforce quality separately.

    Args:
        worktree_path (Path): Worktree checkout root.
        run_id (str): Run identifier.
        node_id (str): Wave node id.

    Returns:
        str | None: Commit SHA when a commit was created, else ``None`` when clean.
    """
    msg = f"tripll: {run_id} {node_id} recovery"
    return checkpoint_worktree(worktree_path, message=msg)


def cleanup_worktree(repo_root: Path, worktree: Worktree, *, force: bool = True) -> None:
    """Remove an allocated worktree via ``git worktree remove``.

    Args:
        repo_root (Path): The target repository git checkout.
        worktree (Worktree): The worktree to remove.
        force (bool): Pass ``--force`` (default True).

    Raises:
        WorktreeError: If ``git worktree remove`` fails.

    Examples:
        >>> callable(cleanup_worktree)
        True
    """
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree.path))
    proc = _git(repo_root, *args)
    if proc.returncode != 0:
        raise WorktreeError(f"git worktree remove failed: {proc.stderr.strip()}")


def cleanup_run_worktrees(repo_root: Path, run_dir: Path) -> None:
    """Remove git worktrees registered under ``run_dir/worktrees/``.

    Best-effort: logs warnings and continues when individual removes fail so
    ``reset-run`` / ``delete-run`` can still drop the run directory.
    """
    worktrees_dir = run_dir / "worktrees"
    if not worktrees_dir.is_dir():
        return
    for child in sorted(worktrees_dir.iterdir()):
        if not child.is_dir() or not _is_git_worktree(child):
            continue
        wt = Worktree(path=child, branch="", lane_id="", wave_id="")
        try:
            cleanup_worktree(repo_root, wt, force=True)
        except WorktreeError as exc:
            logger.warning("pipeline: worktree cleanup {}: {}", child.name, exc)
            if child.exists():
                shutil.rmtree(child, ignore_errors=True)


def changed_paths(worktree_path: Path) -> list[str]:
    """Return working-tree + staged changed paths in *worktree_path*.

    Uses ``git status --porcelain`` so both staged and unstaged edits, plus
    untracked files, are reported.

    Args:
        worktree_path (Path): Worktree checkout root.

    Returns:
        list[str]: Repo-relative changed paths (sorted, de-duplicated).

    Examples:
        >>> callable(changed_paths)
        True
    """
    proc = _git(worktree_path, "status", "--porcelain")
    if proc.returncode != 0:
        raise WorktreeError(f"git status failed: {proc.stderr.strip()}")
    paths: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        entry = line[3:] if len(line) > 3 else line.strip()
        # Renames are reported as "old -> new"; record the destination.
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.add(entry.strip())
    return sorted(paths)


def _forbidden_prefix(forbidden: str) -> str:
    """Normalise a forbidden-path entry to a comparable prefix.

    Strips any ``" (…)"`` annotation (e.g. ``"Makefile (ci: line)"``) and a
    trailing slash.

    Args:
        forbidden (str): Forbidden-path entry from a node.

    Returns:
        str: Comparable path prefix.

    Examples:
        >>> _forbidden_prefix("Makefile (ci: line)")
        'Makefile'
        >>> _forbidden_prefix("src/sevn/a/")
        'src/sevn/a'
    """
    return re.sub(r"\s*\(.*\)\s*$", "", forbidden).rstrip("/").strip()


def path_matches_owned(changed: str, owned_paths: list[str]) -> bool:
    """Return True when *changed* falls under an explicit owned path pattern."""
    c = changed.rstrip("/")
    for pattern in owned_paths:
        p = pattern.rstrip("/")
        if fnmatch.fnmatch(c, p) or fnmatch.fnmatch(c, p + "/*"):
            return True
        if p.startswith("/") and p.endswith("/*"):
            root = p[1:-2]
            if c == root or c.startswith(root + "/"):
                return True
        if "*" not in p and (c == p or c.startswith(p + "/")):
            return True
    return False


def detect_scope_breach(
    worktree_path: Path,
    forbidden_paths: list[str],
    *,
    owned_paths: list[str] | None = None,
) -> list[str]:
    """Return changed paths that fall under any forbidden path (D9).

    Args:
        worktree_path (Path): Worktree checkout root.
        forbidden_paths (list[str]): Paths the wave must not edit.

    Returns:
        list[str]: Breached changed paths (sorted).

    Examples:
        >>> callable(detect_scope_breach)
        True
    """
    prefixes = [_forbidden_prefix(f) for f in forbidden_paths if _forbidden_prefix(f)]
    breached: list[str] = []
    for changed in changed_paths(worktree_path):
        if owned_paths and path_matches_owned(changed, owned_paths):
            continue
        c = changed.rstrip("/")
        for pre in prefixes:
            if c == pre or c.startswith(pre + "/"):
                breached.append(changed)
                break
    return sorted(breached)


def revert_breach(worktree_path: Path, files: list[str]) -> None:
    """Restore breached *files* to HEAD and unstage them.

    Args:
        worktree_path (Path): Worktree checkout root.
        files (list[str]): Breached paths to revert.

    Examples:
        >>> callable(revert_breach)
        True
    """
    for f in files:
        _git(worktree_path, "reset", "--quiet", "HEAD", "--", f)
        _git(worktree_path, "checkout", "--quiet", "--", f)
        # Drop untracked files that have no HEAD version.
        target = worktree_path / f
        if target.exists():
            status = _git(worktree_path, "status", "--porcelain", "--", f)
            if status.stdout.startswith("??"):
                target.unlink()
