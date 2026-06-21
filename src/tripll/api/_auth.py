"""tripll.api._auth — Bearer-token authentication dependency (W4 + W5).

Auth model:
- If ``TRIPLL_API_TOKEN`` env var is set: all requests must supply a valid
  ``Authorization: Bearer <token>`` header **or** a matching ``?token=`` query
  parameter (needed for browser ``EventSource`` SSE connections that cannot set
  custom headers); non-matching tokens get 401.
- If ``TRIPLL_API_TOKEN`` is unset: requests are **allowed without auth**
  (dev/localhost mode — document this clearly; the server binds to localhost
  by default, so the risk surface is low).

Exports:
    require_auth — FastAPI dependency; raises 401 on auth failure.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request


async def require_auth(
    request: Request,
) -> None:
    """FastAPI dependency that enforces Bearer-token auth when configured.

    If ``TRIPLL_API_TOKEN`` is set in the environment, the request must
    include either:

    - A matching ``Authorization: Bearer <token>`` header, **or**
    - A matching ``?token=<token>`` query parameter (for browser ``EventSource``
      clients that cannot set custom headers, e.g. the dashboard SSE feed).

    If the env var is unset the request is allowed without auth (dev mode —
    the server defaults to localhost-only binding, so the exposure is minimal).

    Args:
        request (Request): The incoming FastAPI request.

    Raises:
        HTTPException: 401 when a token is configured but the request fails
            to supply a matching bearer token or ``?token=`` parameter.

    Examples:
        This function is used as a FastAPI dependency::

            @app.get("/protected")
            async def endpoint(_auth: None = Depends(require_auth)):
                ...
    """
    configured = os.environ.get("TRIPLL_API_TOKEN", "").strip()
    if not configured:
        # Dev mode — no token configured; allow all.
        return

    # 1. Check Authorization: Bearer header.
    auth_header = request.headers.get("Authorization", "")
    from_header = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    if from_header and from_header == configured:
        return

    # 2. Fall back to ?token= query parameter (browser EventSource support).
    from_query = request.query_params.get("token", "").strip()
    if from_query and from_query == configured:
        return

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
