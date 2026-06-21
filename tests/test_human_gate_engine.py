"""Engine policy: human-gate batch waves skip agent dispatch after Pre-0 approve."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.engine import human_gate_node_ids, nodes_for_batch
from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.pipeline import RunsRoot  # noqa: TC001

from ._fakes import FakeAdapter
from .hitl_helpers import approve_run_with_hitl
from .test_engine import _make_engine

_V1_PLAN = """# Demo plan

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| D1 | Scope | Confirm at W0 review gate. |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets | model | role |
|---------|-------|------------|-------------|--------|----------------|-------|------|
| W0 | Design gate | | yes | M | make lint | | impl |
| R1 | First impl | W0 | | M | make lint | | impl |

## tripll batches

| batch_id | waves | human_gate | parallel |
|----------|-------|------------|----------|
| Pre-0 | W0 | yes | no |
| A | R1 | | no |

## Wave W0 — review gate

- [ ] **W0.7** Review gate: confirm D1 before R1.

## Wave R1 — implementation

- [ ] **R1.1** Implement slice one.

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `src/sevn/demo/` |
"""


def _seed_v1_run(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "demo-set"
    src.mkdir(parents=True)
    (src / "demo-set-wave-plan.md").write_text(_V1_PLAN, encoding="utf-8")
    return src


def test_human_gate_node_ids_from_batches() -> None:
    graph = RunGraph(run_id="r1", source_mode="B")
    lane = Lane(lane_id="plan", owned_paths=["src/"], plans=["plan"])
    w0 = WaveNode("plan:W0", "plan", "p.md", "W0", "lane")
    r1 = WaveNode("plan:R1", "plan", "p.md", "R1", "lane", depends_on=["plan:W0"])
    lane.waves.extend([w0, r1])
    graph.lanes["plan"] = lane
    graph.nodes = {"plan:W0": w0, "plan:R1": r1}
    graph.batches = [
        Batch("Pre-0", "gate", lanes=["plan"], is_human_gate=True, wave_ids=["W0"]),
        Batch("A", "impl", lanes=["plan"], wave_ids=["R1"]),
    ]
    assert human_gate_node_ids(graph) == {"plan:W0"}
    batch_a = graph.batches[1]
    assert [n.node_id for n in nodes_for_batch(graph, batch_a)] == ["plan:R1"]


@pytest.mark.asyncio
async def test_resume_after_pre0_skips_w0_and_dispatches_r1(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_v1_run(engine.runs_root)
    started = await engine.start(src)
    assert started.pre0_pending is True
    assert adapter.calls == 0

    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "done"
    assert adapter.calls == 1
    assert result.nodes["demo-set:W0"].state == "done"
    assert "human gate" in result.nodes["demo-set:W0"].evidence.lower()
