"""Optional NetworkX replica — accelerates ``paths()`` when the ``kg`` extra is installed."""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Any

from tripll.graphstore import Edge, EdgeInput, GraphStore, NodeInput, PathResult, Subgraph

if TYPE_CHECKING:
    from tripll.graphstore.sqlite_store import SqliteGraphStore


def networkx_available() -> bool:
    """Return True when ``networkx`` is importable."""
    return importlib.util.find_spec("networkx") is not None


class NetworkXReplica:
    """In-memory replica rebuilt from a :class:`SqliteGraphStore`."""

    def __init__(self, store: SqliteGraphStore) -> None:
        if not networkx_available():
            raise ImportError("networkx is not installed — install tripll with the kg extra")
        import networkx as nx

        self._nx = nx
        self._graph: nx.DiGraph = nx.DiGraph()
        self.rebuild(store)

    def rebuild(self, store: SqliteGraphStore) -> None:
        self._graph.clear()
        for row in store.conn.execute(
            "SELECT node_id, kind FROM nodes WHERE valid_to IS NULL"
        ).fetchall():
            self._graph.add_node(str(row["node_id"]), kind=str(row["kind"]))
        for row in store.conn.execute(
            "SELECT src, dst, predicate FROM edges WHERE valid_to IS NULL"
        ).fetchall():
            self._graph.add_edge(str(row["src"]), str(row["dst"]), predicate=str(row["predicate"]))

    def paths(
        self,
        src: str,
        dst: str,
        *,
        max_depth: int = 3,
        predicates: list[str] | None = None,
    ) -> list[PathResult]:
        if src not in self._graph or dst not in self._graph:
            return []
        pred_set = set(predicates) if predicates else None
        results: list[PathResult] = []
        for path in self._nx.all_simple_edge_paths(self._graph, src, dst, cutoff=max_depth):
            if pred_set is not None:
                edge_preds = [self._graph.edges[u, v].get("predicate", "") for u, v in path]
                if not all(p in pred_set for p in edge_preds):
                    continue
            node_ids = [src, *(v for _, v in path)]
            results.append(PathResult(nodes=[], depth=len(path), path=">".join(node_ids)))
        return results


class ReplicaGraphStore:
    """Wrap a store; delegate ``paths()`` to NetworkX when installed and ``at_sha`` is unset."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store
        self._replica: NetworkXReplica | None = None
        if networkx_available() and hasattr(store, "conn"):
            self._replica = NetworkXReplica(store)  # type: ignore[arg-type]

    def upsert_nodes(self, nodes: list[NodeInput]) -> None:
        self._store.upsert_nodes(nodes)
        self._maybe_rebuild()

    def upsert_edges(self, edges: list[EdgeInput]) -> None:
        self._store.upsert_edges(edges)
        self._maybe_rebuild()

    def get(self, node_id: str) -> Any:
        return self._store.get(node_id)

    def neighbors(self, node_id: str, **kwargs: Any) -> list[Edge]:
        return self._store.neighbors(node_id, **kwargs)

    def paths(self, src: str, dst: str, **kwargs: Any) -> list[PathResult]:
        if self._replica is not None and kwargs.get("at_sha") is None:
            return self._replica.paths(src, dst, **kwargs)
        return self._store.paths(src, dst, **kwargs)

    def subgraph(self, seeds: list[str], **kwargs: Any) -> Subgraph:
        return self._store.subgraph(seeds, **kwargs)

    def snapshot(self, label: str) -> str:
        return self._store.snapshot(label)

    def merge(self, keep: str, drop: str, *, reason: str) -> str:
        merge_id = self._store.merge(keep, drop, reason=reason)
        self._maybe_rebuild()
        return merge_id

    def unmerge(self, merge_id: str) -> None:
        self._store.unmerge(merge_id)
        self._maybe_rebuild()

    def _maybe_rebuild(self) -> None:
        if self._replica is not None and hasattr(self._store, "conn"):
            self._replica.rebuild(self._store)  # type: ignore[arg-type]
