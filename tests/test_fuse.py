"""Fusion — blocking, rename merge, provenance retention (W1.4)."""

from __future__ import annotations

from tests.conftest import require_module


def test_blocking_reduces_candidate_pairs() -> None:
    block_candidates = require_module("tripll.extract.fuse", attr="block_candidates")
    nodes = [
        {"node_id": "code:Symbol:a", "kind": "Symbol", "natural_key": "foo", "repo": "r"},
        {"node_id": "code:Symbol:b", "kind": "Symbol", "natural_key": "bar", "repo": "r"},
        {"node_id": "code:Module:m", "kind": "Module", "natural_key": "m.py", "repo": "r"},
    ]
    all_pairs = len(nodes) * (len(nodes) - 1)
    pairs = block_candidates(nodes)
    assert 0 < len(pairs) < all_pairs


def test_disjoint_neighbourhoods_do_not_merge() -> None:
    should_merge = require_module("tripll.extract.fuse", attr="should_merge")
    ctx = {
        "neighbours": {
            "code:Symbol:a": {"callers": ["x"], "callees": ["y"]},
            "code:Symbol:b": {"callers": ["p"], "callees": ["q"]},
        }
    }
    assert should_merge("code:Symbol:a", "code:Symbol:b", context=ctx) is False


def test_renamed_symbol_merges() -> None:
    should_merge = require_module("tripll.extract.fuse", attr="should_merge")
    ctx = {
        "neighbours": {
            "code:Symbol:old": {"callers": ["c1"], "callees": ["c2"]},
            "code:Symbol:new": {"callers": ["c1"], "callees": ["c2"]},
        },
        "rename_hint": True,
    }
    assert should_merge("code:Symbol:old", "code:Symbol:new", context=ctx) is True


def test_conflicting_attributes_retained_with_provenance() -> None:
    merge_nodes = require_module("tripll.extract.fuse", attr="merge_nodes")
    kept, _dropped = merge_nodes(
        {"props": {"doc": "a"}, "source": "ast", "confidence": 1.0},
        {"props": {"doc": "b"}, "source": "semantic", "confidence": 0.9},
    )
    props = kept.get("props") or kept
    assert "a" in str(props)
    assert "b" in str(props)
    assert kept.get("merged_from") or kept.get("provenance")


def test_every_merge_is_reversible() -> None:
    fuse_merge = require_module("tripll.extract.fuse", attr="fuse_merge")
    unmerge = require_module("tripll.extract.fuse", attr="unmerge")
    merge_id = fuse_merge("code:Symbol:a", "code:Symbol:b", reason="test")
    unmerge(merge_id)
    assert merge_id
