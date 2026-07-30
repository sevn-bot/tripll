"""tripll.api.ui.router — Dashboard page routes (W5 + W1 + W2 + W8).

Server-rendered HTML pages:

- ``GET /`` — runs home: launch-run form, runs list, backends (W2).
- ``GET /runs/{run_id}`` — run detail (W1).
- ``GET /agents``, ``/agents/new``, ``/agents/{id}/edit`` — profile CRUD (W2).
- ``GET /settings`` — runtime config form (W2).

Fragment routes (W1-W4):

- ``GET /runs/{run_id}/timeline`` — event timeline partial (W1.3).
- ``GET /runs/{run_id}/waves/{node_id}/log`` — log tail viewer (W1.4, D4).
- ``GET /runs/{run_id}/batch-timeline`` — batch swimlane chart (W4.1).
- ``GET /runs/{run_id}/report`` — report.md embed (W4.3).
- ``GET /runs/{run_id}/orchestrator`` — orchestrator panel + feed (W5).

Auth
----
When ``TRIPLL_API_TOKEN`` is set, the token is injected into the rendered
page (inside the EventSource URL query-parameter and htmx hx-headers) so the
browser can authenticate against the SSE and action endpoints.  Fragment GETs
accept the same ``?token=`` query param (D12).  In dev mode (no token)
everything works without credentials.

No Node / build toolchain
--------------------------
``htmx.min.js`` and ``htmx-sse.js`` are vendored under ``src/tripll/api/ui/static/``.
The CSS is minimal and fully inline inside the base template.

Exports:
    make_ui_router — factory that returns the configured ``APIRouter``.
    fragment_url — build htmx-safe fragment URLs (re-exported for tests).
    log_full_page_url — full-page log viewer URL helper.
    log_append_url — append-only log poll URL helper.
    log_fragment_url — log fragment URL helper.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

from tripll.api.ui._helpers import (
    fragment_url,
    log_append_url,
    log_fragment_url,
    log_full_page_url,
)
from tripll.api.ui._routes_agents import make_agents_router
from tripll.api.ui._routes_fragments import make_fragments_router
from tripll.api.ui._routes_runs import make_runs_router

_TEMPLATES_DIR = Path(__file__).parent / "templates"

__all__ = [
    "fragment_url",
    "log_append_url",
    "log_fragment_url",
    "log_full_page_url",
    "make_ui_router",
]


def make_ui_router() -> APIRouter:
    """Construct the dashboard ``APIRouter``.

    The returned router must be ``app.include_router(...)``'d from
    ``create_app()`` **after** ``app.state.runs_root`` is set.

    Returns:
        APIRouter: Router with dashboard and fragment routes.

    Examples:
        >>> from tripll.api.ui import make_ui_router
        >>> router = make_ui_router()
        >>> router.routes  # doctest: +ELLIPSIS
        [...]
    """
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["log_full_page_url"] = log_full_page_url

    router = APIRouter(include_in_schema=False)
    for factory in (make_runs_router, make_agents_router, make_fragments_router):
        router.routes.extend(factory(templates).routes)

    return router
