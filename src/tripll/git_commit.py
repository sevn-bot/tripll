"""tripll.git_commit — commit-per-wave git helpers (orchestrator mode W2.5).

Runs ``git add``, ``make commit-msg-check``, ``commit``, and ``push`` from the
integration worktree after verify passes. Fails closed when push fails (D7).

Exports:
    head_sha — current HEAD commit in a worktree.
    commit_msg_check — validate a subject via repo-root ``make commit-msg-check``.
    commit_and_push_wave — stage, validate, commit, and push on *branch*.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _run(
    argv: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env or os.environ.copy(),
    )


def head_sha(worktree_path: Path) -> str | None:
    """Return the current HEAD SHA in *worktree_path*, or ``None`` when unknown."""
    git = shutil.which("git") or "git"
    proc = _run([git, "rev-parse", "HEAD"], cwd=worktree_path)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def commit_msg_check(repo_root: Path, message: str) -> tuple[bool, str]:
    """Validate *message* with ``make commit-msg-check`` from *repo_root*."""
    make = shutil.which("make") or "make"
    proc = _run([make, "commit-msg-check", f"MSG={message}"], cwd=repo_root)
    if proc.returncode == 0:
        return True, "commit-msg-check ok"
    detail = (proc.stderr or proc.stdout or "commit-msg-check failed").strip()
    return False, detail


def commit_and_push_wave(
    worktree_path: Path,
    repo_root: Path,
    *,
    message: str,
    branch: str,
    author_name: str = "tripll",
    author_email: str = "tripll@local",
) -> tuple[bool, str]:
    """Stage all changes, validate subject, commit, and push *branch*."""
    git = shutil.which("git") or "git"
    status = _run([git, "status", "--porcelain"], cwd=worktree_path)
    if status.returncode != 0:
        return False, f"git status failed: {status.stderr.strip()}"
    if not status.stdout.strip():
        sha = head_sha(worktree_path)
        if sha is None:
            return False, "no changes and HEAD unknown"
        push_ok, push_err = _push_branch(worktree_path, git, branch)
        if not push_ok:
            return False, push_err
        return True, sha

    ok, ev = commit_msg_check(repo_root, message)
    if not ok:
        return False, ev

    add = _run([git, "add", "-A"], cwd=worktree_path)
    if add.returncode != 0:
        return False, f"git add failed: {add.stderr.strip()}"

    commit = _run(
        [
            git,
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            message,
        ],
        cwd=worktree_path,
    )
    if commit.returncode != 0:
        return False, f"git commit failed: {commit.stderr.strip()}"

    sha = head_sha(worktree_path)
    if sha is None:
        return False, "commit succeeded but HEAD unknown"

    push_ok, push_err = _push_branch(worktree_path, git, branch)
    if not push_ok:
        return False, push_err
    return True, sha


def _push_branch(worktree_path: Path, git: str, branch: str) -> tuple[bool, str]:
    proc = _run([git, "push", "-u", "origin", branch], cwd=worktree_path)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git push failed").strip()
        return False, f"git push failed: {detail}"
    return True, "pushed"
