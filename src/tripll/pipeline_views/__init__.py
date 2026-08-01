"""tripll.pipeline_views — render pipeline files as self-contained HTML graphs.

Given a :class:`~tripll.pipeline_spec.PipelineSpec` (loaded from a
``pipeline_format = 1`` file), this package derives two complementary charts and
renders either as one offline HTML document:

* **execution** — steps are nodes (agents, system phases, human gates) and the
  declared transitions are edges, including retry loops and feedback paths.
* **state** — the artifact states are nodes and every edge is the step work that
  moves the pipeline from one state to the next.

The seams: :mod:`._model` is the geometry-free view, :mod:`._derive` builds it
from a spec, :mod:`._layout` places it and routes its edges, and :mod:`._render`
writes the document.

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

from tripll.pipeline_views._derive import VIEWS, execution_view, state_view
from tripll.pipeline_views._model import (
    DetailCard,
    NodeDetail,
    PipelineView,
    ViewCluster,
    ViewEdge,
    ViewNode,
)
from tripll.pipeline_views._render import render_view_html, write_view_html

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
