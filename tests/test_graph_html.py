"""Tests for tripll.graph_html — layout, HTML rendering, and the validate hook."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tripll.cli import app
from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.graph_html import layout_graph, render_graph_html, write_graph_html
from tripll.parse import build_graph_from_dir

runner = CliRunner()

EXAMPLE_SOURCE = "docs/examples/wave-graph-input-set"
EXAMPLE_DIR = Path(__file__).resolve().parents[1] / EXAMPLE_SOURCE
EXAMPLE_HTML = Path(__file__).resolve().parents[1] / "docs/examples/wave-graph.html"


def _diamond_graph() -> RunGraph:
    """W0 → W1 → {W2, W3} → Final, single lane."""

    def node(wave_id: str, deps: list[str], **kwargs: object) -> WaveNode:
        return WaveNode(
            node_id=f"p:{wave_id}",
            plan_id="p",
            plan_file="p-wave-plan.md",
            wave_id=wave_id,
            lane="Plan title",
            depends_on=[f"p:{d}" for d in deps],
            **kwargs,  # type: ignore[arg-type]
        )

    nodes = [
        node("W0", [], is_review_gate=True),
        node("W1", ["W0"], role="test-author"),
        node("W2", ["W1"]),
        node("W3", ["W1"]),
        node("Final", ["W2", "W3"]),
    ]
    graph = RunGraph(run_id="r", source_mode="B")
    graph.nodes = {n.node_id: n for n in nodes}
    graph.lanes = {"p": Lane(lane_id="p", plans=["p"], waves=nodes)}
    graph.batches = [
        Batch(batch_id="Pre-0", label="gate", is_human_gate=True, wave_ids=["W0"]),
        Batch(batch_id="A", label="A", wave_ids=["W1"]),
        Batch(batch_id="B", label="B", wave_ids=["W2", "W3"]),
        Batch(batch_id="Final", label="Final", wave_ids=["Final"]),
    ]
    graph.pre0_gates = ["W0: design — review gate"]
    return graph


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


def test_layout_assigns_dependency_depths() -> None:
    layout = layout_graph(_diamond_graph())
    depths = {box.wave_id: box.depth for box in layout.boxes}
    assert depths == {"W0": 0, "W1": 1, "W2": 2, "W3": 2, "Final": 3}


def test_layout_keeps_one_edge_per_dependency() -> None:
    layout = layout_graph(_diamond_graph())
    assert len(layout.edges) == 5
    assert ("p:W2", "p:Final") in layout.edges
    assert ("p:W1", "p:W3") in layout.edges


def test_layout_places_same_depth_nodes_side_by_side() -> None:
    boxes = {box.wave_id: box for box in layout_graph(_diamond_graph()).boxes}
    assert boxes["W2"].y == boxes["W3"].y
    assert boxes["W2"].x != boxes["W3"].x
    assert boxes["W0"].y < boxes["W1"].y < boxes["Final"].y


def test_layout_carries_batch_and_role_metadata() -> None:
    boxes = {box.wave_id: box for box in layout_graph(_diamond_graph()).boxes}
    assert boxes["W0"].batch == "Pre-0"
    assert boxes["W0"].review_gate is True
    assert boxes["W1"].role == "test-author"


def test_layout_ignores_dangling_dependencies() -> None:
    graph = _diamond_graph()
    graph.nodes["p:W0"].depends_on = ["p:missing"]
    layout = layout_graph(graph)
    assert {box.wave_id: box.depth for box in layout.boxes}["W0"] == 0
    assert all(target != "p:missing" for _, target in layout.edges)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_is_self_contained_html() -> None:
    out = render_graph_html(_diamond_graph(), source="in/")
    assert out.startswith("<!DOCTYPE html>")
    assert out.rstrip().endswith("</html>")
    assert "<svg" in out
    assert "http-equiv" not in out
    assert "<script" not in out
    assert "src=" not in out


def test_render_includes_every_node_and_edge() -> None:
    out = render_graph_html(_diamond_graph(), source="in/")
    for node_id in ("p:W0", "p:W1", "p:W2", "p:W3", "p:Final"):
        assert node_id in out
    assert out.count('class="edge"') == 5
    assert "p:W1 → p:W3" in out
    assert "nodes=5 · edges=5" in out


def test_render_lists_pre0_gates() -> None:
    out = render_graph_html(_diamond_graph(), source="in/")
    assert "Pre-0 gates" in out
    assert "W0: design — review gate" in out


def test_render_escapes_markup_in_labels() -> None:
    graph = _diamond_graph()
    graph.nodes["p:W0"].lane = "<script>x</script>"
    out = render_graph_html(graph, source="in/")
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out


def test_render_empty_graph() -> None:
    out = render_graph_html(RunGraph(run_id="r"), source="in/")
    assert "No wave nodes" in out
    assert "<svg" not in out


def test_render_is_deterministic() -> None:
    first = render_graph_html(_diamond_graph(), source="in/")
    second = render_graph_html(_diamond_graph(), source="in/")
    assert first == second


def test_write_graph_html_creates_parent_dirs(tmp_path: Path) -> None:
    out = write_graph_html(_diamond_graph(), tmp_path / "nested" / "g.html", source="in/")
    assert out.is_file()
    assert "<svg" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# validate hook + committed example
# ---------------------------------------------------------------------------


def test_validate_writes_graph_html(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    result = runner.invoke(app, ["validate", str(EXAMPLE_DIR), "--graph-html", str(out)])
    assert result.exit_code == 0, result.output
    assert "Wrote graph HTML" in result.output
    assert "nodes=5 · edges=5" in out.read_text(encoding="utf-8")


def test_validate_without_flag_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLE_DIR)])
    assert result.exit_code == 0, result.output
    assert "Wrote graph HTML" not in result.output
    assert list(tmp_path.iterdir()) == []


def test_committed_example_html_is_current() -> None:
    graph = build_graph_from_dir(EXAMPLE_DIR, run_id="example")
    expected = render_graph_html(graph, source=EXAMPLE_SOURCE)
    assert EXAMPLE_HTML.read_text(encoding="utf-8") == expected, (
        "docs/examples/wave-graph.html is stale — regenerate with: "
        f"tripll validate {EXAMPLE_SOURCE} --graph-html docs/examples/wave-graph.html"
    )
