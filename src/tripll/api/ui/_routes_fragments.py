"""tripll.api.ui._routes_fragments — htmx partial routes for the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates  # noqa: TC002

from tripll.api._artefacts import (
    MAX_LOG_FULL_BYTES,
    MAX_LOG_PANEL_BYTES,
    LogPathError,
    parse_escalation_reasons,
    read_log_file,
    read_log_file_from_offset,
    read_report_markdown,
    render_report_markdown,
    resolve_attempt_log_path,
    tail_log_file,
)
from tripll.api._auth import require_auth
from tripll.api._runs import _find_ledger
from tripll.api.ui._helpers import (
    _build_batch_timeline_context,
    _build_orchestrator_fragment_context,
    _build_run_detail_context,
    _build_tasks_fragment_context,
    _build_worktree_fragment_context,
    _get_token,
    _get_wave_row,
    _timeline_events,
    _ui_context,
    _wave_status_detail,
    log_append_url,
    log_full_page_url,
)
from tripll.ledger import latest_events_by_node, list_attempts, open_ledger
from tripll.pipeline import RunsRoot  # noqa: TC001


def make_fragments_router(templates: Jinja2Templates) -> APIRouter:
    """Register htmx fragment routes on a fresh ``APIRouter``."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # Fragment routes (timeline, log, worktree, tasks, batch-timeline, report)
    # ------------------------------------------------------------------

    @router.get("/runs/{run_id}/timeline", response_class=HTMLResponse)
    async def run_timeline_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Scrollable event timeline partial (W1.3, D3)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        with open_ledger(ledger_path) as lc:
            timeline_events = _timeline_events(lc, run_id)
        return templates.TemplateResponse(
            request,
            "_timeline.html",
            {"timeline_events": timeline_events},
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/log", response_class=HTMLResponse)
    async def wave_log_fragment(
        request: Request,
        run_id: str,
        node_id: str,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Per-wave log tail viewer partial (W1.4, D4). Accepts ``?token=`` when auth set (D12)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
                latest = latest_events_by_node(lc, run_id).get(node_id)
                wave = _get_wave_row(lc, run_id, node_id)
            if not attempts:
                run_dir = rr.find_run_dir(run_id)
                escalation_reasons = parse_escalation_reasons(run_dir)
                phase = latest.phase if latest is not None else (wave.state if wave else "queued")
                last_action = latest.last_action if latest and latest.last_action else ""
                status_detail = _wave_status_detail(
                    node_id=node_id,
                    wave_id=wave.wave_id if wave else node_id.split(":")[-1],
                    phase=phase,
                    last_action=last_action,
                    attempts=[],
                    escalation_reasons=escalation_reasons,
                )
                log_message = status_detail or "No agent log yet — wave not dispatched."
                return templates.TemplateResponse(
                    request,
                    "_log_viewer.html",
                    {
                        "attempt_n": None,
                        "log_content": log_message,
                        "truncated": False,
                        "log_available": False,
                    },
                )
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            content, truncated = tail_log_file(log_path, max_bytes=MAX_LOG_PANEL_BYTES)
            log_byte_offset = log_path.stat().st_size
        except LogPathError:
            return templates.TemplateResponse(
                request,
                "_log_viewer.html",
                {
                    "attempt_n": attempt_n,
                    "log_content": (
                        f"Log file missing for attempt {attempt_n} (engine may still be writing)."
                    ),
                    "truncated": False,
                    "log_available": False,
                },
            )

        token = _get_token()
        return templates.TemplateResponse(
            request,
            "_log_viewer.html",
            {
                "attempt_n": attempt_n,
                "log_content": content,
                "truncated": truncated,
                "log_available": True,
                "run_id": run_id,
                "node_id": node_id,
                "full_log_url": log_full_page_url(
                    run_id,
                    node_id,
                    attempt_n,
                    api_token=token,
                ),
                "log_append_url": log_append_url(run_id, node_id, api_token=token),
                "log_byte_offset": log_byte_offset,
            },
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/log/append")
    async def wave_log_append(
        request: Request,
        run_id: str,
        node_id: str,
        offset: int = 0,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> JSONResponse:
        """Append-only log bytes for live panel polling (preserves scroll position)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
            if not attempts:
                return JSONResponse({"text": "", "offset": 0, "truncated": False})
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            text, new_offset, truncated = read_log_file_from_offset(log_path, offset)
        except LogPathError:
            return JSONResponse({"text": "", "offset": offset, "truncated": False})

        return JSONResponse(
            {
                "text": text,
                "offset": new_offset,
                "truncated": truncated,
                "attempt_n": attempt_n,
            }
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/log/full", response_class=HTMLResponse)
    async def wave_log_full_page(
        request: Request,
        run_id: str,
        node_id: str,
        attempt: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Full attempt log in a standalone page (opens in new tab)."""
        rr: RunsRoot = request.app.state.runs_root
        ledger_path = _find_ledger(rr, run_id)
        if ledger_path is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        attempt_n = attempt
        if attempt_n is None:
            with open_ledger(ledger_path) as lc:
                attempts = list_attempts(lc, run_id, node_id)
            if not attempts:
                raise HTTPException(status_code=404, detail="No attempts for this wave")
            attempt_n = attempts[-1].attempt_n

        try:
            log_path = resolve_attempt_log_path(rr, run_id, node_id, attempt_n)
            content, truncated = read_log_file(log_path, max_bytes=MAX_LOG_FULL_BYTES)
        except LogPathError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return templates.TemplateResponse(
            request,
            "log_full.html",
            {
                "run_id": run_id,
                "node_id": node_id,
                "attempt_n": attempt_n,
                "log_content": content,
                "truncated": truncated,
                "full_log_url": None,
                "log_available": True,
                **_ui_context(request, nav_section="runs"),
            },
        )

    @router.get("/runs/{run_id}/waves-table", response_class=HTMLResponse)
    async def waves_table_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Refreshable waves table body for SSE terminal-state sync."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_run_detail_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(
            request,
            "_waves_tbody.html",
            ctx,
        )

    @router.get("/runs/{run_id}/waves/{node_id:path}/worktree", response_class=HTMLResponse)
    async def wave_worktree_fragment(
        request: Request,
        run_id: str,
        node_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Git worktree status partial (W3.4, D5). Poll every 5s while running."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_worktree_fragment_context(rr, run_id, node_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_worktree_panel.html", ctx)

    @router.get("/runs/{run_id}/waves/{node_id:path}/tasks", response_class=HTMLResponse)
    async def wave_tasks_fragment(
        request: Request,
        run_id: str,
        node_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Wave-task checklist partial (W3.3, D6). Reload on SSE ``last_action`` change."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_tasks_fragment_context(rr, run_id, node_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_wave_tasks.html", ctx)

    @router.get("/runs/{run_id}/batch-timeline", response_class=HTMLResponse)
    async def batch_timeline_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Batch swimlane partial from ``graph.json`` / ``report.md`` (W4.1, D9)."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_batch_timeline_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_batch_timeline.html", ctx)

    @router.get("/runs/{run_id}/report", response_class=HTMLResponse)
    async def run_report_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Rendered ``report.md`` embed partial (W4.3)."""
        rr: RunsRoot = request.app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        report_text = read_report_markdown(run_dir)
        if report_text is None:
            raise HTTPException(status_code=404, detail="report.md not found")
        return templates.TemplateResponse(
            request,
            "_report.html",
            {"report_html": render_report_markdown(report_text)},
        )

    @router.get("/runs/{run_id}/orchestrator", response_class=HTMLResponse)
    async def run_orchestrator_fragment(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Orchestrator panel + turn feed partial (W5.3, D13)."""
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_orchestrator_fragment_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return templates.TemplateResponse(request, "_orchestrator.html", ctx)

    return router
