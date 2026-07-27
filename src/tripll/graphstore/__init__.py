"""GraphStore port — SQLite of record with optional NetworkX replica."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

NodeInput = dict[str, Any]
EdgeInput = dict[str, Any]


_PROVENANCE_KEYS = (
    "source",
    "extractor",
    "extractor_version",
    "confidence",
    "extracted_at",
)


def validate_provenance(record: NodeInput | EdgeInput, *, label: str) -> None:
    """Raise when mandatory provenance columns are missing."""
    missing = [key for key in _PROVENANCE_KEYS if key not in record]
    if missing:
        raise ValueError(f"{label} missing required provenance fields: {', '.join(missing)}")


@dataclass(frozen=True, slots=True)
class Node:
    node_id: str
    layer: str
    kind: str
    natural_key: str
    repo: str | None
    props: str
    source: str
    evidence: str | None
    extractor: str
    extractor_version: str
    confidence: float
    extracted_at: str
    valid_from_sha: str | None = None
    valid_to_sha: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    merged_from: str | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    edge_id: str
    predicate: str
    src: str
    dst: str
    props: str
    reason: str | None
    source: str
    evidence: str | None
    extractor: str
    extractor_version: str
    confidence: float
    extracted_at: str
    valid_from_sha: str | None = None
    valid_to_sha: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    merged_from: str | None = None


@dataclass(frozen=True, slots=True)
class PathResult:
    nodes: list[Node]
    depth: int
    path: str


@dataclass
class Subgraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


@runtime_checkable
class GraphStore(Protocol):
    def upsert_nodes(self, nodes: list[NodeInput]) -> None: ...
    def upsert_edges(self, edges: list[EdgeInput]) -> None: ...
    def get(self, node_id: str) -> Node | None: ...
    def neighbors(
        self,
        node_id: str,
        *,
        predicates: list[str] | None = None,
        direction: Literal["out", "in", "both"] = "out",
        at_sha: str | None = None,
    ) -> list[Edge]: ...
    def paths(
        self,
        src: str,
        dst: str,
        *,
        max_depth: int = 3,
        predicates: list[str] | None = None,
        at_sha: str | None = None,
    ) -> list[PathResult]: ...
    def subgraph(
        self,
        seeds: list[str],
        *,
        hops: int = 2,
        predicates: list[str] | None = None,
        at_sha: str | None = None,
    ) -> Subgraph: ...
    def snapshot(self, label: str) -> str: ...
    def merge(self, keep: str, drop: str, *, reason: str) -> str: ...
    def unmerge(self, merge_id: str) -> None: ...


from tripll.graphstore.sqlite_store import SqliteGraphStore  # noqa: E402

__all__ = [
    "Edge",
    "EdgeInput",
    "GraphStore",
    "Node",
    "NodeInput",
    "PathResult",
    "SqliteGraphStore",
    "Subgraph",
    "validate_provenance",
]
