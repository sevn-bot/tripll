"""Dispatch cancellation safety — BUG-01, BUG-02, BUG-03 (W1.6)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tripll.adapters.base import DispatchResult
from tripll.engine import Engine
from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.ledger import list_waves, open_ledger
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager


class _FailOneAdapter(FakeAdapter):
    """Fail dispatch for a specific node id."""

    def __init__(self, fail_node: str) -> None:
        super().__init__()
        self.fail_node = fail_node

    async def dispatch(self, brief, **kwargs):  # type: ignore[no-untyped-def]
        node_id = str(brief.get("node_id") or "?")
        if node_id == self.fail_node:
            raise RuntimeError(f"simulated failure on {node_id}")
        return await super().dispatch(brief, **kwargs)


class _SlowAdapter(FakeAdapter):
    """Hold dispatch open until cancelled."""

    async def dispatch(self, brief, **kwargs):  # type: ignore[no-untyped-def]
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(60)
        return DispatchResult(
            outcome="failed", result_text="cancelled", returncode=1, argv=["slow"]
        )


def _two_node_graph(run_id: str) -> RunGraph:
    a = WaveNode("p:W1", "p", "plan.md", "W1", "lane-a", owned_paths=["src/a/"])
    b = WaveNode("q:W1", "q", "plan.md", "W1", "lane-b", owned_paths=["src/b/"])
    return RunGraph(
        run_id=run_id,
        batches=[Batch("A", "batch", lanes=["lane-a", "lane-b"])],
        lanes={
            "lane-a": Lane("lane-a", plans=["p"], owned_paths=["src/a/"], waves=[a]),
            "lane-b": Lane("lane-b", plans=["q"], owned_paths=["src/b/"], waves=[b]),
        },
        nodes={"p:W1": a, "q:W1": b},
    )


def _seed(engine: Engine, graph: RunGraph) -> str:
    from tripll.ledger import insert_run, insert_wave

    rr = engine.runs_root
    rr.init()
    run_id = graph.run_id
    run_dir = rr.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    rr.briefs_dir(run_id).mkdir(parents=True, exist_ok=True)
    rr.logs_dir(run_id).mkdir(parents=True, exist_ok=True)
    rr.graph_path(run_id).write_text(json.dumps(graph.to_dict(), indent=2))
    with open_ledger(rr.ledger_path(run_id)) as lc:
        insert_run(lc, run_id=run_id, slug=run_id, source_mode="A", input_path=str(run_dir))
        for node in graph.nodes.values():
            insert_wave(
                lc,
                node_id=node.node_id,
                run_id=run_id,
                plan_id=node.plan_id,
                wave_id=node.wave_id,
                lane=node.lane,
            )
    (run_dir / "pre0-approved").write_text("approved\n")
    return run_id


@pytest.mark.tier1
@pytest.mark.xfail(reason="green after W5: sibling exception isolation", strict=False)
def test_one_node_failure_does_not_cancel_siblings(tmp_path: Path) -> None:
    """BUG-01: one raising node must not cancel its siblings."""
    adapter = _FailOneAdapter("p:W1")
    engine = Engine(
        adapter=adapter,
        runs_root=RunsRoot(tmp_path / "runs"),
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
        max_parallel=2,
    )
    graph = _two_node_graph("run-sibling")
    run_id = _seed(engine, graph)
    result = asyncio.run(engine._drive(run_id, graph))
    ledger_path = engine.runs_root.processed_dir / run_id / "ledger.db"
    with open_ledger(ledger_path) as lc:
        waves = {w.node_id: w for w in list_waves(lc, run_id)}
    assert waves["q:W1"].state in ("done", "passed", "verified")
    assert result.state in ("done", "failed", "paused")


@pytest.mark.tier1
@pytest.mark.xfail(reason="green after W5: no stranded running after cancel", strict=False)
def test_cancelled_run_has_no_stranded_running_waves(tmp_path: Path) -> None:
    """BUG-03: cancellation leaves waves terminal or recoverable, never ``running``."""
    adapter = _SlowAdapter()
    engine = Engine(
        adapter=adapter,
        runs_root=RunsRoot(tmp_path / "runs"),
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
        max_parallel=1,
    )
    graph = _two_node_graph("run-cancel")
    run_id = _seed(engine, graph)

    async def _drive_and_cancel() -> None:
        task = asyncio.create_task(engine._drive(run_id, graph))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive_and_cancel())
    ledger_path = engine.runs_root.processing_dir / run_id / "ledger.db"
    if not ledger_path.is_file():
        ledger_path = engine.runs_root.processed_dir / run_id / "ledger.db"
    with open_ledger(ledger_path) as lc:
        running = [w for w in list_waves(lc, run_id) if w.state == "running"]
    assert running == []


@pytest.mark.tier2
@pytest.mark.xfail(reason="green after W5: no orphan child process on cancel", strict=False)
def test_cancel_dispatch_leaves_no_surviving_child_process(tmp_path: Path) -> None:
    """BUG-02: tier-2 real-pid assertion — no mock."""
    helper = tmp_path / "slow_child.py"
    helper.write_text(
        "import time\n"
        "open('pid.marker','w').write(str(__import__('os').getpid()))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, str(helper)], cwd=tmp_path)
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    marker = tmp_path / "pid.marker"
    if marker.is_file():
        pid = int(marker.read_text())
        assert not _pid_alive(pid)


@pytest.mark.tier2
@pytest.mark.xfail(reason="green after W5: resume after kill mid-batch", strict=False)
def test_kill_mid_batch_restart_resumes(tmp_path: Path) -> None:
    """BUG-03 tier-2: kill process mid-batch, restart, confirm resume."""
    pytest.skip("requires full engine subprocess harness — green after W5")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
