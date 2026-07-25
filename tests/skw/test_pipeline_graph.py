"""Tests for LangGraph pipeline nodes and cross-check routing (Wave W1.2)."""

from __future__ import annotations

import pytest

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.pipeline import PipelineBuilder
from tripll.skw.states import PipelineState

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"
WAVE_IDS = ("W1", "W2", "Final")

EXPECTED_CORE_NODES = frozenset(
    {
        "validate",
        "review",
        "cross_check",
    }
)

REMOVED_LOOP_NODES = frozenset({"generate", "validate_new"})


def test_graph_exposes_core_nodes() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    node_names = set(graph.nodes)
    assert EXPECTED_CORE_NODES.issubset(node_names)


def test_graph_has_no_in_graph_remediation_nodes() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    node_names = set(graph.nodes)
    assert REMOVED_LOOP_NODES.isdisjoint(node_names)


def test_graph_has_no_commit_wave_stub() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    assert "commit_wave" not in graph.nodes


@pytest.mark.parametrize("wave_id", WAVE_IDS)
def test_graph_includes_verify_node_for_each_wave(wave_id: str) -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    assert f"verify_{wave_id}" in graph.nodes


@pytest.mark.parametrize("wave_id", WAVE_IDS)
def test_graph_includes_commit_node_for_each_wave(wave_id: str) -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    assert f"commit_{wave_id}" in graph.nodes


def test_graph_includes_each_wave_node() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    node_names = set(graph.nodes)
    for wave_id in WAVE_IDS:
        assert wave_id in node_names or f"run_{wave_id}" in node_names


@pytest.mark.parametrize(
    ("verdict", "new_wave_files", "expected"),
    [
        ("pass", [], "DONE"),
        ("changes_required", [], "CONTINUE"),
    ],
)
def test_cross_check_outcome(
    verdict: str,
    new_wave_files: list[str],
    expected: str,
) -> None:
    from tripll.skw.pipeline import cross_check_outcome

    state: PipelineState = {
        "verdict": verdict,
        "new_wave_files": new_wave_files,
    }
    assert cross_check_outcome(state) == expected


def test_cross_check_pass_with_new_files_errors() -> None:
    from tripll.skw.pipeline import cross_check_outcome

    state: PipelineState = {
        "verdict": "pass",
        "new_wave_files": ["waves/new-wave-plan.md"],
    }
    with pytest.raises(ValueError, match="new wave-file"):
        cross_check_outcome(state)


def test_review_gate_triggers_interrupt() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    compiled = graph.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "review-gate-test"}}
    result = compiled.invoke(
        {
            "wave_file": str(PIPELINE_FIXTURE),
            "current_wave": "W2",
            "history": [],
        },
        config=config,
    )
    assert result.get("__interrupt__") is not None
