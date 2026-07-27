"""tripll.api._csrf — double-submit CSRF for HTML form POSTs (W3, R5).

When ``TRIPLL_API_TOKEN`` is set, mutating HTML form POSTs must carry a
``csrf_token`` field matching the ``tripll_csrf`` cookie set on prior GET
responses.  No server-side session store — the cookie + hidden field are the
whole state machine.

Exports:
    CSRF_COOKIE — cookie name holding the active token.
    CSRF_FORM_FIELD — form field name operators and templates must use.
    ensure_csrf_token — attach a per-request token on ``request.state``.
    require_csrf — FastAPI dependency; raises 403 on CSRF failure.
    apply_csrf_cookie — set the response cookie from ``request.state``.
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from starlette.responses import Response as StarletteResponse

CSRF_COOKIE = "tripll_csrf"
CSRF_FORM_FIELD = "csrf_token"


def _auth_enabled() -> bool:
    """Return whether Bearer auth is configured."""
    return bool(os.environ.get("TRIPLL_API_TOKEN", "").strip())


def ensure_csrf_token(request: Request) -> str:
    """Return the CSRF token for *request*, generating one when absent.

    The token is stored on ``request.state.csrf_token`` so middleware can
    mirror it into the ``tripll_csrf`` cookie on HTML responses.

    Args:
        request (Request): Active FastAPI request.

    Returns:
        str: URL-safe CSRF token.
    """
    existing = getattr(request.state, "csrf_token", None)
    if isinstance(existing, str) and existing:
        return existing
    token = secrets.token_urlsafe(32)
    request.state.csrf_token = token
    return token


def apply_csrf_cookie(request: Request, response: StarletteResponse) -> None:
    """Set ``tripll_csrf`` on *response* when a token was prepared for *request*.

    Args:
        request (Request): Active FastAPI request.
        response (StarletteResponse): Outgoing response to mutate.
    """
    if not _auth_enabled():
        return
    token = getattr(request.state, "csrf_token", None)
    if not isinstance(token, str) or not token:
        return
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        samesite="lax",
        secure=False,
    )


async def require_csrf(request: Request) -> None:
    """FastAPI dependency enforcing double-submit CSRF on mutating HTML POSTs.

    Skipped entirely when ``TRIPLL_API_TOKEN`` is unset (R4 open dev mode) or
    the method is not state-changing.

    Args:
        request (Request): Incoming FastAPI request.

    Raises:
        HTTPException: 403 when the form field is missing or does not match the
            ``tripll_csrf`` cookie.
    """
    if not _auth_enabled():
        return
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return

    form = await request.form()
    form_token = str(form.get(CSRF_FORM_FIELD, "")).strip()
    cookie_token = request.cookies.get(CSRF_COOKIE, "").strip()

    if not form_token:
        raise HTTPException(status_code=403, detail="CSRF token missing.")
    if not cookie_token or form_token != cookie_token:
        raise HTTPException(status_code=403, detail="CSRF token invalid.")
