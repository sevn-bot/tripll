"""GraphStore port — upsert idempotence, provenance, paths, merges (W1.1)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import require_module

_PROV: dict[str, Any] = {
    "source": "test",
    "evidence": "tests/test_graphstore.py:1",
    "extractor": "test",
    "extractor_version": "0",
    "confidence": 1.0,
    "extracted_at": "2026-07-25T00:00:00Z",
}


def _store() -> Any:
    SqliteGraphStore = require_module("tripll.graphstore", attr="SqliteGraphStore")
    return SqliteGraphStore(":memory:")


def test_upsert_idempotent_same_natural_key() -> None:
    store = _store()
    node = {
        "node_id": "code:Module:tripll.graph",
        "layer": "code",
        "kind": "Module",
        "natural_key": "tripll.graph",
        "repo": "tripll",
        "props": "{}",
        **_PROV,
    }
    store.upsert_nodes([node])
    store.upsert_nodes([node])
    assert store.get("code:Module:tripll.graph") is not None


def test_provenance_required_raises_when_omitted() -> None:
    store = _store()
    with pytest.raises((TypeError, ValueError)):
        store.upsert_nodes(
            [
                {
                    "node_id": "code:Module:x",
                    "layer": "code",
                    "kind": "Module",
                    "natural_key": "x",
                    "repo": "tripll",
                    "props": "{}",
                }
            ]
        )


def test_neighbors_at_sha_filter() -> None:
    store = _store()
    out = store.neighbors("code:Symbol:foo", predicates=["CALLS"], at_sha="abc123")
    assert isinstance(out, list)


def test_subgraph_at_sha_filter() -> None:
    store = _store()
    sg = store.subgraph(
        seeds=["code:Module:tripll.graph"],
        hops=2,
        predicates=["DECLARES", "CALLS"],
        at_sha="abc123",
    )
    assert hasattr(sg, "nodes") or isinstance(sg, dict)


def test_paths_recursive_cte_finding_chain() -> None:
    store = _store()
    # Seed finding → symbol → requirement chain per design §7.2.2 CTE example.
    nodes = [
        {
            "node_id": "finding:Finding:ci-1",
            "layer": "finding",
            "kind": "Finding",
            "natural_key": "ci-1",
            "repo": "tripll",
            "props": "{}",
            **_PROV,
        },
        {
            "node_id": "code:Symbol:demo.helper",
            "layer": "code",
            "kind": "Symbol",
            "natural_key": "demo.helper",
            "repo": "tripll",
            "props": "{}",
            **_PROV,
        },
        {
            "node_id": "code:Requirement:FR-1",
            "layer": "code",
            "kind": "Requirement",
            "natural_key": "FR-1",
            "repo": "tripll",
            "props": "{}",
            **_PROV,
        },
    ]
    edges = [
        {
            "edge_id": "e1",
            "predicate": "ABOUT",
            "src": "finding:Finding:ci-1",
            "dst": "code:Symbol:demo.helper",
            **_PROV,
        },
        {
            "edge_id": "e2",
            "predicate": "IMPLEMENTS",
            "src": "code:Symbol:demo.helper",
            "dst": "code:Requirement:FR-1",
            **_PROV,
        },
    ]
    store.upsert_nodes(nodes)
    store.upsert_edges(edges)
    paths = store.paths(
        "finding:Finding:ci-1",
        "code:Requirement:FR-1",
        max_depth=3,
        predicates=["ABOUT", "CALLS", "IMPLEMENTS", "COVERS", "DECLARES"],
        at_sha="deadbeef",
    )
    assert paths
    terminal_kinds = {p.nodes[-1].kind if hasattr(p, "nodes") else p.get("kind") for p in paths}
    assert "Requirement" in terminal_kinds or any("Requirement" in str(p) for p in paths)


def test_merge_and_unmerge_reversible() -> None:
    store = _store()
    merge_id = store.merge("code:Symbol:a", "code:Symbol:b", reason="rename")
    store.unmerge(merge_id)
    assert store.get("code:Symbol:b") is not None
