"""tripll.api.ui — Jinja2 + htmx + SSE web dashboard (W5).

Server-rendered pages progressively enhanced with htmx.  Zero Node/JS build
toolchain — static assets (htmx, minimal CSS) are vendored under ``static/``.

Exports:
    make_ui_router — construct and return a FastAPI ``APIRouter`` with the
        dashboard routes mounted.  Call this from ``create_app`` and include
        the returned router.
    templates_path — ``Path`` to the ``templates/`` directory.
    static_path — ``Path`` to the ``static/`` directory.
"""

from __future__ import annotations

from pathlib import Path

from .router import make_ui_router

__all__ = ["make_ui_router"]

templates_path: Path = Path(__file__).parent / "templates"
static_path: Path = Path(__file__).parent / "static"
