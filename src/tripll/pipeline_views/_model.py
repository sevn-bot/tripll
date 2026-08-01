"""tripll.pipeline_views._model — the renderable view a pipeline chart is built from.

A view is the geometry-free description of one chart: placed nodes, directed
edges, cluster boxes, and the popup content each node carries. Both charts are
derived into this shape, so layout and rendering never read a pipeline file.

Exports:
    DetailCard — one agent note inside a node popup.
    NodeDetail — popup content for one node.
    ViewNode — one placed node in a rendered view.
    ViewEdge — one directed edge between nodes.
    ViewCluster — labelled container drawn around member nodes.
    PipelineView — a renderable view derived from a pipeline spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from tripll.pipeline_spec import Answer, StepKind, TransitionStyle

__all__ = [
    "DetailCard",
    "NodeDetail",
    "PipelineView",
    "ViewCluster",
    "ViewEdge",
    "ViewNode",
]

_KIND_LABELS: dict[StepKind, str] = {
    "gate": "Human / gate",
    "phase": "System phase",
    "agent": "Agent",
    "artifact": "Artifact / state",
    "external": "External input",
}

_STYLE_LABELS: dict[TransitionStyle, str] = {
    "primary": "Primary flow",
    "conditional": "Conditional / feedback",
    "optional": "Optional / side path",
}


@dataclass(frozen=True)
class DetailCard:
    """One agent note inside a node popup.

    Args:
        name (str): Agent or step name.
        summary (str): What the agent does at this point in the pipeline.
        facts (tuple[tuple[str, str], ...]): Label/value rows (harness, model, …).
        params (tuple[tuple[str, str], ...]): Declared parameters.
    """

    name: str
    summary: str = ""
    facts: tuple[tuple[str, str], ...] = ()
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class NodeDetail:
    """Popup content for one node.

    Args:
        summary (str): Prose shown under the node title.
        facts (tuple[tuple[str, str], ...]): Label/value rows for the node itself.
        params (tuple[tuple[str, str], ...]): Declared parameters of the node.
        cards (tuple[DetailCard, ...]): Agent notes (used by the state view, where
            the node is a state and the agents sit on its incoming edges).
    """

    summary: str = ""
    facts: tuple[tuple[str, str], ...] = ()
    params: tuple[tuple[str, str], ...] = ()
    cards: tuple[DetailCard, ...] = ()

    def is_empty(self) -> bool:
        """Return True when there is nothing worth opening a popup for.

        Returns:
            bool: True if no summary, facts, params, or cards are set.

        Examples:
            >>> NodeDetail().is_empty()
            True
            >>> NodeDetail(summary="does a thing").is_empty()
            False
        """
        return not (self.summary or self.facts or self.params or self.cards)


@dataclass(frozen=True)
class ViewNode:
    """One placed node.

    Args:
        node_id (str): Unique id referenced by edges and clusters.
        label (str): Primary label line.
        kind (StepKind): Visual class.
        layer (int): Row index, top to bottom.
        column (float): Column index (fractional allowed for offsets).
        note (str): Optional second label line.
        detail (NodeDetail | None): Popup content, or None when the node has none.
    """

    node_id: str
    label: str
    kind: StepKind
    layer: int
    column: float
    note: str = ""
    detail: NodeDetail | None = None


@dataclass(frozen=True)
class ViewEdge:
    """One directed edge.

    Args:
        source (str): Source node id.
        target (str): Target node id.
        label (str): Primary edge label.
        note (str): Optional second label line.
        detail (str): Prose shown on hover; explains the flow across this edge.
        style (TransitionStyle): Visual class.
        answer (Answer): Decision arm — ``yes`` or ``no`` — drawn as a pass/fail
            badge on the edge label, or empty when the edge is not a branch.
        bow (Literal["auto", "left", "right"]): Side channel for edges that run
            back to an earlier layer.
    """

    source: str
    target: str
    label: str = ""
    note: str = ""
    detail: str = ""
    style: TransitionStyle = "primary"
    answer: Answer = ""
    bow: Literal["auto", "left", "right"] = "auto"


@dataclass(frozen=True)
class ViewCluster:
    """Labelled container drawn around a set of nodes.

    Args:
        label (str): Cluster heading.
        members (tuple[str, ...]): Node ids enclosed by the box.
    """

    label: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class PipelineView:
    """A renderable view derived from a pipeline spec.

    Args:
        view_id (str): Stable id used for the CLI argument and filenames.
        title (str): Document heading.
        subtitle (str): One-line description of what nodes and edges mean.
        nodes (tuple[ViewNode, ...]): Placed nodes.
        edges (tuple[ViewEdge, ...]): Directed edges.
        clusters (tuple[ViewCluster, ...]): Grouping boxes.
        source (str): Pipeline file the view came from.
        col_pitch (int): Horizontal distance between columns.
        row_pitch (int): Vertical distance between layers.
    """

    view_id: str
    title: str
    subtitle: str
    nodes: tuple[ViewNode, ...]
    edges: tuple[ViewEdge, ...]
    clusters: tuple[ViewCluster, ...] = ()
    source: str = ""
    col_pitch: int = 248
    row_pitch: int = 152

    def node_map(self) -> dict[str, ViewNode]:
        """Return node_id → node.

        Returns:
            dict[str, ViewNode]: Lookup for edge and cluster resolution.

        Examples:
            >>> PipelineView("v", "t", "s", (ViewNode("a", "A", "agent", 0, 0),), ()).node_map()["a"].label
            'A'
        """
        return {node.node_id: node for node in self.nodes}

    def validate(self) -> list[str]:
        """Return view errors (empty list = valid).

        Checks duplicate node ids, edges referencing unknown nodes, self-edges,
        and nodes sharing one grid cell.

        Returns:
            list[str]: Human-readable error strings.

        Examples:
            >>> PipelineView("v", "t", "s", (ViewNode("a", "A", "agent", 0, 0),), ()).validate()
            []
        """
        errors: list[str] = []
        seen: set[str] = set()
        for node in self.nodes:
            if node.node_id in seen:
                errors.append(f"duplicate node id: {node.node_id}")
            seen.add(node.node_id)
        cells: dict[tuple[int, float], str] = {}
        for node in self.nodes:
            cell = (node.layer, node.column)
            if cell in cells:
                errors.append(f"cell collision at {cell}: {cells[cell]} and {node.node_id}")
            cells[cell] = node.node_id
        for edge in self.edges:
            for side, ref in (("source", edge.source), ("target", edge.target)):
                if ref not in seen:
                    errors.append(f"edge {side} references unknown node: {ref}")
            if edge.source == edge.target:
                errors.append(f"self-edge on {edge.source}")
        return errors
