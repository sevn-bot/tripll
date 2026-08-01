"""tripll.api.routes.events — event poll and SSE stream routes."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from tripll.api._auth import require_auth
from tripll.api._runs import _find_ledger
from tripll.api.deps import _event_out, _event_payload
from tripll.api.models import EventOut
from tripll.ledger import get_run, list_events, open_ledger
from tripll.pipeline import RunsRoot  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter()


@router.get("/api/runs/{run_id}/events", response_model=list[EventOut], tags=["events"])
async def poll_events(
    run_id: str,
    request: Request,
    after: int = 0,
    _auth: None = Depends(require_auth),
) -> list[EventOut]:
    """Poll events for a run (paged by event_id cursor).

    Args:
        run_id (str): Parent run identifier.
        after (int): Return only events with ``event_id > after`` (default 0 = all).

    Returns:
        list[EventOut]: Events ordered by event_id ascending.

    Raises:
        HTTPException: 404 if run not found.
    """
    rr: RunsRoot = request.app.state.runs_root
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    with open_ledger(ledger_path) as lc:
        events = list_events(lc, run_id, after_event_id=after)
        return [_event_out(rr, lc, e) for e in events]


@router.get("/api/runs/{run_id}/events/stream", tags=["events"])
async def stream_events(
    run_id: str,
    request: Request,
    after: int = 0,
    token: str | None = None,
    _auth: None = Depends(require_auth),
) -> StreamingResponse:
    """Server-Sent Events stream for live run events.

    Replays events from ``after`` / ``Last-Event-ID`` header, then polls
    for new events every second until the client disconnects.  Each SSE
    event carries the JSON-encoded :class:`EventOut` payload.

    The ``id:`` field of each SSE event is the ``event_id`` so browsers
    and clients can resume with ``Last-Event-ID`` across reconnects.

    Auth note: browsers cannot set ``Authorization`` headers on
    ``EventSource``.  When ``TRIPLL_API_TOKEN`` is set the dashboard
    injects the token as ``?token=<tok>``; the ``require_auth`` dependency
    checks ``Authorization: Bearer`` first, then falls back to the ``token``
    query parameter so the web UI can authenticate.

    Args:
        run_id (str): Parent run identifier.
        request (Request): FastAPI request (used to detect disconnect).
        after (int): Start cursor; overridden by ``Last-Event-ID`` header.
        token (str | None): Optional query-param bearer token for browser
            ``EventSource`` clients that cannot set custom headers.

    Returns:
        StreamingResponse: text/event-stream response.

    Raises:
        HTTPException: 404 if run not found.
    """
    rr: RunsRoot = request.app.state.runs_root
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    last_id_header = request.headers.get("Last-Event-ID")
    cursor = int(last_id_header) if last_id_header else after

    async def _event_generator() -> AsyncIterator[str]:
        nonlocal cursor, ledger_path
        try:
            poll_interval = float(os.environ.get("TRIPLL_SSE_POLL", "1.0") or "1.0")
        except ValueError:
            poll_interval = 1.0
        while True:
            if await request.is_disconnected():
                break
            with open_ledger(ledger_path) as lc:
                events = list_events(lc, run_id, after_event_id=cursor)
                if not events:
                    try:
                        row = get_run(lc, run_id)
                        if row.state in ("done", "failed", "paused"):
                            break
                    except KeyError:
                        break
                for e in events:
                    payload = json.dumps(_event_payload(rr, lc, e))
                    yield f"id: {e.event_id}\ndata: {payload}\n\n"
                    cursor = e.event_id
            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
