"""Tests for L2-W5b graph↔ledger reconcile (plan-edit surface)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli import _rewrite_run_inject_argv, app
from tripll.engine import Engine
from tripll.inject import InjectError, reconcile_run_graph
from tripll.ledger import get_wave, list_waves, open_ledger, transition_wave
from tripll.parse import build_graph_from_dir
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl

runner = CliRunner()

_PLAN_ALPHA = """# Alpha

## Wave W0 — gate

- [ ] **W0.1** Review alpha scope.

## Files in scope

| Subsystem | Paths |
|--|--|
| Core | `src/alpha/` |
"""

_PLAN_BETA = """# Beta

## Files in scope

| Subsystem | Paths |
|--|--|
| Jobs | `src/beta/` |
"""

_PLAN_GAMMA = """# Gamma

## Files in scope

| Subsystem | Paths |
|--|--|
| UI | `src/gamma/` |
"""


def _make_engine(tmp_path: Path, adapter: FakeAdapter) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )


def _seed_two_plans(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "dual"
    src.mkdir(parents=True)
    (src / "alpha-wave-plan.md").write_text(_PLAN_ALPHA)
    (src / "beta-wave-plan.md").write_text(_PLAN_BETA)
    return src


def _pause(run_dir: Path) -> None:
    (run_dir / "pause-requested.md").write_text("# pause\n", encoding="utf-8")


def _node_ids_for_plans(run_dir: Path, run_id: str, plan_slugs: list[str]) -> list[str]:
    graph = build_graph_from_dir(run_dir, run_id=run_id)
    return sorted(nid for nid, node in graph.nodes.items() if node.plan_id in plan_slugs)


def _mark_done(rr: RunsRoot, run_id: str, node_ids: list[str]) -> None:
    with open_ledger(rr.ledger_path(run_id)) as lc:
        for node_id in node_ids:
            row = get_wave(lc, run_id, node_id)
            if row.state != "done":
                transition_wave(lc, run_id, node_id, "done")


@pytest.mark.asyncio
async def test_reconcile_inserts_new_plan_as_queued(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    alpha_nodes = _node_ids_for_plans(run_dir, rid, ["alpha"])
    _mark_done(engine.runs_root, rid, alpha_nodes)
    _pause(run_dir)

    (run_dir / "gamma-wave-plan.md").write_text(_PLAN_GAMMA, encoding="utf-8")

    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        before = {w.node_id: w.state for w in list_waves(lc, rid)}
        result = reconcile_run_graph(
            engine.runs_root,
            rid,
            lc=lc,
            require_pause=True,
        )

    assert result.dry_run is False
    assert len(result.inserted) == 1
    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        for node_id in result.inserted:
            assert get_wave(lc, rid, node_id).state == "queued"
        for node_id, state in before.items():
            assert get_wave(lc, rid, node_id).state == state


@pytest.mark.asyncio
async def test_reconcile_refuses_removing_done_wave(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    all_nodes = _node_ids_for_plans(run_dir, rid, ["alpha", "beta"])
    _mark_done(engine.runs_root, rid, all_nodes)
    _pause(run_dir)

    (run_dir / "alpha-wave-plan.md").unlink()

    with (
        open_ledger(engine.runs_root.ledger_path(rid)) as lc,
        pytest.raises(InjectError, match="reconcile refused") as exc,
    ):
        reconcile_run_graph(engine.runs_root, rid, lc=lc, require_pause=True)
    assert exc.value.exit_code == 1


@pytest.mark.asyncio
async def test_reconcile_done_unchanged_when_adding(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    alpha_nodes = _node_ids_for_plans(run_dir, rid, ["alpha"])
    _mark_done(engine.runs_root, rid, alpha_nodes)
    _pause(run_dir)
    (run_dir / "gamma-wave-plan.md").write_text(_PLAN_GAMMA, encoding="utf-8")

    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        reconcile_run_graph(engine.runs_root, rid, lc=lc, require_pause=True)
        for node_id in alpha_nodes:
            assert get_wave(lc, rid, node_id).state == "done"


@pytest.mark.asyncio
async def test_reconcile_orphan_queued_logged_not_deleted(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    alpha_nodes = _node_ids_for_plans(run_dir, rid, ["alpha"])
    beta_nodes = _node_ids_for_plans(run_dir, rid, ["beta"])
    _mark_done(engine.runs_root, rid, alpha_nodes)
    _pause(run_dir)
    (run_dir / "beta-wave-plan.md").unlink()

    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        result = reconcile_run_graph(engine.runs_root, rid, lc=lc, require_pause=True)
        assert beta_nodes[0] in result.orphans
        assert get_wave(lc, rid, beta_nodes[0]).state == "queued"


@pytest.mark.asyncio
async def test_reconcile_dry_run_no_ledger_write(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_two_plans(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    _pause(run_dir)
    (run_dir / "gamma-wave-plan.md").write_text(_PLAN_GAMMA, encoding="utf-8")

    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        before = len(list_waves(lc, rid))
        result = reconcile_run_graph(
            engine.runs_root,
            rid,
            lc=lc,
            dry_run=True,
            require_pause=True,
        )
        assert result.dry_run is True
        assert len(result.inserted) == 1
        assert len(list_waves(lc, rid)) == before
    assert (
        not json.loads(engine.runs_root.graph_path(rid).read_text())
        .get("nodes", {})
        .get(result.inserted[0])
    )


@pytest.mark.asyncio
async def test_resume_after_plan_edit_dispatches_new_wave(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    rr = engine.runs_root
    src = rr.input_dir / "solo"
    rr.init()
    src.mkdir(parents=True)
    (src / "alpha-wave-plan.md").write_text(_PLAN_ALPHA, encoding="utf-8")
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = rr.run_dir(rid)
    alpha_nodes = _node_ids_for_plans(run_dir, rid, ["alpha"])
    _mark_done(rr, rid, alpha_nodes)
    _pause(run_dir)
    (run_dir / "gamma-wave-plan.md").write_text(_PLAN_GAMMA, encoding="utf-8")

    with open_ledger(rr.ledger_path(rid)) as lc:
        reconcile_run_graph(rr, rid, lc=lc, require_pause=True)
        gamma_node = next(w.node_id for w in list_waves(lc, rid) if w.plan_id == "gamma")

    adapter.calls = 0
    run_dir.joinpath("pause-requested.md").unlink(missing_ok=True)
    result = await engine.resume(rid)
    assert result.state == "done"
    assert adapter.calls >= 1
    with open_ledger(rr.processed_dir / rid / "ledger.db") as lc:
        assert get_wave(lc, rid, gamma_node).state == "done"


def test_rewrite_run_reconcile_argv() -> None:
    argv = _rewrite_run_inject_argv(["tripll", "run", "reconcile-graph", "my-run", "--dry-run"])
    assert argv == ["tripll", "run-reconcile-graph", "my-run", "--dry-run"]


def test_cli_reconcile_graph_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path))
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    run_dir = rr.processing_dir / "demo-run"
    run_dir.mkdir(parents=True)
    (run_dir / "alpha-wave-plan.md").write_text(_PLAN_ALPHA, encoding="utf-8")
    _pause(run_dir)
    (run_dir / "gamma-wave-plan.md").write_text(_PLAN_GAMMA, encoding="utf-8")
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
            wave_id="W0->Final",
            lane="Alpha",
        )

    args = _rewrite_run_inject_argv(
        [
            "tripll",
            "run",
            "reconcile-graph",
            "demo-run",
            "--dry-run",
            "--runs-root",
            str(rr.root),
        ]
    )[1:]
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert "[dry-run]" in result.stdout
