"""Characterization tests for :mod:`tripll.engine_scheduling` (issue #16 seam)."""

from __future__ import annotations

from tripll.engine import (
    can_run_concurrently,
    human_gate_node_ids,
    nodes_for_batch,
    orchestrator_serial_nodes,
    ready_nodes,
    select_concurrent_set,
)
from tripll.engine_scheduling import (
    can_run_concurrently as scheduling_can_run_concurrently,
)
from tripll.engine_scheduling import (
    human_gate_node_ids as scheduling_human_gate_node_ids,
)
from tripll.engine_scheduling import (
    nodes_for_batch as scheduling_nodes_for_batch,
)
from tripll.engine_scheduling import (
    orchestrator_serial_nodes as scheduling_orchestrator_serial_nodes,
)
from tripll.engine_scheduling import (
    ready_nodes as scheduling_ready_nodes,
)
from tripll.engine_scheduling import (
    select_concurrent_set as scheduling_select_concurrent_set,
)
from tripll.graph import Batch, Lane, OrchestratorConfig, RunGraph, WaveNode


def test_engine_reexports_match_scheduling_module() -> None:
    """Public ``tripll.engine`` API stays aligned with the extracted module."""
    assert ready_nodes is scheduling_ready_nodes
    assert can_run_concurrently is scheduling_can_run_concurrently
    assert select_concurrent_set is scheduling_select_concurrent_set
    assert human_gate_node_ids is scheduling_human_gate_node_ids
    assert nodes_for_batch is scheduling_nodes_for_batch
    assert orchestrator_serial_nodes is scheduling_orchestrator_serial_nodes


def test_orchestrator_serial_nodes_respects_config_order() -> None:
    """Orchestrator serial waves precede remaining topo-sorted nodes."""
    a = WaveNode("l:W2", "l", "p.md", "W2", "lane")
    b = WaveNode("l:W1", "l", "p.md", "W1", "lane")
    graph = RunGraph(
        run_id="r",
        nodes={"l:W1": b, "l:W2": a},
        lanes={"l": Lane("l", "lane", [b, a])},
        batches=[Batch("a", ["l"])],
        orchestrator=OrchestratorConfig(True, "p.md", serial_waves=["W2", "W1"]),
    )
    ordered = orchestrator_serial_nodes(graph)
    assert [n.wave_id for n in ordered] == ["W2", "W1"]
