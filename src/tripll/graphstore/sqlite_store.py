"""SQLite implementation of the GraphStore port."""

from __future__ import annotations

import json
import sqlite3  # noqa: TC003 — Row/Connection used at runtime
import uuid
from datetime import UTC, datetime
from typing import Literal

from tripll.graphstore import (
    Edge,
    EdgeInput,
    Node,
    NodeInput,
    PathResult,
    Subgraph,
    validate_provenance,
)
from tripll.graphstore.migrate import migrate_path


def _row_to_node(row: sqlite3.Row) -> Node:
    return Node(
        node_id=str(row["node_id"]),
        layer=str(row["layer"]),
        kind=str(row["kind"]),
        natural_key=str(row["natural_key"]),
        repo=row["repo"],
        props=str(row["props"]),
        source=str(row["source"]),
        evidence=row["evidence"],
        extractor=str(row["extractor"]),
        extractor_version=str(row["extractor_version"]),
        confidence=float(row["confidence"]),
        extracted_at=str(row["extracted_at"]),
        valid_from_sha=row["valid_from_sha"],
        valid_to_sha=row["valid_to_sha"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        merged_from=row["merged_from"],
    )


def _row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        edge_id=str(row["edge_id"]),
        predicate=str(row["predicate"]),
        src=str(row["src"]),
        dst=str(row["dst"]),
        props=str(row["props"]),
        reason=row["reason"],
        source=str(row["source"]),
        evidence=row["evidence"],
        extractor=str(row["extractor"]),
        extractor_version=str(row["extractor_version"]),
        confidence=float(row["confidence"]),
        extracted_at=str(row["extracted_at"]),
        valid_from_sha=row["valid_from_sha"],
        valid_to_sha=row["valid_to_sha"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        merged_from=row["merged_from"],
    )


def _sha_clause(alias: str, at_sha: str | None) -> tuple[str, list[str]]:
    if at_sha is None:
        return (
            f"({alias}.valid_to IS NULL AND {alias}.valid_to_sha IS NULL)",
            [],
        )
    return (
        f"({alias}.valid_to IS NULL"
        f" AND ({alias}.valid_from_sha IS NULL OR {alias}.valid_from_sha <= ?)"
        f" AND ({alias}.valid_to_sha IS NULL OR {alias}.valid_to_sha > ?))",
        [at_sha, at_sha],
    )


class SqliteGraphStore:
    """SQLite-backed graph store — system of record for all three layers."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = migrate_path(db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def upsert_nodes(self, nodes: list[NodeInput]) -> None:
        for node in nodes:
            validate_provenance(node, label="node")
        with self._conn:
            for node in nodes:
                self._conn.execute(
                    """INSERT INTO nodes (
                           node_id, layer, kind, natural_key, repo, props,
                           source, evidence, extractor, extractor_version,
                           confidence, extracted_at,
                           valid_from_sha, valid_to_sha, valid_from, valid_to, merged_from
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(node_id) DO UPDATE SET
                           layer=excluded.layer, kind=excluded.kind,
                           natural_key=excluded.natural_key, repo=excluded.repo,
                           props=excluded.props, source=excluded.source,
                           evidence=excluded.evidence, extractor=excluded.extractor,
                           extractor_version=excluded.extractor_version,
                           confidence=excluded.confidence, extracted_at=excluded.extracted_at,
                           valid_from_sha=excluded.valid_from_sha,
                           valid_to_sha=excluded.valid_to_sha,
                           valid_from=excluded.valid_from, valid_to=excluded.valid_to,
                           merged_from=excluded.merged_from""",
                    (
                        node["node_id"],
                        node["layer"],
                        node["kind"],
                        node["natural_key"],
                        node.get("repo"),
                        node.get("props", "{}"),
                        node["source"],
                        node.get("evidence"),
                        node["extractor"],
                        node["extractor_version"],
                        node["confidence"],
                        node["extracted_at"],
                        node.get("valid_from_sha"),
                        node.get("valid_to_sha"),
                        node.get("valid_from"),
                        node.get("valid_to"),
                        node.get("merged_from"),
                    ),
                )

    def upsert_edges(self, edges: list[EdgeInput]) -> None:
        for edge in edges:
            validate_provenance(edge, label="edge")
        with self._conn:
            for edge in edges:
                self._conn.execute(
                    """INSERT INTO edges (
                           edge_id, predicate, src, dst, props, reason,
                           source, evidence, extractor, extractor_version,
                           confidence, extracted_at,
                           valid_from_sha, valid_to_sha, valid_from, valid_to, merged_from
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(edge_id) DO UPDATE SET
                           predicate=excluded.predicate, src=excluded.src, dst=excluded.dst,
                           props=excluded.props, reason=excluded.reason,
                           source=excluded.source, evidence=excluded.evidence,
                           extractor=excluded.extractor,
                           extractor_version=excluded.extractor_version,
                           confidence=excluded.confidence, extracted_at=excluded.extracted_at,
                           valid_from_sha=excluded.valid_from_sha,
                           valid_to_sha=excluded.valid_to_sha,
                           valid_from=excluded.valid_from, valid_to=excluded.valid_to,
                           merged_from=excluded.merged_from""",
                    (
                        edge["edge_id"],
                        edge["predicate"],
                        edge["src"],
                        edge["dst"],
                        edge.get("props", "{}"),
                        edge.get("reason"),
                        edge["source"],
                        edge.get("evidence"),
                        edge["extractor"],
                        edge["extractor_version"],
                        edge["confidence"],
                        edge["extracted_at"],
                        edge.get("valid_from_sha"),
                        edge.get("valid_to_sha"),
                        edge.get("valid_from"),
                        edge.get("valid_to"),
                        edge.get("merged_from"),
                    ),
                )

    def get(self, node_id: str) -> Node | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ? AND valid_to IS NULL", (node_id,)
        ).fetchone()
        return _row_to_node(row) if row else None

    def neighbors(
        self,
        node_id: str,
        *,
        predicates: list[str] | None = None,
        direction: Literal["out", "in", "both"] = "out",
        at_sha: str | None = None,
    ) -> list[Edge]:
        edge_valid, edge_params = _sha_clause("e", at_sha)
        pred_clause = ""
        params: list[object] = []
        if predicates:
            placeholders = ",".join("?" for _ in predicates)
            pred_clause = f" AND e.predicate IN ({placeholders})"
            params.extend(predicates)
        rows: list[sqlite3.Row] = []
        if direction in ("out", "both"):
            rows.extend(
                self._conn.execute(
                    f"SELECT e.* FROM edges e WHERE e.src = ? AND {edge_valid}{pred_clause}",
                    [node_id, *edge_params, *params],
                ).fetchall()
            )
        if direction in ("in", "both"):
            rows.extend(
                self._conn.execute(
                    f"SELECT e.* FROM edges e WHERE e.dst = ? AND {edge_valid}{pred_clause}",
                    [node_id, *edge_params, *params],
                ).fetchall()
            )
        return [_row_to_edge(row) for row in rows]

    def paths(
        self,
        src: str,
        dst: str,
        *,
        max_depth: int = 3,
        predicates: list[str] | None = None,
        at_sha: str | None = None,
    ) -> list[PathResult]:
        edge_valid, edge_params = _sha_clause("e", at_sha)
        pred_clause = ""
        pred_params: list[object] = []
        if predicates:
            placeholders = ",".join("?" for _ in predicates)
            pred_clause = f" AND e.predicate IN ({placeholders})"
            pred_params = list(predicates)
        sql = f"""
            WITH RECURSIVE reach(node_id, depth, path) AS (
                SELECT ?, 0, ?
              UNION ALL
                SELECT e.dst, r.depth + 1, r.path || '>' || e.dst
                  FROM edges e JOIN reach r ON e.src = r.node_id
                 WHERE r.depth < ? AND {edge_valid}{pred_clause}
            )
            SELECT r.node_id, r.depth, r.path FROM reach r WHERE r.node_id = ?
            ORDER BY r.depth
        """
        params: list[object] = [src, src, max_depth, *edge_params, *pred_params, dst]
        rows = self._conn.execute(sql, params).fetchall()
        results: list[PathResult] = []
        for row in rows:
            node_ids = str(row["path"]).split(">")
            node_rows = self._conn.execute(
                f"SELECT * FROM nodes WHERE node_id IN ({','.join('?' for _ in node_ids)})",
                node_ids,
            ).fetchall()
            by_id = {str(n["node_id"]): _row_to_node(n) for n in node_rows}
            path_nodes = [by_id[nid] for nid in node_ids if nid in by_id]
            results.append(
                PathResult(nodes=path_nodes, depth=int(row["depth"]), path=str(row["path"]))
            )
        return results

    def subgraph(
        self,
        seeds: list[str],
        *,
        hops: int = 2,
        predicates: list[str] | None = None,
        at_sha: str | None = None,
    ) -> Subgraph:
        if not seeds:
            return Subgraph()
        edge_valid, edge_params = _sha_clause("e", at_sha)
        pred_clause = ""
        pred_params: list[object] = []
        if predicates:
            placeholders = ",".join("?" for _ in predicates)
            pred_clause = f" AND e.predicate IN ({placeholders})"
            pred_params = list(predicates)
        seed_ph = ",".join("?" for _ in seeds)
        sql = f"""
            WITH RECURSIVE reach(node_id, depth) AS (
                SELECT node_id, 0 FROM nodes
                 WHERE node_id IN ({seed_ph}) AND valid_to IS NULL
              UNION ALL
                SELECT e.dst, r.depth + 1 FROM edges e
                  JOIN reach r ON e.src = r.node_id
                 WHERE r.depth < ? AND {edge_valid}{pred_clause}
            )
            SELECT DISTINCT node_id FROM reach
        """
        node_ids = [
            str(r[0])
            for r in self._conn.execute(sql, [*seeds, hops, *edge_params, *pred_params]).fetchall()
        ]
        if not node_ids:
            return Subgraph()
        n_ph = ",".join("?" for _ in node_ids)
        nodes = [
            _row_to_node(r)
            for r in self._conn.execute(
                f"SELECT * FROM nodes WHERE node_id IN ({n_ph}) AND valid_to IS NULL",
                node_ids,
            ).fetchall()
        ]
        edge_valid2, edge_params2 = _sha_clause("e", at_sha)
        edges = [
            _row_to_edge(r)
            for r in self._conn.execute(
                f"SELECT e.* FROM edges e WHERE e.src IN ({n_ph}) AND e.dst IN ({n_ph})"
                f" AND {edge_valid2}",
                [*node_ids, *node_ids, *edge_params2],
            ).fetchall()
        ]
        return Subgraph(nodes=nodes, edges=edges)

    def snapshot(self, label: str) -> str:
        snapshot_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS snapshots (
                       snapshot_id TEXT PRIMARY KEY, label TEXT NOT NULL,
                       created_at TEXT NOT NULL, payload TEXT NOT NULL)"""
            )
            payload = {
                "nodes": [
                    dict(r)
                    for r in self._conn.execute(
                        "SELECT * FROM nodes WHERE valid_to IS NULL"
                    ).fetchall()
                ],
                "edges": [
                    dict(r)
                    for r in self._conn.execute(
                        "SELECT * FROM edges WHERE valid_to IS NULL"
                    ).fetchall()
                ],
            }
            self._conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                (snapshot_id, label, now, json.dumps(payload)),
            )
        return snapshot_id

    def merge(self, keep: str, drop: str, *, reason: str) -> str:
        self._ensure_merge_node(keep)
        self._ensure_merge_node(drop)
        dropped = self._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ? AND valid_to IS NULL", (drop,)
        ).fetchone()
        if dropped is None:
            dropped = self._conn.execute(
                "SELECT * FROM nodes WHERE node_id = ?", (drop,)
            ).fetchone()
        if dropped is None:
            raise KeyError(f"node to drop not found: {drop!r}")
        merge_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO merges VALUES (?, ?, ?, ?, ?, ?)",
                (merge_id, keep, drop, reason, json.dumps(dict(dropped)), now),
            )
            self._conn.execute("UPDATE nodes SET valid_to = ? WHERE node_id = ?", (now, drop))
            self._conn.execute(
                "UPDATE edges SET valid_to = ? WHERE src = ? OR dst = ?", (now, drop, drop)
            )
        return merge_id

    def close_valid_at_sha(self, sha: str) -> None:
        """Close live code-layer rows at *sha* before re-extraction (incremental by sha)."""
        now = datetime.now(tz=UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """UPDATE nodes SET valid_to_sha = ?, valid_to = ?
                   WHERE layer = 'code' AND valid_to IS NULL AND valid_to_sha IS NULL
                     AND (valid_from_sha IS NULL OR valid_from_sha != ?)""",
                (sha, now, sha),
            )
            self._conn.execute(
                """UPDATE edges SET valid_to_sha = ?, valid_to = ?
                   WHERE valid_to IS NULL AND valid_to_sha IS NULL
                     AND src IN (SELECT node_id FROM nodes WHERE layer = 'code')
                     AND (valid_from_sha IS NULL OR valid_from_sha != ?)""",
                (sha, now, sha),
            )

    def record_candidate_relation(
        self,
        *,
        predicate: str,
        src_kind: str,
        dst_kind: str,
        evidence: str,
        count: int = 1,
    ) -> None:
        """Accumulate an unmodelled relation for ontology drift review (§7.4.3)."""
        now = datetime.now(tz=UTC).isoformat()
        relation_id = f"{predicate}:{src_kind}:{dst_kind}"
        with self._conn:
            row = self._conn.execute(
                "SELECT relation_id, count FROM candidate_relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """INSERT INTO candidate_relations (
                           relation_id, predicate, src_kind, dst_kind, count,
                           evidence, first_seen, last_seen
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (relation_id, predicate, src_kind, dst_kind, count, evidence, now, now),
                )
            else:
                self._conn.execute(
                    """UPDATE candidate_relations
                          SET count = count + ?, evidence = ?, last_seen = ?
                        WHERE relation_id = ?""",
                    (count, evidence, now, relation_id),
                )

    def list_candidate_relations(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_relations ORDER BY count DESC, predicate"
        ).fetchall()
        return [dict(r) for r in rows]

    def unmerge(self, merge_id: str) -> None:
        row = self._conn.execute(
            "SELECT payload, dropped FROM merges WHERE merge_id = ?", (merge_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"merge not found: {merge_id!r}")
        payload = json.loads(str(row["payload"]))
        dropped_id = str(row["dropped"])
        with self._conn:
            self._conn.execute(
                """INSERT INTO nodes (
                       node_id, layer, kind, natural_key, repo, props,
                       source, evidence, extractor, extractor_version,
                       confidence, extracted_at,
                       valid_from_sha, valid_to_sha, valid_from, valid_to, merged_from
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(node_id) DO UPDATE SET valid_to = NULL""",
                (
                    payload["node_id"],
                    payload["layer"],
                    payload["kind"],
                    payload["natural_key"],
                    payload.get("repo"),
                    payload.get("props", "{}"),
                    payload["source"],
                    payload.get("evidence"),
                    payload["extractor"],
                    payload["extractor_version"],
                    payload["confidence"],
                    payload["extracted_at"],
                    payload.get("valid_from_sha"),
                    payload.get("valid_to_sha"),
                    payload.get("valid_from"),
                    None,
                    payload.get("merged_from"),
                ),
            )
            self._conn.execute("DELETE FROM merges WHERE merge_id = ?", (merge_id,))
        if self.get(dropped_id) is None:
            raise RuntimeError(f"unmerge failed to restore {dropped_id!r}")

    def _ensure_merge_node(self, node_id: str) -> None:
        if self.get(node_id) is not None:
            return
        parts = node_id.split(":", 2)
        if len(parts) != 3:
            raise KeyError(f"invalid node_id: {node_id!r}")
        layer, kind, natural_key = parts
        now = datetime.now(tz=UTC).isoformat()
        self.upsert_nodes(
            [
                NodeInput(
                    node_id=node_id,
                    layer=layer,
                    kind=kind,
                    natural_key=natural_key,
                    repo="tripll",
                    props="{}",
                    source="merge",
                    evidence=node_id,
                    extractor="tripll.graphstore",
                    extractor_version="0.1.0",
                    confidence=1.0,
                    extracted_at=now,
                )
            ]
        )
