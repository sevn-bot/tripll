"""L2-W4 — l1_outer real wave dispatch via Engine seam."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tripll.engine import Engine
from tripll.loops import graph_available
from tripll.loops.dispatch_bridge import invoke_engine_wave_dispatch_async
from tripll.loops.l1_outer import _node_waves
from tripll.pipeline import RunsRoot

if TYPE_CHECKING:
    from tripll.loops.state import L1OuterState

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl
from .test_engine import MarkingAdapter, _init_repo, _seed_mode_b


def _make_engine(tmp_path: Path, adapter: FakeAdapter) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )


async def _seed_paused_run(engine: Engine) -> str:
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    return started.run_id


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_invoke_engine_wave_dispatch_dispatches_waves(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    _init_repo(tmp_path)
    run_id = await _seed_paused_run(engine)
    approve_run_with_hitl(engine, run_id)
    adapter.calls = 0

    run_dir = engine.runs_root.run_dir(run_id)
    state: L1OuterState = {
        "run_id": run_id,
        "thread_id": run_id,
        "run_dir": str(run_dir),
        "history": ["validate"],
        "turn": 1,
    }
    result = await invoke_engine_wave_dispatch_async(state, engine=engine)
    assert result.state == "done"
    assert result.waves_done >= 1
    assert adapter.calls >= 1
    assert result.waves_dispatched


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_waves_node_records_wave_dispatch(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    _init_repo(tmp_path)
    run_id = await _seed_paused_run(engine)
    approve_run_with_hitl(engine, run_id)
    adapter.calls = 0
    run_dir = engine.runs_root.run_dir(run_id)

    waves_fn = _node_waves(run_dir=run_dir, engine=engine)
    state: L1OuterState = {
        "run_id": run_id,
        "thread_id": run_id,
        "run_dir": str(run_dir),
        "history": ["validate"],
        "turn": 1,
    }
    update = await waves_fn(state)
    assert update.get("step") == "waves"
    payload = update.get("wave_dispatch") or {}
    assert payload.get("state") == "done"
    assert adapter.calls >= 1


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_engine_resume_uses_outer_loop_waves(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    _init_repo(tmp_path)
    run_id = await _seed_paused_run(engine)
    approve_run_with_hitl(engine, run_id)
    adapter.calls = 0
    result = await engine.resume(run_id)
    assert result.state == "done"
    assert adapter.calls >= 1
