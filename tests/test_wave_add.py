"""Tests for L2-W5c parallel lane wave-add CLI and resume dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli import app
from tripll.engine import Engine
from tripll.inject import InjectError, apply_wave_add, load_wave_add_tasks
from tripll.ledger import get_wave, list_attempts, list_waves, open_ledger, transition_wave
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl
from .test_reconcile import _PLAN_ALPHA, _PLAN_BETA, _seed_two_plans

runner = CliRunner()


def _make_engine(tmp_path: Path, adapter: FakeAdapter) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )


def _pause(run_dir: Path) -> None:
    (run_dir / "pause-requested.md").write_text("# pause\n", encoding="utf-8")


def _mark_done(rr: RunsRoot, run_id: str, node_ids: list[str]) -> None:
    with open_ledger(rr.ledger_path(run_id)) as lc:
        for node_id in node_ids:
            row = get_wave(lc, run_id, node_id)
            if row.state != "done":
                transition_wave(lc, run_id, node_id, "done")


@pytest.mark.asyncio
async def test_wave_add_refused_when_not_paused(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    _mark_done(engine.runs_root, rid, ["alpha:all-waves"])

    with pytest.raises(InjectError, match="not paused") as exc:
        apply_wave_add(
            engine.runs_root,
            rid,
            lane="docs",
            wave_id="W7",
            brief="Add docs lane",
            owned_paths=["docs/"],
            depends_on=["alpha:all-waves"],
        )
    assert exc.value.exit_code == 2


@pytest.mark.asyncio
async def test_wave_add_dry_run_writes_plan_no_ledger(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    _mark_done(engine.runs_root, rid, ["alpha:all-waves"])
    _pause(run_dir)

    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        before = len(list_waves(lc, rid))

    task = apply_wave_add(
        engine.runs_root,
        rid,
        lane="docs",
        wave_id="W7",
        brief="Docs lane work",
        owned_paths=["docs/"],
        after="alpha:all-waves",
        dry_run=True,
    )
    assert task.dry_run is True
    plan_path = engine.runs_root.injects_dir(rid) / f"{task.task_id}.plan.json"
    assert plan_path.is_file()
    assert not (engine.runs_root.injects_dir(rid) / f"{task.task_id}.json").exists()
    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        assert len(list_waves(lc, rid)) == before
    assert load_wave_add_tasks(run_dir) == []


@pytest.mark.asyncio
async def test_wave_add_current_batch_and_resume_dispatches(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    _mark_done(engine.runs_root, rid, ["alpha:all-waves"])
    _pause(run_dir)

    task = apply_wave_add(
        engine.runs_root,
        rid,
        lane="docs",
        wave_id="W7",
        brief="Parallel docs lane",
        owned_paths=["docs/"],
        after="alpha:all-waves",
        batch_placement="current",
    )
    assert task.node_id == "docs:W7"
    assert task.batch_id == "A"
    graph_data = json.loads(engine.runs_root.graph_path(rid).read_text(encoding="utf-8"))
    assert task.node_id in graph_data["nodes"]
    assert "docs" in graph_data["batches"][1]["lanes"]

    adapter.calls = 0
    run_dir.joinpath("pause-requested.md").unlink(missing_ok=True)
    result = await engine.resume(rid)
    assert result.state == "done"
    assert adapter.calls >= 1
    ledger_path = engine.runs_root.processed_dir / rid / "ledger.db"
    with open_ledger(ledger_path) as lc:
        attempts = list_attempts(lc, rid, task.node_id)
        assert attempts
        assert get_wave(lc, rid, task.node_id).state == "done"


@pytest.mark.asyncio
async def test_wave_add_overlap_exit_code(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    _mark_done(engine.runs_root, rid, ["alpha:all-waves"])
    _pause(run_dir)

    with pytest.raises(InjectError) as exc:
        apply_wave_add(
            engine.runs_root,
            rid,
            lane="overlap",
            wave_id="W1",
            brief="Overlap paths",
            owned_paths=["src/alpha/"],
            after="alpha:all-waves",
        )
    assert exc.value.exit_code == 3


@pytest.mark.asyncio
async def test_wave_add_batch_next_creates_inject_batch(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    _mark_done(engine.runs_root, rid, ["alpha:all-waves", "beta:all-waves"])
    _pause(run_dir)

    task = apply_wave_add(
        engine.runs_root,
        rid,
        lane="docs",
        wave_id="W8",
        brief="Next batch docs",
        owned_paths=["docs/"],
        after="alpha:all-waves",
        batch_placement="next",
    )
    assert task.batch_id.startswith("Inject-")
    graph_data = json.loads(engine.runs_root.graph_path(rid).read_text(encoding="utf-8"))
    batch_ids = [b["batch_id"] for b in graph_data["batches"]]
    assert task.batch_id in batch_ids


def test_cli_wave_add_requires_deps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path))
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    run_dir = rr.processing_dir / "demo-run"
    run_dir.mkdir(parents=True)
    (run_dir / "alpha-wave-plan.md").write_text(_PLAN_ALPHA, encoding="utf-8")
    _pause(run_dir)

    result = runner.invoke(
        app,
        [
            "wave",
            "add",
            "demo-run",
            "--lane",
            "docs",
            "--wave-id",
            "W7",
            "--brief",
            "Docs",
            "--paths",
            "docs/",
            "--runs-root",
            str(rr.root),
        ],
    )
    assert result.exit_code == 2
    assert "depends-on" in result.stdout.lower() or "depends-on" in (result.stderr or "").lower()


def test_cli_wave_add_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path))
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    run_dir = rr.processing_dir / "demo-run"
    run_dir.mkdir(parents=True)
    (run_dir / "alpha-wave-plan.md").write_text(_PLAN_ALPHA, encoding="utf-8")
    (run_dir / "beta-wave-plan.md").write_text(_PLAN_BETA, encoding="utf-8")
    _pause(run_dir)
    from tripll.ledger import insert_run, insert_wave, open_ledger

    with open_ledger(rr.ledger_path("demo-run")) as lc:
        insert_run(
            lc,
            run_id="demo-run",
            slug="demo",
            source_mode="B",
            input_path=str(run_dir),
        )
        insert_wave(
            lc,
            node_id="alpha:all-waves",
            run_id="demo-run",
            plan_id="alpha",
            wave_id="all-waves",
            lane="alpha",
            initial_state="done",
        )

    result = runner.invoke(
        app,
        [
            "wave",
            "add",
            "demo-run",
            "--lane",
            "docs",
            "--wave-id",
            "W7",
            "--brief",
            "Docs lane",
            "--paths",
            "docs/",
            "--after",
            "alpha:all-waves",
            "--dry-run",
            "--runs-root",
            str(rr.root),
        ],
    )
    assert result.exit_code == 0
    assert "[dry-run]" in result.stdout
