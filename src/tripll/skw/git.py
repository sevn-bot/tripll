"""Deterministic per-wave git commit + push node (Wave W2, D9).

``commit_wave`` runs after an agent state **and** verify pass: stage tracked
changes, commit with Conventional subject, push to plan ``branch`` on
``[git].remote``. Gated by ``skw.toml [git]``; no-op when disabled or empty
diff; never switches branches.

Exports:
    commit_wave — stage, commit, and optionally push wave changes.
    resolve_worktree — locate the worktree that has *branch* checked out.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tripll.skw.runtime import is_dryrun
from tripll.skw.tracing import span

__all__: list[str] = ["commit_wave", "resolve_worktree"]


def _git_run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _print_argv(cmd: list[str]) -> None:
    print(" ".join(cmd))


def resolve_worktree(branch: str, hint: Path) -> Path:
    """Return the worktree path where *branch* is checked out.

    Args:
        branch (str): Git branch name (e.g. ``feature/my-plan``).
        hint (Path): Fallback directory when parsing fails (typically repo root).

    Returns:
        Path: Worktree root for *branch*, or *hint* when not found.

    Examples:
        >>> resolve_worktree("main", Path("."))  # doctest: +SKIP
        PosixPath('.')
    """
    result = _git_run(["git", "worktree", "list", "--porcelain"], cwd=hint)
    if result.returncode != 0:
        return hint

    target = f"refs/heads/{branch}"
    current_path: Path | None = None
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("worktree "):
            current_path = Path(line.removeprefix("worktree ").strip())
            continue
        if line.startswith("branch ") and current_path is not None:
            ref = line.removeprefix("branch ").strip()
            if ref == target:
                return current_path
    return hint


def _commit_subject(slug: str, wave_id: str, title: str, role: str) -> str:
    prefix = "test" if role == "test-author" else "feat"
    return f"{prefix}({slug}): {wave_id} — {title}"


def commit_wave(
    *,
    wave_id: str,
    title: str,
    slug: str,
    role: str,
    branch: str,
    worktree: Path,
    git_config: dict[str, Any],
) -> None:
    """Stage, commit, and optionally push tracked changes for one wave.

    Args:
        wave_id (str): Wave identifier (e.g. ``W2``).
        title (str): Wave title for the commit subject.
        slug (str): Plan slug for Conventional Commit scope.
        role (str): Wave role (``impl`` or ``test-author``).
        branch (str): Target branch name; used to resolve worktree.
        worktree (Path): Hint path for worktree resolution.
        git_config (dict[str, Any]): Full ``skw.toml`` config (includes ``git`` key).

    Examples:
        >>> commit_wave(  # doctest: +SKIP
        ...     wave_id="W1",
        ...     title="Tests",
        ...     slug="demo",
        ...     role="test-author",
        ...     branch="feature/demo",
        ...     worktree=Path("."),
        ...     git_config={"git": {"commit_per_wave": False}},
        ... )
    """
    git_section = git_config.get("git", {})
    if not git_section.get("commit_per_wave", True):
        return

    with span(
        "git.commit_wave",
        wave_id=wave_id,
        role=role,
        branch=branch,
        slug=slug,
    ) as bag:
        dry = is_dryrun()
        wt = resolve_worktree(branch, worktree) if not dry else worktree

        remote = git_section.get("remote", "origin")
        subject = _commit_subject(slug, wave_id, title, role)
        bag["subject"] = subject

        add_cmd = ["git", "add", "-A"]
        commit_cmd = ["git", "commit", "-m", subject]
        push_cmd = ["git", "push", remote, branch]

        if dry:
            _print_argv(add_cmd)
            _print_argv(commit_cmd)
            if git_section.get("push_per_wave", True):
                _print_argv(push_cmd)
            bag["output"] = "dry-run git commands printed"
            return

        _git_run(add_cmd, cwd=wt)
        commit_result = _git_run(commit_cmd, cwd=wt)
        if commit_result.returncode != 0:
            stderr = commit_result.stderr.strip()
            if "nothing to commit" in stderr.lower():
                bag["output"] = "nothing to commit"
                return
            msg = f"git commit failed: {stderr or commit_result.stdout}"
            raise RuntimeError(msg)

        if git_section.get("push_per_wave", True):
            push_result = _git_run(push_cmd, cwd=wt)
            if push_result.returncode != 0:
                msg = f"git push failed: {push_result.stderr.strip()}"
                raise RuntimeError(msg)
        bag["output"] = subject
