"""Tests for engine pause-marker enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.engine import Engine
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl

_MODE_B_PLAN = (
    "# Demo\n\n"
    "## Wave W0 -- review gate\n\n"
    "- [ ] **W0.1** Review gate: confirm demo scope.\n\n"
    "## Files in scope\n\n| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
)


def _make_engine(tmp_path: Path, adapter: FakeAdapter) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )


def _seed_mode_b(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "demo"
    src.mkdir(parents=True)
    (src / "demo-wave-plan.md").write_text(_MODE_B_PLAN)
    return src


@pytest.mark.asyncio
async def test_pause_marker_stops_before_next_wave(tmp_path: Path) -> None:
    """With pause-requested.md present, the engine pauses before dispatch."""
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    assert started.state == "paused"
    assert started.pre0_pending is True

    # Approve Pre-0 gate but write pause marker before resuming.
    approve_run_with_hitl(engine, started.run_id)
    run_dir = engine.runs_root.run_dir(started.run_id)
    (run_dir / "pause-requested.md").write_text("# Pause requested\n")

    result = await engine.resume(started.run_id)
    assert result.state == "paused"
    # The adapter should NOT have been called -- paused before dispatch.
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_no_pause_marker_runs_normally(tmp_path: Path) -> None:
    """Without pause-requested.md, the engine runs normally."""
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)

    result = await engine.resume(started.run_id)
    assert result.state == "done"
    assert adapter.calls >= 1
