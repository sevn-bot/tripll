"""L1 outer post-wave nodes — verify, commit, review, generate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tripll.engine import Engine
from tripll.ledger import list_events, open_ledger
from tripll.loops import graph_available
from tripll.loops.dispatch_bridge import invoke_engine_wave_dispatch_async
from tripll.loops.l1_outer import _node_commit, _node_generate, _node_review, _node_verify
from tripll.loops.outer_post_wave import (
    invoke_outer_commit_async,
    invoke_outer_generate_async,
    invoke_outer_review_async,
    invoke_outer_verify_async,
)
from tripll.pipeline import RunsRoot

if TYPE_CHECKING:
    from tripll.loops.state import L1OuterState

from ._fakes import AlwaysFailVerifier, AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl
from .test_engine import MarkingAdapter, _init_repo, _seed_mode_b


def _make_engine(tmp_path: Path, adapter: FakeAdapter, *, verifier: object | None = None) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=verifier or AlwaysPassVerifier(),
    )


async def _seed_done_run(engine: Engine) -> str:
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    return started.run_id


def _run_dir_for(engine: Engine, run_id: str) -> Path:
    found = engine.runs_root.find_run_dir(run_id)
    assert found is not None
    return found


async def _waves_done_state(engine: Engine, run_id: str) -> L1OuterState:
    run_dir = engine.runs_root.run_dir(run_id)
    state: L1OuterState = {
        "run_id": run_id,
        "thread_id": run_id,
        "run_dir": str(run_dir),
        "history": ["validate"],
        "turn": 1,
    }
    wave_result = await invoke_engine_wave_dispatch_async(state, engine=engine)
    return {
        **state,
        "step": "waves",
        "history": ["validate", "waves"],
        "turn": 2,
        "wave_dispatch": {
            "run_id": run_id,
            "state": wave_result.state,
            "waves_done": wave_result.waves_done,
            "waves_dispatched": list(wave_result.waves_dispatched),
            "paused": wave_result.paused,
            "node_details": wave_result.node_details or {},
        },
        "paused": wave_result.paused,
    }


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_verify_sets_ci_green(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path, MarkingAdapter())
    _init_repo(tmp_path)
    run_id = await _seed_done_run(engine)
    state = await _waves_done_state(engine, run_id)

    result = await invoke_outer_verify_async(state, engine=engine)
    assert result.ok is True
    assert result.node == "verify"
    assert result.extra.get("skipped") is False

    verify_fn = _node_verify(run_dir=_run_dir_for(engine, run_id), engine=engine)
    update = await verify_fn({**state, "ci_green": False})
    assert update.get("ci_green") is True
    assert update.get("step") == "verify"


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_verify_fails_with_fail_verifier(tmp_path: Path) -> None:
    pass_engine = _make_engine(tmp_path, MarkingAdapter(), verifier=AlwaysPassVerifier())
    _init_repo(tmp_path)
    run_id = await _seed_done_run(pass_engine)
    state = await _waves_done_state(pass_engine, run_id)

    fail_engine = _make_engine(tmp_path, MarkingAdapter(), verifier=AlwaysFailVerifier())
    fail_engine.runs_root = pass_engine.runs_root
    result = await invoke_outer_verify_async(state, engine=fail_engine)
    assert result.ok is False


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_commit_writes_manifest(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path, MarkingAdapter())
    _init_repo(tmp_path)
    run_id = await _seed_done_run(engine)
    state = await _waves_done_state(engine, run_id)
    state = {**state, "ci_green": True}

    result = await invoke_outer_commit_async(state, engine=engine)
    assert result.ok is True
    run_dir = _run_dir_for(engine, run_id)
    manifest = run_dir / "outer-commit.json"
    assert manifest.is_file()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload.get("waves_done", 0) >= 1


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_review_writes_audit(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path, MarkingAdapter())
    _init_repo(tmp_path)
    run_id = await _seed_done_run(engine)
    state = await _waves_done_state(engine, run_id)

    result = await invoke_outer_review_async(state, engine=engine)
    assert result.extra.get("review_clean") is True
    run_dir = _run_dir_for(engine, run_id)
    review_path = run_dir / "outer-review.json"
    assert review_path.is_file()


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_generate_completes_when_review_clean(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path, MarkingAdapter())
    _init_repo(tmp_path)
    run_id = await _seed_done_run(engine)
    state = await _waves_done_state(engine, run_id)
    state = {**state, "review_clean": True}

    result = await invoke_outer_generate_async(state, engine=engine)
    assert result.ok is True
    assert result.extra.get("action") == "complete"
    run_dir = _run_dir_for(engine, run_id)
    assert (run_dir / "outer-generate.json").is_file()


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_outer_nodes_record_ledger_events(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path, MarkingAdapter())
    _init_repo(tmp_path)
    run_id = await _seed_done_run(engine)
    run_dir = _run_dir_for(engine, run_id)
    state = await _waves_done_state(engine, run_id)

    await _node_verify(run_dir=run_dir, engine=engine)(state)
    state = {**state, "ci_green": True}
    await _node_commit(run_dir=run_dir, engine=engine)(state)
    review_update = await _node_review(run_dir=run_dir, engine=engine)(state)
    await _node_generate(run_dir=run_dir, engine=engine)(
        {**state, **review_update},
    )

    with open_ledger(run_dir / "ledger.db") as lc:
        phases = {e.phase for e in list_events(lc, run_id)}
    assert {"outer_verify", "outer_commit", "outer_review", "outer_generate"}.issubset(phases)


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_simulation_stubs_without_engine(tmp_path: Path) -> None:
    state: L1OuterState = {"run_id": "sim", "thread_id": "sim", "history": [], "turn": 0}
    for fn in (
        invoke_outer_verify_async,
        invoke_outer_commit_async,
        invoke_outer_review_async,
        invoke_outer_generate_async,
    ):
        result = await fn(state, engine=None)
        assert result.ok is True
        assert result.extra.get("simulation") is True


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
async def test_engine_resume_writes_outer_manifests(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    _init_repo(tmp_path)
    run_id = await _seed_done_run(engine)
    adapter.calls = 0

    result = await engine.resume(run_id)
    assert result.state == "done"

    run_dir = engine.runs_root.processed_dir / run_id
    assert run_dir.is_dir()
    assert (run_dir / "outer-commit.json").is_file()
    assert (run_dir / "outer-review.json").is_file()
    assert (run_dir / "outer-generate.json").is_file()
