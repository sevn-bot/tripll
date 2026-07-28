"""Tests for L2-W5a hotfix inject CLI and resume dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli import _rewrite_run_inject_argv, app
from tripll.engine import Engine
from tripll.inject import InjectError, apply_hotfix_inject, load_hotfix_tasks
from tripll.ledger import list_attempts, list_waves, open_ledger, transition_wave
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl

runner = CliRunner()

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


def _mark_all_waves_done(rr: RunsRoot, run_id: str) -> None:
    with open_ledger(rr.ledger_path(run_id)) as lc:
        for wave in list_waves(lc, run_id):
            if wave.state != "done":
                transition_wave(lc, run_id, wave.node_id, "done")


@pytest.mark.asyncio
async def test_inject_refused_when_not_paused(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    _mark_all_waves_done(engine.runs_root, rid)

    with pytest.raises(InjectError, match="not paused") as exc:
        apply_hotfix_inject(
            engine.runs_root,
            rid,
            brief="Fix something",
            owned_paths=["src/tripll/engine.py"],
            after="all-waves",
        )
    assert exc.value.exit_code == 2


@pytest.mark.asyncio
async def test_inject_requires_after_flag_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path))
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    run_dir = rr.processing_dir / "demo-run"
    run_dir.mkdir(parents=True)
    args = _rewrite_run_inject_argv(
        [
            "tripll",
            "run",
            "inject",
            "demo-run",
            "--brief",
            "Fix",
            "--paths",
            "src/a.py",
            "--runs-root",
            str(rr.root),
        ]
    )[1:]
    result = runner.invoke(app, args)
    assert result.exit_code == 2


@pytest.mark.asyncio
async def test_inject_dry_run_writes_plan_no_ledger(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    _mark_all_waves_done(engine.runs_root, rid)
    run_dir = engine.runs_root.run_dir(rid)
    (run_dir / "pause-requested.md").write_text("# pause\n")

    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        before = len(list_waves(lc, rid))

    task = apply_hotfix_inject(
        engine.runs_root,
        rid,
        brief="Fix race",
        owned_paths=["src/tripll/engine.py"],
        after="all-waves",
        dry_run=True,
    )
    assert task.dry_run is True
    plan_path = engine.runs_root.injects_dir(rid) / f"{task.task_id}.plan.json"
    assert plan_path.is_file()
    assert not (engine.runs_root.injects_dir(rid) / f"{task.task_id}.json").exists()
    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        assert len(list_waves(lc, rid)) == before
    assert load_hotfix_tasks(run_dir) == []


@pytest.mark.asyncio
async def test_inject_and_resume_dispatches_hotfix(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    _mark_all_waves_done(engine.runs_root, rid)
    run_dir = engine.runs_root.run_dir(rid)
    (run_dir / "pause-requested.md").write_text("# pause\n")

    task = apply_hotfix_inject(
        engine.runs_root,
        rid,
        brief="Fix engine edge case",
        owned_paths=["src/tripll/engine.py"],
        after="demo:all-waves",
    )
    assert task.node_id == "hotfix:HF-1"
    graph_data = json.loads(engine.runs_root.graph_path(rid).read_text(encoding="utf-8"))
    assert task.node_id in graph_data["nodes"]

    adapter.calls = 0
    (run_dir / "pause-requested.md").unlink(missing_ok=True)
    result = await engine.resume(rid)
    assert result.state == "done"
    assert adapter.calls >= 1
    ledger_path = engine.runs_root.processed_dir / rid / "ledger.db"
    with open_ledger(ledger_path) as lc:
        attempts = list_attempts(lc, rid, task.node_id)
    assert attempts
    assert attempts[0].backend == "fake"


@pytest.mark.asyncio
async def test_inject_default_verify_target(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    _mark_all_waves_done(engine.runs_root, rid)
    (engine.runs_root.run_dir(rid) / "pause-requested.md").write_text("# pause\n")

    task = apply_hotfix_inject(
        engine.runs_root,
        rid,
        brief="Verify default",
        owned_paths=["src/tripll/engine.py"],
        after="all-waves",
    )
    assert task.verify_targets == ["make ci-affected"]
    node = json.loads(engine.runs_root.graph_path(rid).read_text())["nodes"][task.node_id]
    assert node["verify_targets"] == ["make ci-affected"]


@pytest.mark.asyncio
async def test_inject_overlap_exit_code(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    _mark_all_waves_done(engine.runs_root, rid)
    (engine.runs_root.run_dir(rid) / "pause-requested.md").write_text("# pause\n")

    with pytest.raises(InjectError) as exc:
        apply_hotfix_inject(
            engine.runs_root,
            rid,
            brief="Overlap paths",
            owned_paths=["src/sevn/demo/"],
            after="all-waves",
        )
    assert exc.value.exit_code == 3
