"""tripll.api.app — FastAPI control-plane application factory (W4 + W5 + W7).

Implements the full HTTP API surface defined in ``docs/control-plane-design.md``
§6.  All state reads open the ledger read-only; run-mutating operations
(launch, approve, resume, pause) spawn the ``tripll`` CLI as a detached
subprocess so runs **outlive the server**.

In addition, W5 mounts the Jinja2 + htmx + SSE web dashboard:

- ``GET /`` — dashboard home (runs list, profiles, backends).
- ``GET /runs/{run_id}`` — run detail with live per-agent wave table.
- Static assets served from ``/static/`` (htmx vendored; zero Node build).

Auth model
----------
A single Bearer token read from the ``TRIPLL_API_TOKEN`` environment
variable.  If the env var is unset, localhost requests are allowed without
auth (dev mode).  All other origins require the token.

For the SSE endpoint (``GET /api/runs/{id}/events/stream``), browsers cannot
set custom ``Authorization`` headers on ``EventSource``.  When a token is set
the dashboard injects it as a ``?token=`` query parameter; the SSE handler
accepts either ``Authorization: Bearer <tok>`` or ``?token=<tok>``.

Process model (§1)
-------------------
``POST /api/runs`` and ``POST /api/runs/{id}/approve|resume`` spawn
``tripll <subcmd>`` via ``subprocess.Popen(start_new_session=True)``.
The child PID is written to ``<run_dir>/engine.pid``.  A run is "live" if
``engine.pid`` exists and the PID is alive.

Exports:
    create_app — construct and return the configured FastAPI instance.
    _resolve_runs_root — resolve runs root (re-exported for tests / W8).
    _read_config — read runtime config (re-exported for ui/router.py).
    _slug_profile_id — slugify profile ids (re-exported for ui/router.py).
    _tripll_argv — base CLI argv (re-exported for ui/router.py).
"""

from __future__ import annotations

import subprocess
from pathlib import Path  # noqa: TC003

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from tripll.api._worktree_status import (
    collect_worktree_status,
    resolve_wave_worktree_path,
)
from tripll.api.deps import _read_config, _resolve_runs_root, _tripll_argv
from tripll.api.models import _slug_profile_id

__all__ = [
    "_read_config",
    "_resolve_runs_root",
    "_slug_profile_id",
    "_tripll_argv",
    "collect_worktree_status",
    "create_app",
    "resolve_wave_worktree_path",
    "subprocess",
]


def create_app(
    *,
    runs_root: Path | None = None,
) -> FastAPI:
    """Construct and return the configured FastAPI application.

    Args:
        runs_root (Path | None): Override the runs root directory.  Defaults to
            the ``TRIPLL_RUNS`` env var or ``<repo_root>/runs/``.

    Returns:
        FastAPI: Configured application instance.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> app = create_app(runs_root=None)
        >>> client = TestClient(app)
        >>> client.get("/health").status_code
        200
    """
    app = FastAPI(
        title="tripll control plane",
        description=(
            "FastAPI control plane for the wave-orchestrator.  "
            "Launches, observes, and controls headless wave-plan runs."
        ),
        version="0.5.0",
    )

    app.state.runs_root = _resolve_runs_root(runs_root)

    from tripll.api.ui import make_ui_router, static_path

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    app.include_router(make_ui_router())

    from tripll.api.ui.errors import register_html_exception_handlers

    register_html_exception_handlers(app)

    from tripll.api._auth import apply_auth_cookie
    from tripll.api._csrf import apply_csrf_cookie
    from tripll.api.routes import agents, config, events, runs, waves

    @app.middleware("http")
    async def csrf_cookie_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Mirror CSRF + auth cookies after HTML GETs (W3, R5, H3)."""
        response = await call_next(request)
        apply_csrf_cookie(request, response)
        apply_auth_cookie(request, response)
        return response

    for router in (agents.router, runs.router, waves.router, events.router, config.router):
        app.router.routes.extend(router.routes)

    return app
