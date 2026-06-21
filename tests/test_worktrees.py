"""Tests for tripll.worktrees — allocation, scope-breach detection, revert."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.worktrees import (
    _git,
    allocate_worktree,
    branch_name,
    checkpoint_message,
    checkpoint_worktree,
    cleanup_worktree,
    detect_scope_breach,
    revert_breach,
    stage_dispatch_context,
)

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# temp\n")
    _git(root, "add", "README.md")
    _git(
        root,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=test",
        "commit",
        "-q",
        "-m",
        "init",
    )


def test_branch_name() -> None:
    assert branch_name("run-1", "telemetry", "W1") == "wave/run-1/telemetry-w1"


def test_checkpoint_message_deterministic() -> None:
    assert checkpoint_message(run_id="r1", node_id="plan:W0", attempt=2) == (
        "tripll: r1 plan:W0 attempt-2"
    )


def test_checkpoint_worktree_commits_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = allocate_worktree(repo, tmp_path / "wts", run_id="run-1", lane_id="lane", wave_id="W0")
    target = wt.path / "src" / "feature.py"
    target.parent.mkdir(parents=True)
    target.write_text("partial work\n")

    msg = checkpoint_message(run_id="run-1", node_id="lane:W0", attempt=1)
    sha = checkpoint_worktree(wt.path, message=msg)
    assert sha is not None
    assert len(sha) == 40

    show = _git(wt.path, "show", "--stat", "--format=%s", sha)
    assert show.returncode == 0
    assert msg in show.stdout
    assert "src/feature.py" in show.stdout

    # Clean tree after checkpoint.
    assert checkpoint_worktree(wt.path, message=msg) is None

    cleanup_worktree(repo, wt)


def test_recover_worktree_commits_staged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = allocate_worktree(
        repo, tmp_path / "wts", run_id="run-1", lane_id="telemetry", wave_id="W1"
    )
    target = wt.path / "src" / "marker.py"
    target.parent.mkdir(parents=True)
    target.write_text("saved\n")
    _git(wt.path, "add", "src/marker.py")

    from tripll.worktrees import recover_worktree

    sha = recover_worktree(wt.path, run_id="run-1", node_id="telemetry:W1")
    assert sha is not None
    log = _git(repo, "log", "--oneline", wt.branch)
    assert "recovery" in log.stdout

    cleanup_worktree(repo, wt)


def test_allocate_and_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = allocate_worktree(
        repo,
        tmp_path / "wts",
        run_id="run-1",
        lane_id="telemetry",
        wave_id="W1",
    )
    assert wt.path.exists()
    assert wt.branch == "wave/run-1/telemetry-w1"
    cleanup_worktree(repo, wt)
    assert not wt.path.exists()


def test_allocate_reuses_branch_after_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    kwargs = {
        "run_id": "run-1",
        "lane_id": "telemetry",
        "wave_id": "W1",
    }
    wt1 = allocate_worktree(repo, tmp_path / "wts", **kwargs)
    cleanup_worktree(repo, wt1)
    assert not wt1.path.exists()

    wt2 = allocate_worktree(repo, tmp_path / "wts", **kwargs)
    assert wt2.path.exists()
    assert wt2.branch == wt1.branch
    cleanup_worktree(repo, wt2)


def test_allocate_reuses_existing_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt1 = allocate_worktree(
        repo,
        tmp_path / "wts",
        run_id="run-1",
        lane_id="telemetry",
        wave_id="W1",
    )
    wt2 = allocate_worktree(
        repo,
        tmp_path / "wts",
        run_id="run-1",
        lane_id="telemetry",
        wave_id="W1",
    )
    assert wt2.path == wt1.path
    cleanup_worktree(repo, wt1)


def test_detect_and_revert_scope_breach(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = allocate_worktree(repo, tmp_path / "wts", run_id="r", lane_id="telemetry", wave_id="W1")
    forbidden = ["src/sevn/gateway/agent_turn.py", "Makefile (ci: line)"]

    # Edit a forbidden file (out of lane).
    target = wt.path / "src" / "sevn" / "gateway"
    target.mkdir(parents=True)
    (target / "agent_turn.py").write_text("breach\n")
    _git(wt.path, "add", "src/sevn/gateway/agent_turn.py")

    breached = detect_scope_breach(wt.path, forbidden)
    assert breached == ["src/sevn/gateway/agent_turn.py"]

    revert_breach(wt.path, breached)
    assert detect_scope_breach(wt.path, forbidden) == []
    assert not (target / "agent_turn.py").exists()

    cleanup_worktree(repo, wt)


def test_stage_dispatch_context_stages_wave_slice(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    wt = tmp_path / "wt"
    run_dir.mkdir()
    wt.mkdir()
    (run_dir / "demo-wave-plan.md").write_text(
        "## Wave W0\n\nDo scaffolding.\n\n## Wave R1\n\nImplement.\n"
    )
    (run_dir / "pre0-decisions.md").write_text("# Pre-0\n")

    dest = stage_dispatch_context(run_dir, wt, "demo-wave-plan.md", wave_id="W0")
    assert dest == wt / "plan" / "tripll"
    slice_path = dest / "demo-wave-plan-wave-W0.md"
    assert slice_path.is_file()
    assert "Do scaffolding." in slice_path.read_text()
    assert "Implement." not in slice_path.read_text()
    assert (dest / "pre0-decisions.md").read_text() == "# Pre-0\n"
    assert not (dest / "demo-wave-plan.md").exists()
    assert not (dest / "parallel-wave.md").exists()


def test_owned_test_path_not_scope_breach(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = allocate_worktree(repo, tmp_path / "wts", run_id="r", lane_id="telemetry", wave_id="W1")
    target = wt.path / "tests" / "channels"
    target.mkdir(parents=True)
    (target / "test_foo.py").write_text("def test_foo(): pass\n")
    _git(wt.path, "add", "tests/channels/test_foo.py")

    forbidden = ["tests/", "src/sevn/gateway/agent_turn.py"]
    owned = ["tests/channels/test_foo.py"]
    assert detect_scope_breach(wt.path, forbidden, owned_paths=owned) == []

    cleanup_worktree(repo, wt)


def test_in_scope_change_not_flagged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = allocate_worktree(repo, tmp_path / "wts", run_id="r", lane_id="telemetry", wave_id="W1")
    owned = wt.path / "src" / "sevn" / "agent"
    owned.mkdir(parents=True)
    (owned / "adapters.py").write_text("ok\n")
    _git(wt.path, "add", "-A")

    forbidden = ["src/sevn/gateway/agent_turn.py"]
    assert detect_scope_breach(wt.path, forbidden) == []

    cleanup_worktree(repo, wt)
