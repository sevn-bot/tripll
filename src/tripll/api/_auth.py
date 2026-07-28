"""tripll.api._auth — Bearer-token authentication dependency (W4 + W5).

Auth model:
- If ``TRIPLL_API_TOKEN`` env var is set: all requests must supply a valid
  ``Authorization: Bearer <token>`` header, a matching ``?token=`` query
  parameter (EventSource), or a matching ``tripll_api_token`` cookie (plain
  HTML navigation after an initial authenticated GET).
- If ``TRIPLL_API_TOKEN`` is unset: requests are **allowed without auth**
  (dev/localhost mode — document this clearly; the server binds to localhost
  by default, so the risk surface is low).

Exports:
    AUTH_COOKIE — cookie name holding the API token for browser navigation.
    require_auth — FastAPI dependency; raises 401 on auth failure.
    apply_auth_cookie — set the auth cookie after a successful authenticated GET.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from starlette.responses import Response as StarletteResponse

AUTH_COOKIE = "tripll_api_token"


def _configured_token() -> str:
    """Return the configured API token, or empty string in dev mode."""
    return os.environ.get("TRIPLL_API_TOKEN", "").strip()


def _token_matches(configured: str, candidate: str) -> bool:
    """Return whether *candidate* equals the configured token."""
    return bool(candidate) and candidate == configured


async def require_auth(
    request: Request,
) -> None:
    """FastAPI dependency that enforces Bearer-token auth when configured."""
    configured = _configured_token()
    if not configured:
        return

    auth_header = request.headers.get("Authorization", "")
    from_header = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    if _token_matches(configured, from_header):
        request.state.auth_ok = True
        return

    from_query = request.query_params.get("token", "").strip()
    if _token_matches(configured, from_query):
        request.state.auth_ok = True
        return

    from_cookie = request.cookies.get(AUTH_COOKIE, "").strip()
    if _token_matches(configured, from_cookie):
        request.state.auth_ok = True
        return

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def apply_auth_cookie(request: Request, response: StarletteResponse) -> None:
    """Persist auth in a cookie after a successful authenticated HTML GET."""
    configured = _configured_token()
    if not configured:
        return
    if not getattr(request.state, "auth_ok", False):
        return
    if request.method not in {"GET", "HEAD"}:
        return
    response.set_cookie(
        AUTH_COOKIE,
        configured,
        httponly=True,
        samesite="lax",
        secure=False,
    )
