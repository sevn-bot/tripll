"""tripll.pipeline_views — render pipeline files as self-contained HTML graphs.

Given a :class:`~tripll.pipeline_spec.PipelineSpec` (loaded from a
``pipeline_format = 1`` file), this module derives two complementary charts:

* **execution** — steps are nodes (agents, system phases, human gates) and the
  declared transitions are edges, including retry loops and feedback paths.
* **state** — the artifact states are nodes and every edge is the step work that
  moves the pipeline from one state to the next.

Placement comes from the file when it supplies ``layer`` / ``column``, and is
derived from the transitions otherwise. Edges are routed by geometry: forward
edges run down or right, same-layer feedback edges dip below their row, long
same-layer edges arc above it, and edges back to an earlier layer bow out
through a side channel.

The rendered document is a single offline file: inline CSS and one inline script
give it zoom controls, a node popup carrying each agent's note (summary, harness,
model, params), and an edge tooltip explaining the flow.

Exports:
    DetailCard — one agent note inside a node popup.
    NodeDetail — popup content for one node.
    ViewNode — one placed node in a rendered view.
    ViewEdge — one directed edge between nodes.
    ViewCluster — labelled container drawn around member nodes.
    PipelineView — a renderable view derived from a pipeline spec.
    execution_view — build the step/control-transition view.
    state_view — build the state view whose edges are step work.
    VIEWS — view id → builder map.
    render_view_html — self-contained HTML document for one view.
    write_view_html — render one view and write it to disk.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path

    from tripll.pipeline_spec import (
        PipelineSpec,
        State,
        Step,
        StepKind,
        Transition,
        TransitionStyle,
    )

__all__ = [
    "VIEWS",
    "DetailCard",
    "NodeDetail",
    "PipelineView",
    "ViewCluster",
    "ViewEdge",
    "ViewNode",
    "execution_view",
    "render_view_html",
    "state_view",
    "write_view_html",
]

NODE_W = 172
NODE_H = 56
MARGIN = 28
CHANNEL = 104
DIP_BASE = 32
DIP_STEP = 26
#: Same-layer edges wider than this many columns arc above the row.
ARC_SPAN = 1.6

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
        bow (Literal["auto", "left", "right"]): Side channel for edges that run
            back to an earlier layer.
    """

    source: str
    target: str
    label: str = ""
    note: str = ""
    detail: str = ""
    style: TransitionStyle = "primary"
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
    col_pitch: int = 232
    row_pitch: int = 148

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


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


def _back_edges(order: Sequence[str], edges: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    """Return edges that close a cycle, found by DFS in declaration order."""
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in order}
    for source, target in edges:
        adjacency.setdefault(source, []).append(target)
    back: set[tuple[str, str]] = set()
    state: dict[str, int] = dict.fromkeys(order, 0)

    def visit(node_id: str) -> None:
        state[node_id] = 1
        for target in adjacency.get(node_id, []):
            if state.get(target, 0) == 1:
                back.add((node_id, target))
            elif state.get(target, 0) == 0:
                visit(target)
        state[node_id] = 2

    for node_id in order:
        if state.get(node_id, 0) == 0:
            visit(node_id)
    return back


def _derive_placement(
    order: Sequence[str],
    edges: Iterable[tuple[str, str]],
) -> dict[str, tuple[int, float]]:
    """Assign (layer, column) by longest path, ignoring cycle-closing edges.

    Args:
        order (Sequence[str]): Node ids in declaration order.
        edges (Iterable[tuple[str, str]]): Directed ``(source, target)`` pairs.

    Returns:
        dict[str, tuple[int, float]]: node_id → (layer, column).

    Examples:
        >>> _derive_placement(["a", "b"], [("a", "b")])
        {'a': (0, 0.0), 'b': (1, 0.0)}
    """
    pairs = list(edges)
    back = _back_edges(order, pairs)
    forward = [pair for pair in pairs if pair not in back]
    layer = dict.fromkeys(order, 0)
    for _ in range(len(order)):
        changed = False
        for source, target in forward:
            candidate = layer[source] + 1
            if candidate > layer.get(target, 0):
                layer[target] = candidate
                changed = True
        if not changed:
            break
    used: dict[int, int] = {}
    placement: dict[str, tuple[int, float]] = {}
    for node_id in order:
        row = layer[node_id]
        column = used.get(row, 0)
        used[row] = column + 1
        placement[node_id] = (row, float(column))
    return placement


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass
class _Geometry:
    """Pixel geometry for one view."""

    view: PipelineView
    x: dict[str, int] = field(default_factory=dict)
    y: dict[str, int] = field(default_factory=dict)
    width: int = 0
    height: int = 0

    def centre_x(self, node_id: str) -> int:
        return self.x[node_id] + NODE_W // 2

    def centre_y(self, node_id: str) -> int:
        return self.y[node_id] + NODE_H // 2


def _bow_side(edge: ViewEdge, source: ViewNode, target: ViewNode) -> Literal["left", "right"]:
    """Return the side channel an edge to an earlier layer should bow through."""
    if edge.bow != "auto":
        return edge.bow
    return "left" if target.column <= source.column else "right"


def _needs_channel(view: PipelineView) -> tuple[bool, bool]:
    """Return whether the (left, right) side channels are used."""
    nodes = view.node_map()
    left = right = False
    for edge in view.edges:
        source, target = nodes[edge.source], nodes[edge.target]
        if target.layer < source.layer:
            if _bow_side(edge, source, target) == "right":
                right = True
            else:
                left = True
    return left, right


def _geometry(view: PipelineView) -> _Geometry:
    left_channel, right_channel = _needs_channel(view)
    pad_left = MARGIN + (CHANNEL if left_channel else 0)
    pad_right = MARGIN + (CHANNEL if right_channel else 0)
    geo = _Geometry(view=view)
    for node in view.nodes:
        geo.x[node.node_id] = int(pad_left + node.column * view.col_pitch)
        geo.y[node.node_id] = MARGIN + node.layer * view.row_pitch
    max_column = max((node.column for node in view.nodes), default=0)
    max_layer = max((node.layer for node in view.nodes), default=0)
    geo.width = int(pad_left + max_column * view.col_pitch + NODE_W + pad_right)
    geo.height = MARGIN + max_layer * view.row_pitch + NODE_H + MARGIN + DIP_BASE
    return geo


def _dip_depths(view: PipelineView) -> dict[tuple[str, str], int]:
    """Stagger same-layer backward edges so their dips do not overlap."""
    nodes = view.node_map()
    per_layer: dict[int, int] = {}
    depths: dict[tuple[str, str], int] = {}
    for edge in view.edges:
        source, target = nodes[edge.source], nodes[edge.target]
        if target.layer == source.layer and target.column < source.column:
            index = per_layer.get(source.layer, 0)
            depths[edge.source, edge.target] = DIP_BASE + index * DIP_STEP
            per_layer[source.layer] = index + 1
    return depths


@dataclass(frozen=True)
class _EdgeGeom:
    """Resolved SVG path plus label anchor for one edge."""

    path: str
    label_x: int
    label_y: int


def _edge_geometry(
    edge: ViewEdge,
    geo: _Geometry,
    dips: dict[tuple[str, str], int],
) -> _EdgeGeom:
    nodes = geo.view.node_map()
    source, target = nodes[edge.source], nodes[edge.target]
    ax, ay = geo.x[edge.source], geo.y[edge.source]
    bx, by = geo.x[edge.target], geo.y[edge.target]

    if target.layer > source.layer:
        x1, y1 = geo.centre_x(edge.source), ay + NODE_H
        x2, y2 = geo.centre_x(edge.target), by
        mid = (y1 + y2) // 2
        return _EdgeGeom(
            path=f"M {x1} {y1} C {x1} {mid}, {x2} {mid}, {x2} {y2}",
            label_x=(x1 + x2) // 2,
            label_y=mid - 6,
        )

    if target.layer == source.layer and target.column > source.column:
        if target.column - source.column > ARC_SPAN:
            x1, x2 = geo.centre_x(edge.source), geo.centre_x(edge.target)
            y_top = ay
            y_arc = y_top - DIP_BASE
            return _EdgeGeom(
                path=f"M {x1} {y_top} C {x1} {y_arc}, {x2} {y_arc}, {x2} {y_top}",
                label_x=(x1 + x2) // 2,
                label_y=y_arc + 2,
            )
        y_mid = geo.centre_y(edge.source)
        x1, x2 = ax + NODE_W, bx
        return _EdgeGeom(
            path=f"M {x1} {y_mid} L {x2} {y_mid}",
            label_x=(x1 + x2) // 2,
            label_y=y_mid - 9,
        )

    if target.layer == source.layer:
        dip = dips[edge.source, edge.target]
        y_row = ay + NODE_H
        y_dip = y_row + dip
        x1, x2 = geo.centre_x(edge.source), geo.centre_x(edge.target)
        return _EdgeGeom(
            path=f"M {x1} {y_row} C {x1} {y_dip}, {x2} {y_dip}, {x2} {y_row}",
            label_x=(x1 + x2) // 2,
            label_y=y_dip - 2,
        )

    y1, y2 = geo.centre_y(edge.source), geo.centre_y(edge.target)
    if _bow_side(edge, source, target) == "right":
        x1, x2 = ax + NODE_W, bx + NODE_W
        bow = max(x1, x2) + CHANNEL - 24
        label_x = bow - 4
    else:
        x1, x2 = ax, bx
        bow = min(x1, x2) - CHANNEL + 24
        label_x = bow + 4
    return _EdgeGeom(
        path=f"M {x1} {y1} C {bow} {y1}, {bow} {y2}, {x2} {y2}",
        label_x=label_x,
        label_y=(y1 + y2) // 2,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_clusters(view: PipelineView, geo: _Geometry) -> list[str]:
    parts: list[str] = []
    pad = 18
    for cluster in view.clusters:
        members = [m for m in cluster.members if m in geo.x]
        if not members:
            continue
        xs = [geo.x[m] for m in members]
        ys = [geo.y[m] for m in members]
        x = min(xs) - pad
        y = min(ys) - pad - 14
        width = max(xs) + NODE_W + pad - x
        height = max(ys) + NODE_H + pad - y
        parts.extend(
            [
                '<g class="cluster">',
                f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12"></rect>',
                f'<text x="{x + 12}" y="{y + 18}">{html.escape(cluster.label)}</text>',
                "</g>",
            ]
        )
    return parts


def _render_edges(view: PipelineView, geo: _Geometry) -> list[str]:
    dips = _dip_depths(view)
    nodes = view.node_map()
    parts: list[str] = []
    for index, edge in enumerate(view.edges):
        eg = _edge_geometry(edge, geo, dips)
        title = f"{nodes[edge.source].label} → {nodes[edge.target].label}"
        if edge.label:
            title += f" · {edge.label}"
        if edge.detail:
            title += f"\n{edge.detail}"
        parts.append(
            f'<path class="edge edge-{edge.style}" data-edge="{index}" d="{eg.path}" '
            f'marker-end="url(#arrow-{edge.style})">'
            f"<title>{html.escape(title)}</title></path>"
        )
        if edge.label:
            parts.append(
                f'<text class="elabel" x="{eg.label_x}" y="{eg.label_y}">'
                f"{html.escape(edge.label)}</text>"
            )
        if edge.note:
            offset = eg.label_y + (13 if edge.label else 4)
            parts.append(
                f'<text class="enote" x="{eg.label_x}" y="{offset}">{html.escape(edge.note)}</text>'
            )
    return parts


#: Labels longer than this wrap onto a second line at a hyphen.
_LABEL_WRAP = 18


def _wrap_label(label: str) -> tuple[str, ...]:
    """Split a long hyphenated label onto two lines at the most central hyphen.

    Args:
        label (str): Node label, typically an agent id such as ``check-fixer``.

    Returns:
        tuple[str, ...]: One or two lines; the first keeps its trailing hyphen.

    Examples:
        >>> _wrap_label("check-fixer")
        ('check-fixer',)
        >>> _wrap_label("post-review-wave-generator")
        ('post-review-', 'wave-generator')
    """
    if len(label) <= _LABEL_WRAP:
        return (label,)
    cuts = [i for i, char in enumerate(label) if char == "-"]
    if not cuts:
        return (label,)
    middle = len(label) / 2
    best = min(cuts, key=lambda i: (abs(i - middle), -i))
    return (label[: best + 1], label[best + 1 :])


#: Baseline offsets keyed by (label line count, has note).
_TEXT_ROWS: dict[tuple[int, bool], tuple[int, ...]] = {
    (1, False): (34,),
    (1, True): (26, 42),
    (2, False): (25, 40),
    (2, True): (21, 35, 48),
}


def _render_nodes(view: PipelineView, geo: _Geometry) -> list[str]:
    parts: list[str] = []
    for node in view.nodes:
        x, y = geo.x[node.node_id], geo.y[node.node_id]
        lines = _wrap_label(node.label)
        rows = _TEXT_ROWS[len(lines), bool(node.note)]
        centre = x + NODE_W // 2
        openable = node.detail is not None and not node.detail.is_empty()
        classes = f"node node-{node.kind}" + (" node-open" if openable else "")
        attrs = f' data-node="{html.escape(node.node_id, quote=True)}"' if openable else ""
        hint = " · click for details" if openable else ""
        parts.extend(
            [
                f'<g class="{classes}"{attrs}>',
                f"<title>{html.escape(node.node_id + hint)}</title>",
                f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="9"></rect>',
            ]
        )
        parts.extend(
            f'<text class="nlabel" x="{centre}" y="{y + rows[index]}">{html.escape(line)}</text>'
            for index, line in enumerate(lines)
        )
        if node.note:
            parts.append(
                f'<text class="nnote" x="{centre}" y="{y + rows[len(lines)]}">'
                f"{html.escape(node.note)}</text>"
            )
        parts.append("</g>")
    return parts


_STYLE = [
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:24px;"
    "background:#faf9f7;color:#1a1a1a}",
    "h1{font-size:1.35rem;margin:0 0 4px}",
    ".sub{color:#555;font-size:.92rem;margin:0 0 14px}",
    ".legend{display:flex;gap:18px;flex-wrap:wrap;font-size:.8rem;color:#444;"
    "margin:0 0 16px;align-items:center}",
    ".swatch{display:inline-block;width:11px;height:11px;border-radius:3px;"
    "margin-right:6px;vertical-align:middle}",
    ".swatch-gate{background:#fde8b0;border:1px solid #d79b0a}",
    ".swatch-phase{background:#e6dcf7;border:1px solid #8a6ec4}",
    ".swatch-agent{background:#dff0d8;border:1px solid #5f9e4e}",
    ".swatch-artifact{background:#dce8f8;border:1px solid #5f86c4}",
    ".swatch-external{background:#e4e4e2;border:1px solid #9a978f}",
    ".line{display:inline-block;width:26px;margin-right:6px;vertical-align:middle;"
    "border-top:2px solid #6f6a5e}",
    ".line-conditional{border-top-style:dashed}",
    ".line-optional{border-top-style:dotted}",
    ".bar{display:flex;gap:8px;align-items:center;margin:0 0 10px}",
    ".bar button{font:inherit;font-size:.82rem;padding:4px 11px;border-radius:7px;"
    "border:1px solid #d9d4c8;background:#fff;color:#2c2a24;cursor:pointer}",
    ".bar button:hover{background:#f2efe8}",
    ".bar .level{font-size:.8rem;color:#6f6a5e;min-width:46px}",
    ".bar .hint{font-size:.78rem;color:#8a8577}",
    ".canvas{overflow:auto;background:#fff;border:1px solid #e6e2d9;border-radius:12px}",
    ".graph{max-width:100%;height:auto;display:block}",
    ".cluster rect{fill:#f4f2ee;stroke:#ddd8cc;stroke-width:1}",
    ".cluster text{font-size:11px;fill:#6f6a5e;letter-spacing:.09em;text-transform:uppercase}",
    ".node rect{fill:#fff;stroke:#111;stroke-width:1.5}",
    ".node-gate rect{fill:#fde8b0;stroke:#d79b0a}",
    ".node-phase rect{fill:#e6dcf7;stroke:#8a6ec4}",
    ".node-agent rect{fill:#dff0d8;stroke:#5f9e4e}",
    ".node-artifact rect{fill:#dce8f8;stroke:#5f86c4}",
    ".node-external rect{fill:#e4e4e2;stroke:#9a978f}",
    "text{font-family:ui-sans-serif,system-ui,sans-serif}",
    ".nlabel{font-size:12.5px;font-weight:600;text-anchor:middle}",
    ".nnote{font-size:10.5px;fill:#555;text-anchor:middle}",
    ".edge{fill:none;stroke:#6f6a5e;stroke-width:1.6}",
    ".edge-conditional{stroke-dasharray:6 4;stroke:#8a8577}",
    ".edge-optional{stroke-dasharray:2 4;stroke:#9a978f}",
    ".elabel,.enote{text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:3px;"
    "stroke-linejoin:round}",
    ".elabel{font-size:10.5px;font-weight:600;fill:#2c2a24}",
    ".enote{font-size:10px;fill:#6f6a5e}",
    ".node-open{cursor:pointer}",
    ".node-open:hover rect{stroke-width:2.5}",
    "[data-edge]:hover{stroke:#2c2a24;stroke-width:2.6}",
    "#tip{position:fixed;z-index:20;max-width:320px;padding:9px 11px;border-radius:9px;"
    "background:#2c2a24;color:#f7f5f0;font-size:.78rem;line-height:1.42;"
    "box-shadow:0 6px 22px rgba(0,0,0,.28);pointer-events:none}",
    "#tip b{display:block;font-size:.8rem;margin-bottom:2px}",
    "#tip .cond{color:#f3d38a}",
    "#tip .flow{margin-top:5px;color:#e2ded4}",
    "#sheet[hidden],#tip[hidden]{display:none}",
    "#sheet{position:fixed;inset:0;z-index:30;display:flex;align-items:center;"
    "justify-content:center;padding:24px;background:rgba(28,26,22,.42)}",
    "#sheet .card{position:relative;width:min(560px,100%);max-height:82vh;overflow:auto;"
    "background:#fff;border:1px solid #e6e2d9;border-radius:16px;padding:22px 24px;"
    "box-shadow:0 18px 48px rgba(0,0,0,.22)}",
    "#sheet h2{font-size:1.12rem;margin:0 6px 6px 0;display:inline-block}",
    "#sheet .badge{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;"
    "padding:3px 8px;border-radius:99px;border:1px solid #d9d4c8;color:#6f6a5e;"
    "vertical-align:2px}",
    "#sheet .lede{margin:10px 0 0;font-size:.9rem;line-height:1.55;color:#3b3830}",
    "#sheet .rows{display:grid;grid-template-columns:auto 1fr;gap:5px 14px;"
    "margin:14px 0 0;font-size:.84rem}",
    "#sheet .rows dt{color:#6f6a5e}",
    "#sheet .rows dd{margin:0;color:#2c2a24;font-weight:500}",
    "#sheet .group{margin:16px 0 0;font-size:.7rem;letter-spacing:.09em;"
    "text-transform:uppercase;color:#8a8577}",
    "#sheet .agent{margin:14px 0 0;padding:13px 15px;border:1px solid #ece8df;"
    "border-radius:11px;background:#faf9f7}",
    "#sheet .agent h3{margin:0;font-size:.93rem}",
    "#sheet .agent .lede{margin:6px 0 0;font-size:.85rem}",
    "#sheet .close{position:absolute;top:14px;right:14px;font:inherit;font-size:1rem;"
    "line-height:1;padding:5px 9px;border-radius:8px;border:1px solid #e6e2d9;"
    "background:#fff;color:#6f6a5e;cursor:pointer}",
    "#sheet .close:hover{background:#f2efe8}",
    "code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.95em}",
]

_SCRIPT = """
const DATA = __DATA__;
const svg = document.getElementById('graph');
const level = document.getElementById('zoom-level');
const tip = document.getElementById('tip');
const sheet = document.getElementById('sheet');
const card = document.getElementById('sheet-card');
let zoom = 1;

function applyZoom() {
  svg.style.width = zoom === 1 ? '' : (DATA.width * zoom) + 'px';
  svg.style.maxWidth = zoom === 1 ? '100%' : 'none';
  level.textContent = Math.round(zoom * 100) + '%';
}
function step(by) { zoom = Math.min(4, Math.max(0.4, Math.round((zoom + by) * 100) / 100)); applyZoom(); }
document.getElementById('zoom-in').addEventListener('click', () => step(0.25));
document.getElementById('zoom-out').addEventListener('click', () => step(-0.25));
document.getElementById('zoom-fit').addEventListener('click', () => { zoom = 1; applyZoom(); });

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text) node.textContent = text;
  return node;
}
function rows(pairs) {
  const dl = el('dl', 'rows');
  for (const [key, value] of pairs) {
    dl.append(el('dt', '', key), el('dd', '', value));
  }
  return dl;
}
function agentBlock(agent) {
  const box = el('div', 'agent');
  box.append(el('h3', '', agent.name));
  if (agent.summary) box.append(el('p', 'lede', agent.summary));
  if (agent.facts.length) box.append(rows(agent.facts));
  if (agent.params.length) { box.append(el('p', 'group', 'Params')); box.append(rows(agent.params)); }
  return box;
}
function openNode(id) {
  const detail = DATA.nodes[id];
  if (!detail) return;
  card.replaceChildren();
  const close = el('button', 'close', '\\u00d7');
  close.setAttribute('aria-label', 'Close');
  close.addEventListener('click', hide);
  card.append(close, el('h2', '', detail.label), el('span', 'badge', detail.kind));
  if (detail.summary) card.append(el('p', 'lede', detail.summary));
  if (detail.facts.length) card.append(rows(detail.facts));
  if (detail.params.length) { card.append(el('p', 'group', 'Params')); card.append(rows(detail.params)); }
  if (detail.cards.length) {
    card.append(el('p', 'group', detail.cards.length > 1 ? 'Agents on the incoming edges' : 'Agent'));
    for (const agent of detail.cards) card.append(agentBlock(agent));
  }
  sheet.hidden = false;
}
function hide() { sheet.hidden = true; }
sheet.addEventListener('click', (event) => { if (event.target === sheet) hide(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') hide(); });
for (const node of document.querySelectorAll('[data-node]')) {
  node.addEventListener('click', () => openNode(node.dataset.node));
}

function place(event) {
  const box = tip.getBoundingClientRect();
  const x = Math.min(event.clientX + 16, window.innerWidth - box.width - 12);
  const y = Math.min(event.clientY + 16, window.innerHeight - box.height - 12);
  tip.style.left = Math.max(12, x) + 'px';
  tip.style.top = Math.max(12, y) + 'px';
}
for (const path of document.querySelectorAll('[data-edge]')) {
  const edge = DATA.edges[Number(path.dataset.edge)];
  path.addEventListener('mouseenter', (event) => {
    tip.replaceChildren(el('b', '', edge.from + ' \\u2192 ' + edge.to));
    if (edge.label) tip.append(el('div', 'cond', edge.label));
    if (edge.note) tip.append(el('div', 'cond', edge.note));
    tip.append(el('div', 'flow', edge.detail || DATA.styles[edge.style]));
    tip.hidden = false;
    place(event);
  });
  path.addEventListener('mousemove', place);
  path.addEventListener('mouseleave', () => { tip.hidden = true; });
}
applyZoom();
"""


def _card_payload(card: DetailCard) -> dict[str, object]:
    return {
        "name": card.name,
        "summary": card.summary,
        "facts": [list(pair) for pair in card.facts],
        "params": [list(pair) for pair in card.params],
    }


def _detail_payload(view: PipelineView, width: int) -> str:
    """Serialise node popups, edge tooltips, and canvas width as a JS literal.

    Args:
        view (PipelineView): The view being rendered.
        width (int): Intrinsic SVG width, used as the 100% zoom baseline.

    Returns:
        str: A JSON object literal safe to inline inside a ``<script>`` element.
    """
    nodes = {
        node.node_id: {
            "label": node.label,
            "kind": _KIND_LABELS[node.kind],
            "summary": node.detail.summary,
            "facts": [list(pair) for pair in node.detail.facts],
            "params": [list(pair) for pair in node.detail.params],
            "cards": [_card_payload(card) for card in node.detail.cards],
        }
        for node in view.nodes
        if node.detail is not None and not node.detail.is_empty()
    }
    labels = {node.node_id: node.label for node in view.nodes}
    edges = [
        {
            "from": labels[edge.source],
            "to": labels[edge.target],
            "label": edge.label,
            "note": edge.note,
            "detail": edge.detail,
            "style": edge.style,
        }
        for edge in view.edges
    ]
    payload = {
        "width": width,
        "styles": dict(_STYLE_LABELS),
        "nodes": nodes,
        "edges": edges,
    }
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def render_view_html(view: PipelineView) -> str:
    """Render *view* as a self-contained HTML document with an inline SVG graph.

    Args:
        view (PipelineView): The view to render.

    Returns:
        str: Full HTML document; no scripts and no external asset fetch.

    Raises:
        ValueError: If the view fails :meth:`PipelineView.validate`.

    Examples:
        >>> spec = load_pipeline_spec(Path("p.toml"))  # doctest: +SKIP
        >>> render_view_html(execution_view(spec)).startswith("<!DOCTYPE html>")  # doctest: +SKIP
        True
    """
    errors = view.validate()
    if errors:
        msg = f"invalid view {view.view_id!r}: " + "; ".join(errors)
        raise ValueError(msg)

    geo = _geometry(view)
    kinds = [kind for kind in _KIND_LABELS if any(n.kind == kind for n in view.nodes)]
    styles = [style for style in _STYLE_LABELS if any(e.style == style for e in view.edges)]
    source_note = f" · source={view.source}" if view.source else ""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(view.title)}</title>",
        "<style>",
        *_STYLE,
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{html.escape(view.title)}</h1>",
        f'<p class="sub">{html.escape(view.subtitle)} · '
        f"{len(view.nodes)} nodes · {len(view.edges)} edges"
        f"{html.escape(source_note)}</p>",
        '<div class="legend">',
    ]
    parts.extend(
        f'<span><span class="swatch swatch-{kind}"></span>{html.escape(_KIND_LABELS[kind])}</span>'
        for kind in kinds
    )
    parts.extend(
        f'<span><span class="line line-{style}"></span>{html.escape(_STYLE_LABELS[style])}</span>'
        for style in styles
    )
    parts.extend(
        [
            "</div>",
            '<div class="bar">',
            '<button id="zoom-out" type="button">&minus; Zoom out</button>',
            '<button id="zoom-in" type="button">+ Zoom in</button>',
            '<button id="zoom-fit" type="button">Fit</button>',
            '<span class="level" id="zoom-level">100%</span>',
            '<span class="hint">Click a node for its agent note · hover an edge for the flow'
            "</span>",
            "</div>",
            '<div class="canvas">',
            f'<svg class="graph" id="graph" viewBox="0 0 {geo.width} {geo.height}" '
            f'width="{geo.width}" height="{geo.height}" '
            'xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="{html.escape(view.subtitle)}">',
            "<defs>",
        ]
    )
    for style, colour in (
        ("primary", "#6f6a5e"),
        ("conditional", "#8a8577"),
        ("optional", "#9a978f"),
    ):
        parts.extend(
            [
                f'<marker id="arrow-{style}" viewBox="0 0 10 10" refX="9" refY="5" '
                'markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
                f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{colour}"></path>',
                "</marker>",
            ]
        )
    parts.append("</defs>")
    parts.extend(_render_clusters(view, geo))
    parts.extend(_render_edges(view, geo))
    parts.extend(_render_nodes(view, geo))
    parts.extend(
        [
            "</svg>",
            "</div>",
            '<div id="tip" role="tooltip" hidden></div>',
            '<div id="sheet" role="dialog" aria-modal="true" hidden>',
            '<div class="card" id="sheet-card"></div>',
            "</div>",
            "<script>",
            _SCRIPT.replace("__DATA__", _detail_payload(view, geo.width)),
            "</script>",
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(parts) + "\n"


def write_view_html(view: PipelineView, out_path: Path) -> Path:
    """Render *view* and write the document to *out_path*.

    Args:
        view (PipelineView): The view to render.
        out_path (Path): Destination ``.html`` file (parents created).

    Returns:
        Path: The resolved written path.

    Examples:
        >>> write_view_html(view, Path("/tmp/view.html"))  # doctest: +SKIP
        PosixPath('/tmp/view.html')
    """
    resolved = out_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(render_view_html(view), encoding="utf-8")
    return resolved


# ---------------------------------------------------------------------------
# View 1 — steps are nodes (execution graph)
# ---------------------------------------------------------------------------


def _step_facts(step: Step, states: dict[str, State]) -> tuple[tuple[str, str], ...]:
    """Return the label/value rows describing how a step runs."""
    facts: list[tuple[str, str]] = []
    if step.harness:
        facts.append(("Harness", step.harness))
    if step.model:
        facts.append(("Model", step.model))
    if step.produces:
        facts.append(("Produces", states[step.produces].label))
    if step.wave:
        facts.append(("Wave", step.wave))
    return tuple(facts)


def execution_view(spec: PipelineSpec) -> PipelineView:
    """Build the execution view: steps as nodes, declared transitions as edges.

    Args:
        spec (PipelineSpec): Loaded pipeline file.

    Returns:
        PipelineView: Renderable view.

    Examples:
        >>> execution_view(load_pipeline_spec(Path("p.toml"))).view_id  # doctest: +SKIP
        'execution'
    """
    placed = all(step.layer is not None and step.column is not None for step in spec.steps)
    fallback = (
        {}
        if placed
        else _derive_placement(
            [step.step_id for step in spec.steps],
            [(step.step_id, t.to) for step in spec.steps for t in step.transitions],
        )
    )
    states = spec.state_map()
    nodes: list[ViewNode] = []
    for step in spec.steps:
        layer, column = fallback.get(step.step_id, (step.layer or 0, step.column or 0.0))
        nodes.append(
            ViewNode(
                node_id=step.step_id,
                label=step.label,
                kind=step.kind,
                layer=layer,
                column=column,
                note=step.note,
                detail=NodeDetail(
                    summary=step.summary,
                    facts=_step_facts(step, states),
                    params=step.params,
                ),
            )
        )
    edges = tuple(
        ViewEdge(
            source=step.step_id,
            target=transition.to,
            label=transition.label,
            note=transition.note,
            detail=transition.detail,
            style=transition.style,
            bow=transition.bow,
        )
        for step in spec.steps
        for transition in step.transitions
    )
    members: dict[str, list[str]] = {cluster.cluster_id: [] for cluster in spec.clusters}
    for step in spec.steps:
        if step.cluster:
            members[step.cluster].append(step.step_id)
    clusters = tuple(
        ViewCluster(label=cluster.label, members=tuple(members[cluster.cluster_id]))
        for cluster in spec.clusters
        if members[cluster.cluster_id]
    )
    return PipelineView(
        view_id="execution",
        title=f"{spec.title} — execution graph (agent is node)",
        subtitle="Agents, system phases, and human gates are nodes; edges are control transitions",
        nodes=tuple(nodes),
        edges=edges,
        clusters=clusters,
        source=spec.source,
    )


# ---------------------------------------------------------------------------
# View 2 — states are nodes, step work is the edge
# ---------------------------------------------------------------------------


def _chain_note(works: Sequence[str]) -> str:
    """Join a chain of step names, eliding the middle when longer than two."""
    trimmed = [work for work in works if work]
    if not trimmed:
        return ""
    if len(trimmed) <= 2:
        return " → ".join(trimmed)
    return f"{trimmed[0]} → … → {trimmed[-1]}"


def _source_states(
    step_id: str,
    spec: PipelineSpec,
    incoming: dict[str, list[tuple[str, Transition]]],
    seen: frozenset[str],
) -> list[tuple[str, list[str]]]:
    """Walk back to the nearest state-producing ancestors of *step_id*.

    Returns:
        list[tuple[str, list[str]]]: ``(state_id, works)`` where *works* are the
        labels of the non-producing steps passed through, in flow order.
    """
    step = spec.step_map()[step_id]
    if step.produces:
        return [(step.produces, [])]
    out: list[tuple[str, list[str]]] = []
    for source_id, _transition in incoming.get(step_id, []):
        if source_id in seen:
            continue
        for state_id, works in _source_states(source_id, spec, incoming, seen | {step_id}):
            out.append((state_id, [*works, step.work_label]))
    return out


def _merge_parts(parts: Sequence[str], separator: str) -> str:
    """Join distinct label or note fragments, capping the list at two entries."""
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    if len(unique) <= 2:
        return separator.join(unique)
    return separator.join(unique[:2]) + separator + "…"


def _state_edge_label(step: Step, transition: Transition) -> str:
    """Return the primary label for a derived state edge.

    Forward work is named by the producing step's ``wave``; feedback and side
    paths are named by the transition that triggered them, which carries the
    reason (``failed → retry``) rather than the wave id.
    """
    if transition.style == "primary" and step.wave:
        return step.wave
    return transition.label or step.wave


@dataclass
class _EdgeParts:
    """Label, note, and hover-detail fragments collected for one state edge."""

    labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


def _derive_state_edges(spec: PipelineSpec) -> tuple[ViewEdge, ...]:
    """Derive one state-view edge per state transition, merging parallel steps."""
    incoming = spec.incoming()
    grouped: dict[tuple[str, str, TransitionStyle, str], _EdgeParts] = {}
    for step in spec.steps:
        if not step.produces:
            continue
        for source_id, transition in incoming.get(step.step_id, []):
            for state_id, works in _source_states(source_id, spec, incoming, frozenset()):
                if state_id == step.produces:
                    continue
                key = (state_id, step.produces, transition.style, transition.bow)
                parts = grouped.setdefault(key, _EdgeParts())
                parts.labels.append(_state_edge_label(step, transition))
                parts.notes.append(_chain_note([*works, step.work_label]))
                parts.details.append(transition.detail)
    return tuple(
        ViewEdge(
            source=source,
            target=target,
            label=_merge_parts(parts.labels, " / "),
            note=_merge_parts(parts.notes, ", "),
            detail=_merge_parts(parts.details, " "),
            style=style,
            bow=bow,  # type: ignore[arg-type]
        )
        for (source, target, style, bow), parts in grouped.items()
    )


def state_view(spec: PipelineSpec) -> PipelineView:
    """Build the state view: artifact states as nodes, step work as edges.

    Each edge runs from the state a step consumed to the state it produces, and
    is labelled with the step's ``wave`` plus the agent (or chain of agents) that
    performs the work.

    Args:
        spec (PipelineSpec): Loaded pipeline file.

    Returns:
        PipelineView: Renderable view.

    Examples:
        >>> state_view(load_pipeline_spec(Path("p.toml"))).view_id  # doctest: +SKIP
        'state'
    """
    states = spec.state_map()
    edges = _derive_state_edges(spec)
    used = [
        state_id
        for state_id in states
        if any(state_id in (edge.source, edge.target) for edge in edges)
    ]
    placed = all(
        states[state_id].layer is not None and states[state_id].column is not None
        for state_id in used
    )
    fallback = (
        {} if placed else _derive_placement(used, [(edge.source, edge.target) for edge in edges])
    )
    producers: dict[str, list[Step]] = {}
    for step in spec.steps:
        if step.produces:
            producers.setdefault(step.produces, []).append(step)
    nodes: list[ViewNode] = []
    for state_id in used:
        state = states[state_id]
        layer, column = fallback.get(state_id, (state.layer or 0, state.column or 0.0))
        cards = tuple(
            DetailCard(
                name=step.label,
                summary=step.summary,
                facts=_step_facts(step, states),
                params=step.params,
            )
            for step in producers.get(state_id, [])
        )
        nodes.append(
            ViewNode(
                node_id=state_id,
                label=state.label,
                kind=state.kind,
                layer=layer,
                column=column,
                note=state.note,
                detail=NodeDetail(summary=state.note, cards=cards),
            )
        )
    clusters = tuple(
        ViewCluster(
            label=cluster.label,
            members=tuple(state_id for state_id in cluster.states if state_id in set(used)),
        )
        for cluster in spec.clusters
        if any(state_id in set(used) for state_id in cluster.states)
    )
    return PipelineView(
        view_id="state",
        title=f"{spec.title} — state graph (edge is agent work)",
        subtitle="Artifact states are nodes; each edge is the wave and agent that produces them",
        nodes=tuple(nodes),
        edges=edges,
        clusters=clusters,
        source=spec.source,
        col_pitch=392,
        row_pitch=196,
    )


VIEWS: dict[str, Callable[[PipelineSpec], PipelineView]] = {
    "execution": execution_view,
    "state": state_view,
}
