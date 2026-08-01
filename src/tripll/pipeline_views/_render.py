"""tripll.pipeline_views._render — one offline HTML document per view.

Renders a laid-out view as a single self-contained file: inline CSS for the node
palette, cluster panels, and label pills; inline SVG for the graph itself; and
one inline script giving it zoom, drag-to-pan, hover focus, a node popup with the
agent note, and an edge tooltip explaining the routing rule. Nothing is fetched.

Exports:
    render_view_html — self-contained HTML document for one view.
    write_view_html — render one view and write it to disk.
"""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

from tripll.pipeline_views._layout import (
    CLUSTER_TOP,
    NODE_H,
    NODE_W,
    _dip_depths,
    _edge_geometry,
    _EdgeGeom,
    _Geometry,
    _geometry,
    _round,
)
from tripll.pipeline_views._model import (
    _KIND_LABELS,
    _STYLE_LABELS,
    DetailCard,
    PipelineView,
    ViewEdge,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["render_view_html", "write_view_html"]

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_clusters(view: PipelineView, geo: _Geometry) -> list[str]:
    parts: list[str] = []
    pad = 20
    for index, cluster in enumerate(view.clusters):
        members = [m for m in cluster.members if m in geo.x]
        if not members:
            continue
        xs = [geo.x[m] for m in members]
        ys = [geo.y[m] for m in members]
        x = min(xs) - pad
        y = min(ys) - CLUSTER_TOP
        width = max(xs) + NODE_W + pad - x
        height = max(ys) + NODE_H + pad - y
        parts.extend(
            [
                f'<g class="cluster cluster-{index % 3}">',
                f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="16"></rect>',
                f'<text x="{x + 16}" y="{y + 16}">{html.escape(cluster.label)}</text>',
                "</g>",
            ]
        )
    return parts


#: Approximate advance width per character at the label and note font sizes.
_LABEL_CHAR = 6.0
_NOTE_CHAR = 5.2
_ANSWER_GLYPH = {"yes": "\u2713", "no": "\u2717"}

#: Arrowhead colours, keyed by answer first then transition style.
_ARROW_COLOURS: tuple[tuple[str, str], ...] = (
    ("primary", "#46506b"),
    ("conditional", "#d98324"),
    ("optional", "#8f7fc6"),
    ("yes", "#17916a"),
    ("no", "#d1495b"),
)


def _render_edge_label(edge: ViewEdge, eg: _EdgeGeom, index: int) -> list[str]:
    """Draw an edge's label and note inside a pill so both stay readable."""
    label = f"{_ANSWER_GLYPH[edge.answer]} {edge.label}" if edge.answer else edge.label
    lines = [line for line in (label, edge.note) if line]
    if not lines:
        return []
    width = max(len(label) * _LABEL_CHAR, len(edge.note) * _NOTE_CHAR) + 18
    height = 20 if len(lines) == 1 else 32
    top = eg.label_y - height if eg.anchor == "above" else eg.label_y - height / 2
    variant = f"pill-{edge.answer}" if edge.answer else f"pill-{edge.style}"
    parts = [
        f'<g class="plabel" data-label="{index}">',
        f'<rect class="pill {variant}" x="{_round(eg.label_x - width / 2)}" '
        f'y="{_round(top)}" width="{_round(width)}" height="{height}" rx="10"></rect>',
    ]
    baselines = (14.0,) if len(lines) == 1 else (13.0, 25.0)
    classes = ("elabel", "enote") if label else ("enote",)
    parts.extend(
        f'<text class="{css}" x="{_round(eg.label_x)}" y="{_round(top + baseline)}">'
        f"{html.escape(line)}</text>"
        for line, baseline, css in zip(lines, baselines, classes, strict=False)
    )
    parts.append("</g>")
    return parts


def _render_edges(view: PipelineView, geo: _Geometry) -> list[str]:
    dips = _dip_depths(view, geo.directions)
    nodes = view.node_map()
    paths: list[str] = []
    labels: list[str] = []
    for index, edge in enumerate(view.edges):
        eg = _edge_geometry(edge, geo, dips)
        title = f"{nodes[edge.source].label} → {nodes[edge.target].label}"
        if edge.label:
            title += f" · {edge.label}"
        if edge.detail:
            title += f"\n{edge.detail}"
        paths.append(
            f'<path class="edge edge-{edge.style}" data-edge="{index}" '
            f'data-source="{html.escape(edge.source, quote=True)}" '
            f'data-target="{html.escape(edge.target, quote=True)}" d="{eg.path}" '
            f'marker-end="url(#arrow-{edge.answer or edge.style})">'
            f"<title>{html.escape(title)}</title></path>"
        )
        labels.extend(_render_edge_label(edge, eg, index))
    return paths + labels


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
    branches: dict[str, int] = {}
    for edge in view.edges:
        branches[edge.source] = branches.get(edge.source, 0) + 1
    parts: list[str] = []
    for node in view.nodes:
        x, y = geo.x[node.node_id], geo.y[node.node_id]
        lines = _wrap_label(node.label)
        rows = _TEXT_ROWS[len(lines), bool(node.note)]
        centre = x + NODE_W // 2
        openable = node.detail is not None and not node.detail.is_empty()
        classes = f"node node-{node.kind}" + (" node-open" if openable else "")
        hint = " · click for details" if openable else ""
        parts.extend(
            [
                f'<g class="{classes}" data-node="{html.escape(node.node_id, quote=True)}">',
                f"<title>{html.escape(node.node_id + hint)}</title>",
                f'<rect class="body" x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" '
                'rx="11"></rect>',
                f'<rect class="rail" x="{x + 1}" y="{y + 10}" width="5" '
                f'height="{NODE_H - 20}" rx="2.5"></rect>',
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
        fan = branches.get(node.node_id, 0)
        if fan > 1:
            parts.extend(
                [
                    '<g class="fan">',
                    f"<title>routes {fan} ways</title>",
                    f'<circle cx="{x + NODE_W - 13}" cy="{y + 13}" r="9"></circle>',
                    f'<text x="{x + NODE_W - 13}" y="{y + 17}">{fan}</text>',
                    "</g>",
                ]
            )
        parts.append("</g>")
    return parts


_STYLE = [
    ":root{--ink:#1c1a16;--muted:#6f6a5e;--rule:#e6e2d9;--primary:#46506b;"
    "--conditional:#d98324;--optional:#8f7fc6;--yes:#17916a;--no:#d1495b}",
    "*{box-sizing:border-box}",
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:0;padding:26px 26px 34px;"
    "min-height:100vh;color:var(--ink);"
    "background:linear-gradient(180deg,#fbfaf8 0%,#f4f2ec 55%,#edeae2 100%)}",
    "h1{font-size:1.4rem;margin:0 0 4px;letter-spacing:-.01em}",
    ".sub{color:var(--muted);font-size:.92rem;margin:0 0 14px}",
    ".legend{display:flex;gap:8px 16px;flex-wrap:wrap;font-size:.78rem;color:#4a463c;"
    "margin:0 0 14px;align-items:center}",
    ".legend span.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 8px;"
    "border-radius:99px;background:rgba(255,255,255,.78);border:1px solid var(--rule)}",
    ".swatch{display:inline-block;width:11px;height:11px;border-radius:3px}",
    ".swatch-gate{background:#ffeecd;border:1.5px solid #e08e0b}",
    ".swatch-phase{background:#e7eaff;border:1.5px solid #5a6bdc}",
    ".swatch-agent{background:#e2f5ec;border:1.5px solid #0f9d76}",
    ".swatch-artifact{background:#e4f0ff;border:1.5px solid #2b7fd4}",
    ".swatch-external{background:#efedea;border:1.5px solid #8b8778}",
    ".line{display:inline-block;width:24px;border-top:2px solid var(--primary)}",
    ".line-conditional{border-top-style:dashed;border-top-color:var(--conditional)}",
    ".line-optional{border-top-style:dotted;border-top-color:var(--optional)}",
    ".mark{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;"
    "border-radius:99px;font-size:.62rem;font-weight:700;color:#fff}",
    ".mark-yes{background:var(--yes)}",
    ".mark-no{background:var(--no)}",
    ".mark-fan{background:#2c2a24}",
    ".bar{display:flex;gap:8px;align-items:center;margin:0 0 10px;flex-wrap:wrap}",
    ".bar button{font:inherit;font-size:.82rem;padding:5px 12px;border-radius:8px;"
    "border:1px solid #dcd7ca;background:#fff;color:#2c2a24;cursor:pointer;"
    "box-shadow:0 1px 2px rgba(28,26,22,.06)}",
    ".bar button:hover{background:#f5f2ea;border-color:#c9c3b2}",
    ".bar .level{font-size:.8rem;color:var(--muted);min-width:46px}",
    ".bar .hint{font-size:.78rem;color:#8a8577}",
    ".canvas{overflow:auto;background:#fff;border:1px solid var(--rule);border-radius:16px;"
    "box-shadow:0 10px 34px rgba(28,26,22,.09);cursor:grab;"
    "background-image:radial-gradient(#eae6dc 1px,transparent 1px);background-size:22px 22px}",
    ".canvas.dragging{cursor:grabbing}",
    ".graph{max-width:100%;height:auto;display:block}",
    ".cluster rect{fill:#f6f4ef;stroke:#e0dbcd;stroke-width:1}",
    ".cluster-0 rect{fill:#f2f6fb;stroke:#d6e2f0}",
    ".cluster-1 rect{fill:#f4f2fa;stroke:#e0dbee}",
    ".cluster-2 rect{fill:#f6f6f1;stroke:#e4e1d4}",
    ".cluster text{font-size:11px;fill:#8a8577;letter-spacing:.1em;text-transform:uppercase}",
    ".node .body{fill:#fff;stroke:#2c2a24;stroke-width:1.5;filter:url(#lift)}",
    ".node .rail{fill:#2c2a24}",
    ".node-gate .body{fill:#fff7e8;stroke:#e08e0b}",
    ".node-gate .rail{fill:#e08e0b}",
    ".node-phase .body{fill:#f0f2ff;stroke:#5a6bdc}",
    ".node-phase .rail{fill:#5a6bdc}",
    ".node-agent .body{fill:#edfaf4;stroke:#0f9d76}",
    ".node-agent .rail{fill:#0f9d76}",
    ".node-artifact .body{fill:#eef5ff;stroke:#2b7fd4}",
    ".node-artifact .rail{fill:#2b7fd4}",
    ".node-external .body{fill:#f4f3f0;stroke:#8b8778}",
    ".node-external .rail{fill:#8b8778}",
    "text{font-family:ui-sans-serif,system-ui,sans-serif}",
    ".nlabel{font-size:12.5px;font-weight:650;text-anchor:middle;fill:#221f19}",
    ".nnote{font-size:10.5px;fill:#6f6a5e;text-anchor:middle}",
    ".fan circle{fill:#2c2a24;stroke:#fff;stroke-width:1.5}",
    ".fan text{font-size:9.5px;font-weight:700;fill:#fff;text-anchor:middle}",
    ".edge{fill:none;stroke:var(--primary);stroke-width:1.7;stroke-linecap:round}",
    ".edge-conditional{stroke:var(--conditional);stroke-dasharray:7 4}",
    ".edge-optional{stroke:var(--optional);stroke-dasharray:2 4}",
    ".pill{fill:#fff;stroke:var(--rule);stroke-width:1}",
    ".pill-conditional{fill:#fff8ee;stroke:#f0cfa2}",
    ".pill-optional{fill:#f8f6fd;stroke:#ddd4f0}",
    ".pill-yes{fill:#e9f8f1;stroke:#9fd9c2}",
    ".pill-no{fill:#fdedef;stroke:#f0b9c1}",
    ".elabel,.enote{text-anchor:middle}",
    ".elabel{font-size:10.5px;font-weight:650;fill:#2c2a24}",
    ".enote{font-size:10px;fill:#6f6a5e}",
    ".node-open{cursor:pointer}",
    ".node-open:hover .body{stroke-width:2.6}",
    "[data-edge]:hover{stroke:#12100c;stroke-width:2.8}",
    ".focus .node,.focus .edge,.focus .plabel,.focus .cluster{opacity:.16;"
    "transition:opacity .12s ease}",
    ".focus .lit{opacity:1}",
    "#tip{position:fixed;z-index:20;max-width:320px;padding:9px 11px;border-radius:9px;"
    "background:#2c2a24;color:#f7f5f0;font-size:.78rem;line-height:1.42;"
    "box-shadow:0 6px 22px rgba(0,0,0,.28);pointer-events:none}",
    "#tip b{display:block;font-size:.8rem;margin-bottom:2px}",
    "#tip .cond{color:#f3d38a}",
    "#tip .answer{font-weight:700;text-transform:uppercase;letter-spacing:.06em;font-size:.68rem}",
    "#tip .answer-yes{color:#7ee0b6}",
    "#tip .answer-no{color:#f5a2ad}",
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
document.addEventListener('keydown', (event) => {
  if (event.target !== document.body) return;
  if (event.key === '+' || event.key === '=') step(0.25);
  else if (event.key === '-') step(-0.25);
  else if (event.key === '0') { zoom = 1; applyZoom(); }
});

const canvas = document.querySelector('.canvas');
let drag = null;
canvas.addEventListener('mousedown', (event) => {
  if (event.button !== 0) return;
  drag = { x: event.clientX, y: event.clientY, left: canvas.scrollLeft, top: canvas.scrollTop };
  canvas.classList.add('dragging');
});
window.addEventListener('mousemove', (event) => {
  if (!drag) return;
  canvas.scrollLeft = drag.left - (event.clientX - drag.x);
  canvas.scrollTop = drag.top - (event.clientY - drag.y);
});
window.addEventListener('mouseup', () => { drag = null; canvas.classList.remove('dragging'); });

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
const edgePaths = Array.from(document.querySelectorAll('[data-edge]'));
const pills = new Map(
  Array.from(document.querySelectorAll('[data-label]')).map((g) => [Number(g.dataset.label), g])
);
const nodeGroups = new Map(
  Array.from(document.querySelectorAll('[data-node]')).map((g) => [g.dataset.node, g])
);

function clearFocus() {
  svg.classList.remove('focus');
  for (const el of svg.querySelectorAll('.lit')) el.classList.remove('lit');
}
function focusNode(id) {
  clearFocus();
  svg.classList.add('focus');
  nodeGroups.get(id).classList.add('lit');
  edgePaths.forEach((path, index) => {
    if (path.dataset.source !== id && path.dataset.target !== id) return;
    path.classList.add('lit');
    const other = path.dataset.source === id ? path.dataset.target : path.dataset.source;
    const peer = nodeGroups.get(other);
    if (peer) peer.classList.add('lit');
    const pill = pills.get(index);
    if (pill) pill.classList.add('lit');
  });
}
for (const [id, group] of nodeGroups) {
  group.addEventListener('mouseenter', () => focusNode(id));
  group.addEventListener('mouseleave', clearFocus);
  if (group.classList.contains('node-open')) {
    group.addEventListener('click', () => openNode(id));
  }
}

function place(event) {
  const box = tip.getBoundingClientRect();
  const x = Math.min(event.clientX + 16, window.innerWidth - box.width - 12);
  const y = Math.min(event.clientY + 16, window.innerHeight - box.height - 12);
  tip.style.left = Math.max(12, x) + 'px';
  tip.style.top = Math.max(12, y) + 'px';
}
for (const path of edgePaths) {
  const edge = DATA.edges[Number(path.dataset.edge)];
  path.addEventListener('mouseenter', (event) => {
    tip.replaceChildren(el('b', '', edge.from + ' \\u2192 ' + edge.to));
    if (edge.answer) tip.append(el('div', 'answer answer-' + edge.answer, edge.answer + ' branch'));
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
            "answer": edge.answer,
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
        f'<span class="chip"><span class="swatch swatch-{kind}"></span>'
        f"{html.escape(_KIND_LABELS[kind])}</span>"
        for kind in kinds
    )
    parts.extend(
        f'<span class="chip"><span class="line line-{style}"></span>'
        f"{html.escape(_STYLE_LABELS[style])}</span>"
        for style in styles
    )
    answers = [answer for answer in ("yes", "no") if any(e.answer == answer for e in view.edges)]
    parts.extend(
        f'<span class="chip"><span class="mark mark-{answer}">{_ANSWER_GLYPH[answer]}</span>'
        f"{answer} branch</span>"
        for answer in answers
    )
    if any(sum(1 for e in view.edges if e.source == n.node_id) > 1 for n in view.nodes):
        parts.append('<span class="chip"><span class="mark mark-fan">n</span>routes n ways</span>')
    parts.extend(
        [
            "</div>",
            '<div class="bar">',
            '<button id="zoom-out" type="button">&minus; Zoom out</button>',
            '<button id="zoom-in" type="button">+ Zoom in</button>',
            '<button id="zoom-fit" type="button">Fit</button>',
            '<span class="level" id="zoom-level">100%</span>',
            '<span class="hint">Click a node for its agent note · hover a node to isolate its '
            "flow · hover an edge for the routing rule · drag to pan · +/&minus;/0 to zoom</span>",
            "</div>",
            '<div class="canvas">',
            f'<svg class="graph" id="graph" viewBox="0 0 {geo.width} {geo.height}" '
            f'width="{geo.width}" height="{geo.height}" '
            'xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="{html.escape(view.subtitle)}">',
            "<defs>",
        ]
    )
    parts.extend(
        [
            '<filter id="lift" x="-25%" y="-30%" width="150%" height="180%">',
            '<feDropShadow dx="0" dy="1.6" stdDeviation="2.2" flood-color="#1c1a16" '
            'flood-opacity="0.16"></feDropShadow>',
            "</filter>",
        ]
    )
    for marker, colour in _ARROW_COLOURS:
        parts.extend(
            [
                f'<marker id="arrow-{marker}" viewBox="0 0 10 10" refX="9" refY="5" '
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
