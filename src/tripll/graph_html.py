"""tripll.graph_html — self-contained HTML/SVG view of a RunGraph DAG.

Renders the wave nodes of a :class:`~tripll.graph.RunGraph` as boxes laid out in
dependency-depth layers, with one arrow per ``depends_on`` edge. Layout is
computed in Python and emitted as inline SVG, so the document needs no external
asset fetch and is byte-stable for the same graph.

Exports:
    NodeBox — one positioned wave node in the rendered layout.
    GraphLayout — computed boxes, edges, and canvas size.
    layout_graph — layer nodes by dependency depth (deterministic).
    render_graph_html — self-contained HTML document with an inline SVG DAG.
    write_graph_html — render and write the document to disk.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.graph import RunGraph

__all__ = [
    "GraphLayout",
    "NodeBox",
    "layout_graph",
    "render_graph_html",
    "write_graph_html",
]

NODE_W = 220
NODE_H = 66
H_GAP = 34
V_GAP = 74
MARGIN = 28


@dataclass(frozen=True)
class NodeBox:
    """One positioned wave node.

    Args:
        node_id (str): Graph node id (``<plan_id>:<wave_id>``).
        wave_id (str): Wave label shown as the box heading.
        lane (str): Lane label (plan title in v1 sets).
        batch (str): Batch id this node belongs to (``''`` when unassigned).
        effort (str): Effort bucket (``S`` | ``M`` | ``L`` | ``XL``).
        role (str): Wave role (``impl`` | ``test-author``).
        review_gate (bool): True for human-gated review waves.
        depth (int): Dependency-depth layer index (0 = no dependencies).
        x (int): Left edge in SVG user units.
        y (int): Top edge in SVG user units.
    """

    node_id: str
    wave_id: str
    lane: str
    batch: str
    effort: str
    role: str
    review_gate: bool
    depth: int
    x: int
    y: int


@dataclass(frozen=True)
class GraphLayout:
    """Computed layout for one RunGraph.

    Args:
        boxes (tuple[NodeBox, ...]): Positioned nodes, ordered by depth then node_id.
        edges (tuple[tuple[str, str], ...]): ``(from_node_id, to_node_id)`` dependency
            edges, where ``from_node_id`` must complete first.
        width (int): Canvas width in SVG user units.
        height (int): Canvas height in SVG user units.
    """

    boxes: tuple[NodeBox, ...]
    edges: tuple[tuple[str, str], ...]
    width: int
    height: int


def _node_depths(graph: RunGraph) -> dict[str, int]:
    """Return node_id → dependency depth, ignoring dangling deps and cycle backedges."""
    depths: dict[str, int] = {}

    def depth_of(node_id: str, seen: frozenset[str]) -> int:
        cached = depths.get(node_id)
        if cached is not None:
            return cached
        if node_id in seen:
            return 0
        deps = [d for d in graph.nodes[node_id].depends_on if d in graph.nodes]
        value = 0 if not deps else 1 + max(depth_of(d, seen | {node_id}) for d in deps)
        depths[node_id] = value
        return value

    for node_id in graph.nodes:
        depth_of(node_id, frozenset())
    return depths


def _batch_of(graph: RunGraph) -> dict[str, str]:
    """Return node_id → batch id, matching on wave ids first, then lane membership."""
    out: dict[str, str] = {}
    for batch in graph.batches:
        for node_id, node in graph.nodes.items():
            if node_id in out:
                continue
            if batch.wave_ids:
                if node.wave_id in batch.wave_ids:
                    out[node_id] = batch.batch_id
            elif node.plan_id in batch.lanes:
                out[node_id] = batch.batch_id
    return out


def layout_graph(graph: RunGraph) -> GraphLayout:
    """Lay out *graph* as depth-ordered layers of fixed-size boxes.

    Nodes with no dependencies form layer 0; every other node sits one layer
    below its deepest dependency. Layers run top to bottom and are centred
    horizontally; within a layer, nodes are ordered by node_id so the output is
    deterministic.

    Args:
        graph (RunGraph): The run graph to lay out.

    Returns:
        GraphLayout: Positioned boxes, dependency edges, and canvas size.

    Examples:
        >>> from tripll.graph import RunGraph, WaveNode
        >>> g = RunGraph(run_id="r", nodes={"p:W0": WaveNode("p:W0", "p", "p.md", "W0", "lane")})
        >>> layout_graph(g).boxes[0].depth
        0
    """
    depths = _node_depths(graph)
    batches = _batch_of(graph)
    layers: dict[int, list[str]] = {}
    for node_id, depth in depths.items():
        layers.setdefault(depth, []).append(node_id)

    widest = max((len(ids) for ids in layers.values()), default=0)
    row_width = widest * NODE_W + max(widest - 1, 0) * H_GAP
    boxes: list[NodeBox] = []
    for depth in sorted(layers):
        ids = sorted(layers[depth])
        span = len(ids) * NODE_W + max(len(ids) - 1, 0) * H_GAP
        offset = MARGIN + (row_width - span) // 2
        for index, node_id in enumerate(ids):
            node = graph.nodes[node_id]
            boxes.append(
                NodeBox(
                    node_id=node_id,
                    wave_id=node.wave_id,
                    lane=node.lane,
                    batch=batches.get(node_id, ""),
                    effort=node.effort,
                    role=node.role,
                    review_gate=node.is_review_gate,
                    depth=depth,
                    x=offset + index * (NODE_W + H_GAP),
                    y=MARGIN + depth * (NODE_H + V_GAP),
                )
            )

    edges = tuple(
        (dep, node_id)
        for node_id in sorted(graph.nodes)
        for dep in sorted(graph.nodes[node_id].depends_on)
        if dep in graph.nodes
    )
    depth_count = len(layers)
    return GraphLayout(
        boxes=tuple(boxes),
        edges=edges,
        width=row_width + 2 * MARGIN,
        height=depth_count * NODE_H + max(depth_count - 1, 0) * V_GAP + 2 * MARGIN,
    )


def _ellipsis(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _box_class(box: NodeBox) -> str:
    if box.review_gate:
        return "box box-gate"
    if box.role == "test-author":
        return "box box-test"
    return "box box-impl"


def _render_svg(layout: GraphLayout) -> list[str]:
    by_id = {box.node_id: box for box in layout.boxes}
    parts: list[str] = [
        f'<svg class="dag" viewBox="0 0 {layout.width} {layout.height}" '
        f'width="{layout.width}" height="{layout.height}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="wave dependency graph">',
        "<defs>",
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">',
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8a8577"></path>',
        "</marker>",
        "</defs>",
    ]
    for source, target in layout.edges:
        a, b = by_id[source], by_id[target]
        x1 = a.x + NODE_W // 2
        y1 = a.y + NODE_H
        x2 = b.x + NODE_W // 2
        y2 = b.y
        mid = (y1 + y2) // 2
        parts.append(
            f'<path class="edge" d="M {x1} {y1} C {x1} {mid}, {x2} {mid}, {x2} {y2}" '
            f'marker-end="url(#arrow)">'
            f"<title>{html.escape(source)} → {html.escape(target)}</title></path>"
        )
    for box in layout.boxes:
        meta_bits = [bit for bit in (f"batch {box.batch}" if box.batch else "", box.effort) if bit]
        meta = " · ".join([*meta_bits, box.role])
        parts.extend(
            [
                f'<g class="{_box_class(box)}">',
                f"<title>{html.escape(box.node_id)}</title>",
                f'<rect x="{box.x}" y="{box.y}" width="{NODE_W}" height="{NODE_H}" rx="9"></rect>',
                f'<text class="wave" x="{box.x + 12}" y="{box.y + 23}">'
                f"{html.escape(box.wave_id)}</text>",
                f'<text class="lane" x="{box.x + 12}" y="{box.y + 41}">'
                f"{html.escape(_ellipsis(box.lane, 30))}</text>",
                f'<text class="meta" x="{box.x + 12}" y="{box.y + 57}">{html.escape(meta)}</text>',
                "</g>",
            ]
        )
    parts.append("</svg>")
    return parts


_STYLE = [
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:24px;"
    "background:#faf9f7;color:#1a1a1a}",
    "h1{font-size:1.35rem;margin:0 0 4px}",
    "h2{font-size:1rem;margin:24px 0 8px}",
    ".meta-line{color:#555;font-size:.9rem;margin:0 0 16px}",
    ".legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.82rem;color:#444;margin-bottom:12px}",
    ".swatch{display:inline-block;width:11px;height:11px;border-radius:3px;"
    "margin-right:5px;vertical-align:middle;border:1px solid #d4d0c8}",
    ".swatch-impl{background:#fff;border-color:#111}",
    ".swatch-test{background:#eef4ff;border-color:#7c9cff}",
    ".swatch-gate{background:#fff9e6;border-color:#e6a700}",
    ".dag{max-width:100%;height:auto}",
    ".edge{fill:none;stroke:#8a8577;stroke-width:1.5}",
    ".box rect{fill:#fff;stroke:#111;stroke-width:1.5}",
    ".box-test rect{fill:#eef4ff;stroke:#7c9cff}",
    ".box-gate rect{fill:#fff9e6;stroke:#e6a700}",
    "text{font-family:ui-sans-serif,system-ui,sans-serif}",
    ".wave{font-size:14px;font-weight:600}",
    ".lane{font-size:11px;fill:#444}",
    ".meta{font-size:10px;fill:#666;letter-spacing:.03em}",
    "ol{font-size:.88rem;color:#333;padding-left:20px}",
    ".empty{color:#777;font-size:.9rem}",
]


def render_graph_html(graph: RunGraph, *, source: str) -> str:
    """Render *graph* as a self-contained HTML document with an inline SVG DAG.

    Args:
        graph (RunGraph): The run graph to render.
        source (str): Input path the graph was parsed from (shown in the header).

    Returns:
        str: Full HTML document; no external asset fetch.

    Examples:
        >>> from tripll.graph import RunGraph
        >>> render_graph_html(RunGraph(run_id="r"), source="in/").startswith("<!DOCTYPE html>")
        True
    """
    layout = layout_graph(graph)
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(source)} — wave graph</title>",
        "<style>",
        *_STYLE,
        "</style>",
        "</head>",
        "<body>",
        "<h1>wave graph — nodes &amp; edges</h1>",
        f'<p class="meta-line">source={html.escape(source)} · '
        f"mode={html.escape(graph.source_mode)} · "
        f"lanes={len(graph.lanes)} · nodes={len(layout.boxes)} · edges={len(layout.edges)}</p>",
        '<div class="legend">',
        '<span><span class="swatch swatch-impl"></span>impl wave</span>',
        '<span><span class="swatch swatch-test"></span>test-author wave</span>',
        '<span><span class="swatch swatch-gate"></span>review gate</span>',
        "<span>arrow = depends_on (source must finish first)</span>",
        "</div>",
    ]
    if layout.boxes:
        parts.extend(_render_svg(layout))
    else:
        parts.append('<p class="empty">No wave nodes in this graph.</p>')

    parts.append("<h2>Pre-0 gates</h2>")
    if graph.pre0_gates:
        parts.append("<ol>")
        parts.extend(f"<li>{html.escape(gate)}</li>" for gate in graph.pre0_gates)
        parts.append("</ol>")
    else:
        parts.append('<p class="empty">None.</p>')

    parts.extend(["</body>", "</html>"])
    return "\n".join(parts) + "\n"


def write_graph_html(graph: RunGraph, out_path: Path, *, source: str) -> Path:
    """Render *graph* and write the HTML document to *out_path*.

    Parent directories are created when missing.

    Args:
        graph (RunGraph): The run graph to render.
        out_path (Path): Destination ``.html`` file.
        source (str): Input path the graph was parsed from.

    Returns:
        Path: The resolved written path.

    Examples:
        >>> write_graph_html(RunGraph(run_id="r"), Path("/tmp/g.html"), source=".")  # doctest: +SKIP
        PosixPath('/tmp/g.html')
    """
    resolved = out_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(render_graph_html(graph, source=source), encoding="utf-8")
    return resolved
