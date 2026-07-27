"""Graph-packed brief builder — seeds, subgraph, finding paths (§7.6)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tripll.graphstore import GraphStore, SqliteGraphStore

if TYPE_CHECKING:
    from tripll.graphstore import Edge, Node, Subgraph

__all__ = ["FINDING_PATH_PREDICATES", "SUBGRAPH_PREDICATES", "pack_brief"]

SUBGRAPH_PREDICATES = [
    "DECLARES",
    "CALLS",
    "COVERS",
    "IMPLEMENTS",
    "SPECIFIES",
    "OWNS",
]

FINDING_PATH_PREDICATES = [
    "ABOUT",
    "DECLARES",
    "CALLS",
    "COVERS",
    "IMPLEMENTS",
]


def _store_from_arg(graph_store: GraphStore | str) -> GraphStore:
    if isinstance(graph_store, str):
        return SqliteGraphStore(graph_store)
    return graph_store


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _path_to_module_id(target: str) -> str:
    path = target.rstrip("/")
    return f"code:Module:{path}"


def _seeds_from_targets(targets: list[str], store: GraphStore) -> list[str]:
    seeds: list[str] = []
    seen: set[str] = set()
    for target in targets:
        path = str(target).strip()
        if not path:
            continue
        for candidate in (path, _path_to_module_id(path)):
            if candidate not in seen:
                seen.add(candidate)
                seeds.append(candidate)
        module = store.get(_path_to_module_id(path))
        if module is not None and module.node_id not in seen:
            seen.add(module.node_id)
            seeds.append(module.node_id)
        for edge in store.neighbors(
            _path_to_module_id(path),
            predicates=["DECLARES"],
            direction="out",
        ):
            if edge.dst not in seen:
                seen.add(edge.dst)
                seeds.append(edge.dst)
    return seeds


def _provenance_label(node: Node | Edge) -> str:
    evidence = getattr(node, "evidence", None) or ""
    if evidence:
        return str(evidence)
    source = getattr(node, "source", "") or "unknown"
    return f"file:{source}"


def _render_triple_table(subgraph: Subgraph) -> str:
    by_head: dict[str, list[tuple[str, str, str]]] = {}
    node_by_id = {node.node_id: node for node in subgraph.nodes}
    for edge in subgraph.edges:
        head = edge.src
        tail_kind = node_by_id.get(edge.dst)
        tail_label = tail_kind.natural_key if tail_kind else edge.dst
        by_head.setdefault(head, []).append(
            (edge.predicate, tail_label, _provenance_label(edge)),
        )
    if not by_head and subgraph.nodes:
        for node in subgraph.nodes:
            by_head.setdefault(node.node_id, []).append(
                ("node", node.kind, _provenance_label(node)),
            )
    lines = ["| head | predicate | tail | evidence |", "| --- | --- | --- | --- |"]
    for head, rows in sorted(by_head.items()):
        head_label = node_by_id[head].natural_key if head in node_by_id else head
        for predicate, tail, evidence in rows:
            lines.append(f"| {head_label} | {predicate} | {tail} | {evidence} |")
    if len(lines) == 2:
        lines.append("| (empty) | node | — | file:brief_packer.py |")
    return "\n".join(lines)


def _finding_paths(
    store: GraphStore,
    open_findings: list[dict[str, Any]],
    *,
    at_sha: str,
) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    for finding in open_findings:
        finding_id = str(finding.get("finding_id") or finding.get("id") or "").strip()
        if not finding_id:
            continue
        src = finding_id if ":" in finding_id else f"finding:Finding:{finding_id}"
        dst_hint = str(finding.get("requirement_id") or finding.get("about") or "").strip()
        recorded = False
        if dst_hint:
            dst = dst_hint if ":" in dst_hint else f"code:Requirement:{dst_hint}"
            for result in store.paths(
                src,
                dst,
                max_depth=4,
                predicates=FINDING_PATH_PREDICATES,
                at_sha=at_sha,
            ):
                paths.append(
                    {
                        "finding_id": finding_id,
                        "path": result.path,
                        "depth": result.depth,
                    }
                )
                recorded = True
        if not recorded:
            about_edges = store.neighbors(src, predicates=["ABOUT"], direction="out", at_sha=at_sha)
            for edge in about_edges:
                for result in store.paths(
                    src,
                    edge.dst,
                    max_depth=4,
                    predicates=FINDING_PATH_PREDICATES,
                    at_sha=at_sha,
                ):
                    paths.append(
                        {
                            "finding_id": finding_id,
                            "path": result.path,
                            "depth": result.depth,
                        }
                    )
                    recorded = True
        if not recorded:
            paths.append({"finding_id": finding_id, "path": src, "depth": 0})
    return paths


def _apply_token_cap(
    fields: dict[str, str],
    *,
    per_field_token_cap: int | None,
    run_dir: Path | None,
) -> tuple[dict[str, str], list[str], list[str]]:
    if per_field_token_cap is None or per_field_token_cap <= 0:
        return fields, [], []
    spill_files: list[str] = []
    spilled_fields: list[str] = []
    out = dict(fields)
    spill_root = (run_dir or Path(".")) / "brief-spill"
    for key, value in fields.items():
        if _estimate_tokens(value) <= per_field_token_cap:
            continue
        spilled_fields.append(key)
        spill_root.mkdir(parents=True, exist_ok=True)
        spill_id = f"{key}-{uuid.uuid4().hex[:8]}"
        spill_path = spill_root / f"{spill_id}.md"
        spill_path.write_text(value, encoding="utf-8")
        spill_files.append(str(spill_path))
        out[key] = f"(spilled to {spill_path.name}; id={spill_id})"
    return out, spill_files, spilled_fields


def pack_brief(
    *,
    wave: dict[str, Any],
    graph_store: GraphStore | str,
    at_sha: str,
    open_findings: list[dict[str, Any]] | None = None,
    max_hops: int = 2,
    run_dir: Path | str | None = None,
    per_field_token_cap: int | None = None,
) -> dict[str, Any]:
    """Pack a wave brief subgraph from TARGETS and open findings (§7.6)."""
    store = _store_from_arg(graph_store)
    targets = [str(t) for t in wave.get("targets") or []]
    hops = max(0, min(int(max_hops), 2))
    seeds = _seeds_from_targets(targets, store)
    subgraph = store.subgraph(
        seeds,
        hops=hops,
        predicates=SUBGRAPH_PREDICATES,
        at_sha=at_sha,
    )
    finding_paths = _finding_paths(store, open_findings or [], at_sha=at_sha)
    triple_table = _render_triple_table(subgraph)
    fields = {"triple_table": triple_table}
    spill_dir = Path(run_dir) if run_dir is not None else None
    capped, spill_files, spilled_fields = _apply_token_cap(
        fields,
        per_field_token_cap=per_field_token_cap,
        run_dir=spill_dir,
    )
    brief: dict[str, Any] = {
        "wave_id": str(wave.get("id") or wave.get("wave_id") or ""),
        "seeds": seeds,
        "max_hops": hops,
        "at_sha": at_sha,
        "subgraph_nodes": len(subgraph.nodes),
        "subgraph_edges": len(subgraph.edges),
        "finding_paths": finding_paths,
        "triple_table": capped["triple_table"],
    }
    if spill_files:
        brief["spill_files"] = spill_files
    if spilled_fields:
        brief["spilled_fields"] = spilled_fields
    brief["subgraph"] = {
        "nodes": [node.node_id for node in subgraph.nodes],
        "edges": [
            {"predicate": edge.predicate, "src": edge.src, "dst": edge.dst}
            for edge in subgraph.edges
        ],
    }
    brief["packed_json"] = json.dumps(
        {
            "seeds": seeds,
            "finding_paths": finding_paths,
            "triple_table": capped["triple_table"],
        },
        indent=2,
    )
    return brief
