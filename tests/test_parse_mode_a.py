"""Tests for tripll.parse.parallel_wave — Mode A against the dev_eval set."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tripll.parse.parallel_wave import build_run_graph, build_run_graph_from_dir

if TYPE_CHECKING:
    from tripll.graph import RunGraph

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_EVAL = _REPO_ROOT / "plan" / "dev_eval_14062026"

_EXPECTED_BATCH_ORDER = ["Pre-0", "A", "B", "C", "D", "E", "F", "G", "H", "I", "Final"]


@pytest.fixture
def dev_eval_graph() -> RunGraph:
    if not (_DEV_EVAL / "parallel-wave.md").exists():
        pytest.skip("dev_eval_14062026 set not present")
    return build_run_graph_from_dir(_DEV_EVAL, run_id="dev-eval-test")


def test_batch_order_matches_orchestrator(dev_eval_graph: RunGraph) -> None:
    assert dev_eval_graph.batch_order() == _EXPECTED_BATCH_ORDER


def test_lanes_parsed(dev_eval_graph: RunGraph) -> None:
    # The lane table declares 16 lanes.
    assert len(dev_eval_graph.lanes) >= 10
    assert "telemetry" in dev_eval_graph.lanes


def test_pre0_gates_present(dev_eval_graph: RunGraph) -> None:
    assert len(dev_eval_graph.pre0_gates) >= 10


def test_graph_has_no_cycles_or_dangling(dev_eval_graph: RunGraph) -> None:
    # The real dev_eval lane table contains intentional broad-vs-narrow path
    # ownership (e.g. Hermes-features owns src/sevn/agent/ while Telemetry owns
    # src/sevn/agent/adapters/), so overlap warnings are expected. The graph
    # must, however, contain no cycles and no dangling dependencies.
    errors = dev_eval_graph.validate()
    assert [e for e in errors if "cycle" in e or "dangling" in e] == []


def test_pre0_is_human_gate(dev_eval_graph: RunGraph) -> None:
    pre0 = dev_eval_graph.batches[0]
    assert pre0.batch_id == "Pre-0"
    assert pre0.is_human_gate is True


def test_telemetry_forbidden_includes_cw_hotspots(dev_eval_graph: RunGraph) -> None:
    node = dev_eval_graph.nodes["telemetry:all-waves"]
    assert "src/sevn/gateway/agent_turn.py" in node.forbidden_paths
    assert "infra/sevn.schema.json" in node.forbidden_paths
    # Telemetry must not forbid its own owned paths.
    for owned in node.owned_paths:
        assert owned not in node.forbidden_paths


def test_final_batch_has_gate_commands(dev_eval_graph: RunGraph) -> None:
    final = dev_eval_graph.batches[-1]
    assert final.batch_id == "Final"
    assert "make ci" in final.gate_commands


def test_build_run_graph_minimal() -> None:
    md = (
        "| # | Plan | Effort | Lane |\n|---|--|--|--|\n"
        "| 1 | [a](a.md) | M | Telemetry |\n\n"
        "| Lane | Plans | Owned paths |\n|--|--|--|\n"
        "| Telemetry | #1 | `src/sevn/agent/` |\n"
    )
    g = build_run_graph(md, None, None, run_id="r")
    assert g.batch_order() == _EXPECTED_BATCH_ORDER
    assert "telemetry" in g.lanes
