"""tripll.pipeline_views._layout — serpentine placement and orthogonal edge routing.

Placement is serpentine: row 0 reads left to right, row 1 right to left, and so
on, so a long pipeline turns at the end of a row and returns on the next instead
of running off the page. Each row's reading direction is inferred from its own
primary edges, so "forward" is not assumed to be rightwards.

Every edge is routed as an orthogonal polyline with rounded 90° bends: forward
edges drop through the gutter above their target row (fanned out when several
share it), edges along a row follow that row's direction, feedback edges dip
below their row, and edges back to an earlier row return through a corridor
beside the nodes.

Exports:
    layout — geometry constants and the resolved pixel geometry of one view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tripll.pipeline_views._model import PipelineView, ViewEdge, ViewNode

NODE_W = 172
NODE_H = 58
MARGIN = 30
#: Width reserved outside the grid for edges that return to an earlier row.
CORRIDOR = 76
#: Distance from a node's side to the vertical run of a return edge.
RETURN_GAP = 30
#: Radius applied to every 90° bend in an edge.
CORNER = 13
DIP_BASE = 34
DIP_STEP = 26
#: Vertical fan-out applied to turning edges that share one row gutter.
CHANNEL_STEP = 11
#: Height a cluster box extends above its first row, leaving its heading clear of
#: the edge labels that sit in the same gutter.
CLUSTER_TOP = 80

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
    """Assign (layer, column) by longest path, serpentine, ignoring back edges.

    Rows alternate direction — row 0 fills left to right, row 1 right to left —
    so a long pipeline turns and returns down the page instead of running off
    the right edge, and consecutive steps stay adjacent across the turn.

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
    rows: dict[int, list[str]] = {}
    for node_id in order:
        rows.setdefault(layer[node_id], []).append(node_id)
    widest = max((len(members) for members in rows.values()), default=1)
    placement: dict[str, tuple[int, float]] = {}
    for row, members in rows.items():
        for index, node_id in enumerate(members):
            column = index if row % 2 == 0 else widest - 1 - index
            placement[node_id] = (row, float(column))
    return placement


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass
class _Geometry:
    """Pixel geometry for one view."""

    view: PipelineView
    directions: dict[int, int] = field(default_factory=dict)
    channels: dict[tuple[str, str], float] = field(default_factory=dict)
    x: dict[str, int] = field(default_factory=dict)
    y: dict[str, int] = field(default_factory=dict)
    width: int = 0
    height: int = 0

    def centre_x(self, node_id: str) -> int:
        return self.x[node_id] + NODE_W // 2

    def centre_y(self, node_id: str) -> int:
        return self.y[node_id] + NODE_H // 2


def _bow_side(edge: ViewEdge, source: ViewNode, target: ViewNode) -> Literal["left", "right"]:
    """Return the side an edge to an earlier layer should return through."""
    if edge.bow != "auto":
        return edge.bow
    return "left" if target.column <= source.column else "right"


def _needs_channel(view: PipelineView) -> tuple[bool, bool]:
    """Return whether the (left, right) return corridors are used."""
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


def _layer_directions(view: PipelineView) -> dict[int, int]:
    """Infer each row's reading direction from the primary edges inside it.

    A serpentine layout reads left-to-right on one row and right-to-left on the
    next, so "forward" along a row is not always rightwards. Rows vote with
    their own primary edges; rows without any default to left-to-right.

    Args:
        view (PipelineView): The view being laid out.

    Returns:
        dict[int, int]: layer index → ``+1`` (rightwards) or ``-1`` (leftwards).

    Examples:
        >>> nodes = (ViewNode("a", "A", "agent", 0, 1), ViewNode("b", "B", "agent", 0, 0))
        >>> view = PipelineView("v", "t", "s", nodes, (ViewEdge("a", "b"),))
        >>> _layer_directions(view)[0]
        -1
    """
    nodes = view.node_map()
    votes: dict[int, int] = {}
    for edge in view.edges:
        source, target = nodes[edge.source], nodes[edge.target]
        if source.layer != target.layer or edge.style != "primary":
            continue
        step = 1 if target.column > source.column else -1
        votes[source.layer] = votes.get(source.layer, 0) + step
    return {node.layer: (-1 if votes.get(node.layer, 0) < 0 else 1) for node in view.nodes}


def _channel_offsets(view: PipelineView) -> dict[tuple[str, str], float]:
    """Fan out the turning edges that share a row gutter so they do not overlap."""
    nodes = view.node_map()
    per_layer: dict[int, int] = {}
    offsets: dict[tuple[str, str], float] = {}
    for edge in view.edges:
        source, target = nodes[edge.source], nodes[edge.target]
        if target.layer <= source.layer or source.column == target.column:
            continue
        index = per_layer.get(target.layer, 0)
        per_layer[target.layer] = index + 1
        offsets[edge.source, edge.target] = CHANNEL_STEP * ((index + 1) // 2) * (-1) ** index
    return offsets


def _geometry(view: PipelineView) -> _Geometry:
    left_channel, right_channel = _needs_channel(view)
    pad_left = MARGIN + (CORRIDOR if left_channel else 0)
    pad_right = MARGIN + (CORRIDOR if right_channel else 0)
    pad_top = MARGIN + (CLUSTER_TOP if view.clusters else DIP_BASE)
    geo = _Geometry(
        view=view,
        directions=_layer_directions(view),
        channels=_channel_offsets(view),
    )
    for node in view.nodes:
        geo.x[node.node_id] = int(pad_left + node.column * view.col_pitch)
        geo.y[node.node_id] = pad_top + node.layer * view.row_pitch
    max_column = max((node.column for node in view.nodes), default=0)
    max_layer = max((node.layer for node in view.nodes), default=0)
    geo.width = int(pad_left + max_column * view.col_pitch + NODE_W + pad_right)
    geo.height = pad_top + max_layer * view.row_pitch + NODE_H + MARGIN + DIP_BASE
    return geo


def _dip_depths(view: PipelineView, directions: dict[int, int]) -> dict[tuple[str, str], int]:
    """Stagger the feedback edges of each row so their dips do not overlap."""
    nodes = view.node_map()
    per_layer: dict[int, int] = {}
    depths: dict[tuple[str, str], int] = {}
    for edge in view.edges:
        source, target = nodes[edge.source], nodes[edge.target]
        if source.layer != target.layer:
            continue
        step = 1 if target.column > source.column else -1
        if step != directions[source.layer]:
            index = per_layer.get(source.layer, 0)
            depths[edge.source, edge.target] = DIP_BASE + index * DIP_STEP
            per_layer[source.layer] = index + 1
    return depths


Point = tuple[float, float]


def _rounded_path(points: Sequence[Point], radius: float = CORNER) -> str:
    """Render an orthogonal polyline as an SVG path with rounded right angles.

    Each interior corner is cut back along both of its segments and closed with a
    quadratic curve, so turns read as a 90° bend with a soft radius rather than a
    long diagonal sweep.

    Args:
        points (Sequence[Point]): Orthogonal waypoints, start to end.
        radius (float): Desired corner radius in pixels; clamped per corner to
            half of the shorter adjacent segment.

    Returns:
        str: An SVG path ``d`` attribute.

    Examples:
        >>> _rounded_path([(0, 0), (0, 40), (40, 40)], radius=10)
        'M 0 0 L 0 30 Q 0 40 10 40 L 40 40'
    """
    if len(points) < 3:
        return " ".join(
            ("M" if index == 0 else "L") + f" {_round(x)} {_round(y)}"
            for index, (x, y) in enumerate(points)
        )
    parts = [f"M {_round(points[0][0])} {_round(points[0][1])}"]
    for index in range(1, len(points) - 1):
        before, corner, after = points[index - 1], points[index], points[index + 1]
        in_len = abs(corner[0] - before[0]) + abs(corner[1] - before[1])
        out_len = abs(after[0] - corner[0]) + abs(after[1] - corner[1])
        cut = min(radius, in_len / 2, out_len / 2)
        entry = _towards(corner, before, cut)
        exit_ = _towards(corner, after, cut)
        parts.append(f"L {_round(entry[0])} {_round(entry[1])}")
        parts.append(
            f"Q {_round(corner[0])} {_round(corner[1])} {_round(exit_[0])} {_round(exit_[1])}"
        )
    parts.append(f"L {_round(points[-1][0])} {_round(points[-1][1])}")
    return " ".join(parts)


def _round(value: float) -> str:
    """Format a coordinate compactly and deterministically."""
    return f"{value:g}"


def _towards(origin: Point, target: Point, distance: float) -> Point:
    """Return the point *distance* pixels from *origin* along a straight axis."""
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    length = abs(dx) + abs(dy)
    if length == 0:
        return origin
    return (origin[0] + dx / length * distance, origin[1] + dy / length * distance)


@dataclass(frozen=True)
class _EdgeGeom:
    """Resolved SVG path plus label anchor for one edge.

    ``anchor`` says how the label pill sits on ``label_y``: ``center`` puts the
    pill on the line, ``above`` hangs it from that baseline — used for edges that
    run along a row, where the gap between two nodes is narrower than the pill.
    """

    path: str
    label_x: float
    label_y: float
    anchor: Literal["center", "above"] = "center"


def _edge_geometry(
    edge: ViewEdge,
    geo: _Geometry,
    dips: dict[tuple[str, str], int],
) -> _EdgeGeom:
    """Route one edge as an orthogonal path and pick where its label sits."""
    nodes = geo.view.node_map()
    source, target = nodes[edge.source], nodes[edge.target]
    left_s, top_s = geo.x[edge.source], geo.y[edge.source]
    left_t, top_t = geo.x[edge.target], geo.y[edge.target]
    mid_x_s, mid_y_s = geo.centre_x(edge.source), geo.centre_y(edge.source)
    mid_x_t, mid_y_t = geo.centre_x(edge.target), geo.centre_y(edge.target)

    if target.layer > source.layer:
        start, end = (mid_x_s, top_s + NODE_H), (mid_x_t, top_t)
        if abs(mid_x_s - mid_x_t) < 2:
            return _EdgeGeom(
                path=_rounded_path([start, end]),
                label_x=mid_x_s,
                label_y=(start[1] + end[1]) / 2,
            )
        channel = (
            top_t
            - (geo.view.row_pitch - NODE_H) / 2
            + geo.channels.get((edge.source, edge.target), 0.0)
        )
        points = [start, (mid_x_s, channel), (mid_x_t, channel), end]
        return _EdgeGeom(
            path=_rounded_path(points),
            label_x=(mid_x_s + mid_x_t) / 2,
            label_y=channel,
        )

    if target.layer == source.layer:
        direction = geo.directions[source.layer]
        step = 1 if target.column > source.column else -1
        if step == direction:
            start_x = left_s + NODE_W if direction > 0 else left_s
            end_x = left_t if direction > 0 else left_t + NODE_W
            return _EdgeGeom(
                path=_rounded_path([(start_x, mid_y_s), (end_x, mid_y_s)]),
                label_x=(start_x + end_x) / 2,
                label_y=top_s - 6,
                anchor="above",
            )
        dip = top_s + NODE_H + dips[edge.source, edge.target]
        points = [
            (mid_x_s, top_s + NODE_H),
            (mid_x_s, dip),
            (mid_x_t, dip),
            (mid_x_t, top_t + NODE_H),
        ]
        return _EdgeGeom(
            path=_rounded_path(points),
            label_x=(mid_x_s + mid_x_t) / 2,
            label_y=dip,
        )

    if _bow_side(edge, source, target) == "right":
        corridor = max(left_s, left_t) + NODE_W + RETURN_GAP
        start_x, end_x = left_s + NODE_W, left_t + NODE_W
    else:
        corridor = min(left_s, left_t) - RETURN_GAP
        start_x, end_x = left_s, left_t
    points = [
        (start_x, mid_y_s),
        (corridor, mid_y_s),
        (corridor, mid_y_t),
        (end_x, mid_y_t),
    ]
    return _EdgeGeom(
        path=_rounded_path(points),
        label_x=corridor,
        label_y=(mid_y_s + mid_y_t) / 2,
    )
