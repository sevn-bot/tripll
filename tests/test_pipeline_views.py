"""Tests for tripll.pipeline_views — view derivation, placement, and rendering."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli import app
from tripll.pipeline_spec import PipelineSpec, load_pipeline_spec
from tripll.pipeline_views import (
    PipelineView,
    ViewEdge,
    ViewNode,
    execution_view,
    render_view_html,
    state_view,
    write_view_html,
)

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SOURCE = "docs/examples/pipelines/tripll-l1-pipeline.toml"
SAMPLE = REPO_ROOT / SAMPLE_SOURCE
EXECUTION_HTML = REPO_ROOT / "docs/examples/pipeline-execution-graph.html"
STATE_HTML = REPO_ROOT / "docs/examples/pipeline-state-graph.html"

UNPLACED = """
pipeline_format = 1
title = "Unplaced"

[[steps]]
id = "start"
kind = "external"
produces = "goal"
[[steps.next]]
to = "worker"

[[steps]]
id = "worker"
produces = "built"
wave = "W1"
[[steps.next]]
to = "critic"

[[steps]]
id = "critic"
produces = "graded"
wave = "W2"
[[steps.next]]
to = "worker"
label = "gap → retry"
style = "conditional"
"""


def _sample_spec() -> PipelineSpec:
    return dataclasses.replace(load_pipeline_spec(SAMPLE), source=SAMPLE_SOURCE)


def _unplaced_spec(tmp_path: Path) -> PipelineSpec:
    path = tmp_path / "unplaced.toml"
    path.write_text(UNPLACED, encoding="utf-8")
    return load_pipeline_spec(path)


def _edge(view: PipelineView, source: str, target: str) -> ViewEdge:
    matches = [edge for edge in view.edges if (edge.source, edge.target) == (source, target)]
    assert len(matches) == 1, f"expected exactly one {source} → {target} edge, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# execution view
# ---------------------------------------------------------------------------


def test_execution_view_uses_every_step_and_transition() -> None:
    spec = load_pipeline_spec(SAMPLE)
    view = execution_view(spec)
    assert view.validate() == []
    assert len(view.nodes) == len(spec.steps)
    assert len(view.edges) == sum(len(step.transitions) for step in spec.steps)


def test_execution_view_keeps_file_placement_and_kinds() -> None:
    nodes = execution_view(load_pipeline_spec(SAMPLE)).node_map()
    assert (nodes["pre0-gate"].layer, nodes["pre0-gate"].column) == (3, 1.5)
    assert nodes["pre0-gate"].kind == "gate"
    assert nodes["l1-validate"].kind == "phase"
    assert nodes["implementer"].note == "wave Wi"


def test_execution_view_groups_steps_into_clusters() -> None:
    clusters = {c.label: c.members for c in execution_view(load_pipeline_spec(SAMPLE)).clusters}
    wave_exec = next(members for label, members in clusters.items() if "wave execution" in label)
    assert "test-creator" in wave_exec
    assert "pr-shepherd" not in wave_exec


def test_execution_view_carries_transition_style_and_bow() -> None:
    view = execution_view(load_pipeline_spec(SAMPLE))
    assert _edge(view, "wave-verifier", "implementer").style == "conditional"
    assert _edge(view, "build-plan-from-errors", "plan-author").style == "optional"
    assert _edge(view, "post-review-wave-generator", "outer-pipeline").bow == "right"


def test_execution_view_derives_placement_when_file_omits_it(tmp_path: Path) -> None:
    view = execution_view(_unplaced_spec(tmp_path))
    assert view.validate() == []
    nodes = view.node_map()
    assert nodes["start"].layer == 0
    assert nodes["worker"].layer == 1
    assert nodes["critic"].layer == 2


# ---------------------------------------------------------------------------
# state view
# ---------------------------------------------------------------------------


def test_state_view_nodes_are_produced_states() -> None:
    view = state_view(load_pipeline_spec(SAMPLE))
    assert view.validate() == []
    ids = set(view.node_map())
    assert {"goal", "code-kg", "run-graph", "red-tests", "merge"} <= ids
    assert "test-creator" not in ids


def test_state_view_labels_forward_edges_with_wave_and_agent_chain() -> None:
    view = state_view(load_pipeline_spec(SAMPLE))
    edge = _edge(view, "goal", "code-kg")
    assert edge.label == "W-KG"
    assert edge.note == "graph-extractor → … → graph-fuser"
    assert _edge(view, "red-tests", "wave-commit").note == "implementer"


def test_state_view_labels_feedback_edges_with_their_condition() -> None:
    view = state_view(load_pipeline_spec(SAMPLE))
    retry = _edge(view, "verdict", "wave-commit")
    assert retry.label == "failed → retry"
    assert retry.style == "conditional"
    assert _edge(view, "verdict", "red-tests").label == "wrong test → repair"


def test_state_view_merges_parallel_steps_into_one_edge() -> None:
    view = state_view(load_pipeline_spec(SAMPLE))
    assert _edge(view, "open-pr", "findings").note == "ci-investigator, review-comment-triager"
    assert _edge(view, "findings", "fix-commit").note == "check-fixer, review-comment-fixer"


def test_state_view_drops_loops_through_non_producing_steps() -> None:
    view = state_view(load_pipeline_spec(SAMPLE))
    assert all(edge.source != edge.target for edge in view.edges)
    assert _edge(view, "quality-ok", "wave-commit").label == "gap → next round"


def test_state_view_derives_placement_when_file_omits_it(tmp_path: Path) -> None:
    view = state_view(_unplaced_spec(tmp_path))
    assert view.validate() == []
    nodes = view.node_map()
    assert nodes["goal"].layer == 0
    assert nodes["built"].layer == 1
    assert nodes["graded"].layer == 2
    assert _edge(view, "graded", "built").label == "gap → retry"


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_is_self_contained_html() -> None:
    out = render_view_html(execution_view(load_pipeline_spec(SAMPLE)))
    assert out.startswith("<!DOCTYPE html>")
    assert out.rstrip().endswith("</html>")
    assert "<svg" in out
    assert "<script" not in out
    assert "src=" not in out


def test_render_shows_counts_and_source() -> None:
    out = render_view_html(state_view(_sample_spec()))
    assert "17 nodes · 22 edges" in out
    assert f"source={SAMPLE_SOURCE}" in out


def test_render_escapes_markup_in_labels() -> None:
    view = PipelineView(
        view_id="v",
        title="t",
        subtitle="s",
        nodes=(ViewNode("a", "<script>x</script>", "agent", 0, 0),),
        edges=(),
    )
    out = render_view_html(view)
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out


def test_render_is_deterministic() -> None:
    spec = _sample_spec()
    assert render_view_html(state_view(spec)) == render_view_html(state_view(spec))


def test_render_rejects_invalid_view() -> None:
    view = PipelineView(
        view_id="v",
        title="t",
        subtitle="s",
        nodes=(ViewNode("a", "A", "agent", 0, 0),),
        edges=(ViewEdge("a", "ghost"),),
    )
    with pytest.raises(ValueError, match="unknown node: ghost"):
        render_view_html(view)


def test_write_view_html_creates_parent_dirs(tmp_path: Path) -> None:
    out = write_view_html(
        execution_view(load_pipeline_spec(SAMPLE)),
        tmp_path / "nested" / "v.html",
    )
    assert out.is_file()
    assert "<svg" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI + committed artifacts
# ---------------------------------------------------------------------------


def test_cli_renders_each_view(tmp_path: Path) -> None:
    for view_id in ("execution", "state"):
        out = tmp_path / f"{view_id}.html"
        result = runner.invoke(
            app, ["pipeline-view", str(SAMPLE), "--view", view_id, "--out", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert "Wrote pipeline view" in result.output
        assert "<svg" in out.read_text(encoding="utf-8")


def test_cli_defaults_to_execution_view(tmp_path: Path) -> None:
    out = tmp_path / "default.html"
    result = runner.invoke(app, ["pipeline-view", str(SAMPLE), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "execution graph (agent is node)" in out.read_text(encoding="utf-8")


def test_cli_rejects_unknown_view(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["pipeline-view", str(SAMPLE), "--view", "nope", "--out", str(tmp_path / "x.html")]
    )
    assert result.exit_code == 2
    assert "Unknown view" in result.output


def test_cli_reports_missing_pipeline_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["pipeline-view", str(tmp_path / "absent.toml"), "--out", str(tmp_path / "x.html")]
    )
    assert result.exit_code == 1
    assert "Pipeline file not found" in result.output


def test_cli_reports_malformed_pipeline_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("pipeline_format = 2\n", encoding="utf-8")
    result = runner.invoke(app, ["pipeline-view", str(bad), "--out", str(tmp_path / "x.html")])
    assert result.exit_code == 1
    assert "Pipeline view failed" in result.output


@pytest.mark.parametrize(
    ("builder", "path", "view_id"),
    [(execution_view, EXECUTION_HTML, "execution"), (state_view, STATE_HTML, "state")],
)
def test_committed_example_html_is_current(
    builder: Callable[[PipelineSpec], PipelineView], path: Path, view_id: str
) -> None:
    expected = render_view_html(builder(_sample_spec()))
    assert path.read_text(encoding="utf-8") == expected, (
        f"{path.relative_to(REPO_ROOT)} is stale — regenerate with: tripll pipeline-view "
        f"{SAMPLE_SOURCE} --view {view_id} --out {path.relative_to(REPO_ROOT)}"
    )
