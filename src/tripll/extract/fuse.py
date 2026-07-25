"""Fusion — blocking, layered matching, deterministic merge, reversibility."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

_MERGE_REGISTRY: dict[str, dict[str, Any]] = {}


def _qualname_token(natural_key: str) -> str:
    if "::" in natural_key:
        return natural_key.rsplit("::", 1)[-1].lower()
    return natural_key.split("#")[-1].lower()


def _acronym(token: str) -> str:
    parts = re.split(r"[_\-.]+", token)
    return "".join(p[0] for p in parts if p).lower()


def block_candidates(
    nodes: list[dict[str, Any]],
    *,
    embedding_similarity: dict[tuple[str, str], float] | None = None,
    embed_threshold: float = 0.85,
) -> list[tuple[str, str]]:
    """Reduce candidate pairs via kind/repo blocking and qualname/acronym tokens."""
    by_block: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for node in nodes:
        kind = str(node.get("kind", ""))
        repo = str(node.get("repo", ""))
        by_block.setdefault((kind, repo), []).append(node)

    pairs: list[tuple[str, str]] = []
    for group in by_block.values():
        if len(group) < 2:
            continue
        for a, b in combinations(group, 2):
            id_a = str(a["node_id"])
            id_b = str(b["node_id"])
            tok_a = _qualname_token(str(a.get("natural_key", "")))
            tok_b = _qualname_token(str(b.get("natural_key", "")))
            same_token = tok_a == tok_b or _acronym(tok_a) == _acronym(tok_b)
            sim_ok = False
            if embedding_similarity:
                sim = embedding_similarity.get((id_a, id_b)) or embedding_similarity.get(
                    (id_b, id_a)
                )
                sim_ok = sim is not None and sim >= embed_threshold
            if same_token or sim_ok or len(group) <= 3:
                pairs.append((id_a, id_b))
    return pairs


def _neighbourhood(node_id: str, context: dict[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    neighbours = context.get("neighbours", {})
    entry = neighbours.get(node_id, {})
    callers = frozenset(str(x) for x in entry.get("callers", []))
    callees = frozenset(str(x) for x in entry.get("callees", []))
    return callers, callees


def should_merge(a: str, b: str, *, context: dict[str, Any] | None = None) -> bool:
    """Layered matching: string/attribute hints plus structural neighbourhood comparison."""
    ctx = context or {}
    if ctx.get("rename_hint"):
        na = _neighbourhood(a, ctx)
        nb = _neighbourhood(b, ctx)
        return na == nb and na != (frozenset(), frozenset())
    na = _neighbourhood(a, ctx)
    nb = _neighbourhood(b, ctx)
    if na != nb:
        return False
    return bool(ctx.get("auto_merge", False))


def merge_nodes(
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge two node payloads, retaining conflicting values with provenance."""
    kept = dict(left)
    dropped = dict(right)
    merged_props: dict[str, Any] = {}
    left_props = left.get("props") or {}
    right_props = right.get("props") or {}
    if isinstance(left_props, str):
        left_props = json.loads(left_props)
    if isinstance(right_props, str):
        right_props = json.loads(right_props)
    if not isinstance(left_props, dict):
        left_props = {"value": left_props}
    if not isinstance(right_props, dict):
        right_props = {"value": right_props}
    for key in set(left_props) | set(right_props):
        lv = left_props.get(key)
        rv = right_props.get(key)
        if lv == rv:
            merged_props[key] = lv
        else:
            merged_props[key] = {
                "values": [
                    {
                        "value": lv,
                        "source": left.get("source"),
                        "confidence": left.get("confidence"),
                    },
                    {
                        "value": rv,
                        "source": right.get("source"),
                        "confidence": right.get("confidence"),
                    },
                ]
            }
    kept["props"] = merged_props
    kept["merged_from"] = json.dumps([left.get("source"), right.get("source")])
    kept["provenance"] = [
        {"source": left.get("source"), "confidence": left.get("confidence")},
        {"source": right.get("source"), "confidence": right.get("confidence")},
    ]
    return kept, dropped


def fuse_merge(keep: str, drop: str, *, reason: str, store: Any | None = None) -> str:
    """Record a reversible merge; uses GraphStore when provided, else in-memory registry."""
    merge_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC).isoformat()
    payload = {"kept": keep, "dropped": drop, "reason": reason, "merged_at": now}
    if store is not None and hasattr(store, "merge"):
        return str(store.merge(keep, drop, reason=reason))
    _MERGE_REGISTRY[merge_id] = payload
    return merge_id


def unmerge(merge_id: str, *, store: Any | None = None) -> None:
    """Reverse a prior merge by id."""
    if store is not None and hasattr(store, "unmerge"):
        store.unmerge(merge_id)
        return
    if merge_id not in _MERGE_REGISTRY:
        raise KeyError(f"merge not found: {merge_id!r}")
    del _MERGE_REGISTRY[merge_id]
