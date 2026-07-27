"""tripll.api.ui.errors — HTML-friendly HTTP error pages (W3.5).

Exports:
    register_html_exception_handlers — attach 401/403 HTML handlers to *app*.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _wants_html(request: Request) -> bool:
    """Return True when the client prefers an HTML error body."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return True
    path = request.url.path
    return not path.startswith("/api/")


def register_html_exception_handlers(app: FastAPI) -> None:
    """Register HTML 401/403 handlers for dashboard routes on *app*.

    Args:
        app (FastAPI): Application instance from :func:`~tripll.api.app.create_app`.
    """

    @app.exception_handler(HTTPException)
    async def html_http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> HTMLResponse | JSONResponse:
        if exc.status_code == 401 and _wants_html(request):
            detail = exc.detail if isinstance(exc.detail, str) else "Unauthorized."
            return _templates.TemplateResponse(
                request,
                "auth_required.html",
                {"detail": detail},
                status_code=401,
                headers=exc.headers,
            )
        if exc.status_code == 403 and _wants_html(request):
            detail = exc.detail if isinstance(exc.detail, str) else "Forbidden."
            return HTMLResponse(
                content=(
                    "<!DOCTYPE html><html><head><title>Forbidden</title></head>"
                    f"<body><h1>Forbidden</h1><p>{detail}</p></body></html>"
                ),
                status_code=403,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
