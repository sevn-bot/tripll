"""Tests for tripll.graph — data model + validate()."""

from __future__ import annotations

from tripll.graph import (
    CW_HOTSPOTS,
    Batch,
    Lane,
    RunGraph,
    WaveNode,
    derive_forbidden_paths,
    paths_overlap,
)


def _node(node_id: str, *, deps: list[str] | None = None) -> WaveNode:
    return WaveNode(
        node_id=node_id,
        plan_id=node_id.split(":")[0],
        plan_file="x.md",
        wave_id=node_id.split(":")[-1],
        lane=node_id.split(":")[0],
        depends_on=deps or [],
    )


# ---------------------------------------------------------------------------
# paths_overlap
# ---------------------------------------------------------------------------


def test_paths_overlap_prefix() -> None:
    assert paths_overlap(["src/a/"], ["src/a/x.py"]) is True


def test_paths_overlap_exact() -> None:
    assert paths_overlap(["src/a.py"], ["src/a.py"]) is True


def test_paths_overlap_disjoint() -> None:
    assert paths_overlap(["src/a"], ["src/b"]) is False


def test_paths_overlap_not_substring_false() -> None:
    assert paths_overlap(["src/foo"], ["src/foobar"]) is False


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_empty_graph_ok() -> None:
    assert RunGraph(run_id="r").validate() == []


def test_validate_detects_cycle() -> None:
    g = RunGraph(run_id="r")
    g.nodes = {
        "a:W1": _node("a:W1", deps=["b:W1"]),
        "b:W1": _node("b:W1", deps=["a:W1"]),
    }
    errors = g.validate()
    assert any("cycle" in e for e in errors)


def test_validate_no_cycle_on_dag() -> None:
    g = RunGraph(run_id="r")
    g.nodes = {
        "a:W1": _node("a:W1"),
        "b:W1": _node("b:W1", deps=["a:W1"]),
    }
    assert [e for e in g.validate() if "cycle" in e] == []


def test_validate_detects_overlap() -> None:
    g = RunGraph(run_id="r")
    g.lanes = {
        "a": Lane("a", owned_paths=["src/sevn/x/"]),
        "b": Lane("b", owned_paths=["src/sevn/x/y.py"]),
    }
    errors = g.validate()
    assert any("overlap" in e for e in errors)


def test_validate_no_overlap_disjoint() -> None:
    g = RunGraph(run_id="r")
    g.lanes = {
        "a": Lane("a", owned_paths=["src/sevn/x/"]),
        "b": Lane("b", owned_paths=["src/sevn/y/"]),
    }
    assert [e for e in g.validate() if "overlap" in e] == []


def test_validate_dangling_dep() -> None:
    g = RunGraph(run_id="r")
    g.nodes = {"a:W1": _node("a:W1", deps=["missing:W0"])}
    assert any("dangling" in e for e in g.validate())


def test_validate_unknown_cw_seam() -> None:
    g = RunGraph(run_id="r")
    g.batches = [Batch("A", "x", cw_seams=["CW-9"])]
    assert any("unknown CW seam" in e for e in g.validate())


# ---------------------------------------------------------------------------
# derive_forbidden_paths
# ---------------------------------------------------------------------------


def test_derive_forbidden_includes_other_lanes_and_cw(legacy_cw_hotspots: None) -> None:
    lanes = {
        "a": Lane("a", owned_paths=["src/sevn/a/"]),
        "b": Lane("b", owned_paths=["src/sevn/b/"]),
    }
    forbidden = derive_forbidden_paths("a", lanes)
    assert "src/sevn/b/" in forbidden
    assert "src/sevn/gateway/agent_turn.py" in forbidden  # CW-1
    assert "src/sevn/a/" not in forbidden


def test_derive_forbidden_cw_owner_excluded(legacy_cw_hotspots: None) -> None:
    lanes = {"a": Lane("a", owned_paths=["src/sevn/a/"])}
    forbidden = derive_forbidden_paths("a", lanes, cw_owners={"CW-1": "a"})
    assert "src/sevn/gateway/agent_turn.py" not in forbidden
    # other CW hotspots still forbidden
    assert "infra/sevn.schema.json" in forbidden


def test_derive_forbidden_single_lane_owns_cw_hotspots(legacy_cw_hotspots: None) -> None:
    lanes = {
        "tg": Lane(
            "tg",
            owned_paths=[
                "src/sevn/gateway/http_server.py",
                "infra/sevn.schema.json",
            ],
        ),
    }
    forbidden = derive_forbidden_paths("tg", lanes)
    assert "src/sevn/gateway/http_server.py" not in forbidden
    assert "infra/sevn.schema.json" not in forbidden
    assert "src/sevn/gateway/agent_turn.py" in forbidden


def test_cw_hotspots_default_empty() -> None:
    assert CW_HOTSPOTS == {}


# ---------------------------------------------------------------------------
# to_dict / batch_order
# ---------------------------------------------------------------------------


def test_to_dict_round_trips_run_id() -> None:
    g = RunGraph(run_id="abc", batches=[Batch("Pre-0", "gate")])
    d = g.to_dict()
    assert d["run_id"] == "abc"


def test_batch_order() -> None:
    g = RunGraph(run_id="r", batches=[Batch("Pre-0", "g"), Batch("A", "a"), Batch("Final", "f")])
    assert g.batch_order() == ["Pre-0", "A", "Final"]
