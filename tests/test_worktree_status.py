"""Tests for tripll.api._worktree_status — worktree poll schema (D5 / W0.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tripll.api._worktree_status import (
    WORKTREE_POLL_INTERVAL_S,
    WorktreeStatus,
    collect_worktree_status,
    should_poll_worktree,
)


def test_poll_interval_is_five_seconds() -> None:
    assert WORKTREE_POLL_INTERVAL_S == 5


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("running", True),
        ("verifying", True),
        ("done", False),
        ("failed", False),
        ("blocked", False),
        ("dispatched", False),
        ("queued", False),
    ],
)
def test_should_poll_worktree(phase: str, expected: bool) -> None:
    assert should_poll_worktree(phase) is expected


def test_collect_worktree_status_from_git_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sample = repo / "hello.txt"
    sample.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sample.write_text("v2\n", encoding="utf-8")

    status = collect_worktree_status(repo)
    assert isinstance(status, WorktreeStatus)
    assert status.branch == "main" or status.branch == "master"
    assert status.changed_count == 1
    assert status.changed_paths == ["hello.txt"]
    assert len(status.head_sha) == 40
    assert any("hello.txt" in ln for ln in status.diff_stat_lines)
