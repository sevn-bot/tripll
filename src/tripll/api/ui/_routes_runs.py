"""tripll.api.ui._routes_runs — dashboard home, launch, and run-detail routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates  # noqa: TC002

from tripll.api._auth import require_auth
from tripll.api._csrf import require_csrf
from tripll.api._inject import parse_owned_paths, run_hotfix_inject
from tripll.api._runs import RunSummary, _list_all_runs
from tripll.api.deps import _read_config, _tripll_argv
from tripll.api.ui._helpers import _build_run_detail_context, _ui_context
from tripll.api.ui.router import asyncio, subprocess
from tripll.inject import InjectError
from tripll.pipeline import RunsRoot  # noqa: TC001
from tripll.profiles import control_plane_db_path, get_profile, list_profiles, open_profile_store


def make_runs_router(templates: Jinja2Templates) -> APIRouter:
    """Register run dashboard routes on a fresh ``APIRouter``."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET / — dashboard home
    # ------------------------------------------------------------------

    @router.get("/", response_class=HTMLResponse)
    async def dashboard_home(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the dashboard home page.

        Displays all runs (active, processed, failed), agent profiles, and
        backend availability.

        Args:
            request (Request): Incoming FastAPI request (needed by Jinja2).

        Returns:
            HTMLResponse: Rendered ``index.html`` template.
        """
        rr: RunsRoot = request.app.state.runs_root

        # Runs.
        runs: list[RunSummary] = _list_all_runs(rr)

        # Agent profiles.
        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with open_profile_store(db_path) as store:
            profiles = list_profiles(store)

        # Backends — import lazily so ui router doesn't force adapters at import time.
        from tripll.adapters import BACKENDS, get_adapter

        backends: list[dict[str, Any]] = []
        for name in sorted(BACKENDS):
            try:
                adapter = get_adapter(name)
                caps = adapter.capabilities()
                backends.append(
                    {
                        "name": name,
                        "available": caps.available,
                        "detail": caps.detail,
                        "streaming": caps.streaming,
                    }
                )
            except Exception as exc:
                backends.append(
                    {"name": name, "available": False, "detail": str(exc), "streaming": False}
                )

        ctx: dict[str, Any] = _ui_context(
            request,
            nav_section="runs",
            runs=runs,
            profiles=profiles,
            backends=backends,
            input_sets=rr.list_input(),
        )
        return templates.TemplateResponse(request, "index.html", ctx)

    # ------------------------------------------------------------------
    # POST /launch — launch run form (W2.3)
    # ------------------------------------------------------------------

    @router.post("/launch")
    async def launch_run_form(
        request: Request,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Accept launch-run form POST; spawn engine and redirect to run detail."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        input_path_str = str(form.get("input_path_custom", "")).strip()
        if not input_path_str:
            input_path_str = str(form.get("input_path", "")).strip()
        profile_id = str(form.get("profile_id", "")).strip()

        if not input_path_str or not profile_id:
            return RedirectResponse("/", status_code=303)

        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                profile = get_profile(store, profile_id)
            except KeyError:
                return RedirectResponse("/", status_code=303)

        input_path = Path(input_path_str)
        if not input_path.exists():  # noqa: ASYNC240
            return RedirectResponse("/", status_code=303)

        argv = [
            *_tripll_argv(),
            "run",
            str(input_path),
            "--backend",
            profile.backend,
            "--model",
            profile.model,
            "--agent",
            profile.agent,
            "--runs-root",
            str(rr.root),
        ]
        subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        slug = input_path.name
        for _ in range(15):
            await asyncio.sleep(0.2)
            runs: list[RunSummary] = _list_all_runs(rr)
            for run in reversed(runs):
                if run.slug == slug and run.is_live:
                    return RedirectResponse(f"/runs/{run.run_id}", status_code=303)

        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------------
    # GET /runs/{run_id} — run detail
    # ------------------------------------------------------------------

    @router.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(
        request: Request,
        run_id: str,
        inject_msg: str | None = None,
        inject_open: int | None = None,
        pr_msg: str | None = None,
        pr_open: int | None = None,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the hydrated run-detail page for *run_id* (W1.1).

        Shows a per-wave table merged with ``latest_events_by_node`` (D2),
        run header, event timeline replay, and live SSE row updates.

        Args:
            request (Request): Incoming FastAPI request.
            run_id (str): Run identifier.

        Returns:
            HTMLResponse: Rendered ``run_detail.html`` template.

        Raises:
            HTTPException: 404 when the run is not found.
        """
        rr: RunsRoot = request.app.state.runs_root
        ctx = _build_run_detail_context(rr, run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        ctx.update(_ui_context(request, nav_section="runs"))
        ctx["sse_url"] = f"/api/runs/{run_id}/events/stream"
        ctx["inject_flash"] = inject_msg or ""
        ctx["inject_panel_open"] = inject_open == 1
        ctx["pr_flash"] = pr_msg or ""
        ctx["pr_panel_open"] = pr_open == 1
        return templates.TemplateResponse(request, "run_detail.html", ctx)

    @router.post("/runs/{run_id}/pr/approve-merge")
    async def pr_approve_merge_form(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Record operator merge-gate approval from dashboard form POST."""
        from tripll.loops.l1_pr import approve_merge_gate

        rr: RunsRoot = request.app.state.runs_root
        run_dir = rr.find_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        try:
            approve_merge_gate(run_dir=run_dir)
        except FileNotFoundError as exc:
            msg = quote(str(exc))
            return RedirectResponse(
                f"/runs/{run_id}?pr_msg={msg}&pr_open=1",
                status_code=303,
            )
        return RedirectResponse(
            f"/runs/{run_id}?pr_msg={quote('Merge gate approved')}&pr_open=1",
            status_code=303,
        )

    @router.post("/runs/{run_id}/inject")
    async def inject_run_form(
        request: Request,
        run_id: str,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Apply hotfix inject from dashboard form POST."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        brief = str(form.get("brief", "")).strip()
        owned_raw = str(form.get("owned_paths", "")).strip()
        after = str(form.get("after", "")).strip()
        verify_raw = str(form.get("verify_target", "")).strip()
        verify_target = verify_raw or None
        dry_run = form.get("dry_run") == "1"
        owned = parse_owned_paths(owned_raw)

        if not brief or not owned or not after:
            msg = quote("Missing required fields (brief, paths, after wave)")
            return RedirectResponse(
                f"/runs/{run_id}?inject_msg={msg}&inject_open=1",
                status_code=303,
            )
        try:
            run_hotfix_inject(
                rr,
                run_id,
                brief=brief,
                owned_paths=owned,
                after=after,
                verify_target=verify_target,
                dry_run=dry_run,
                injected_by="dashboard",
                cost_budget_usd=_read_config().cost_budget_usd,
            )
        except InjectError as exc:
            return RedirectResponse(
                f"/runs/{run_id}?inject_msg={quote(str(exc))}&inject_open=1",
                status_code=303,
            )
        label = quote("Dry-run OK — no changes written" if dry_run else "Inject applied")
        return RedirectResponse(
            f"/runs/{run_id}?inject_msg={label}&inject_open=1",
            status_code=303,
        )

    return router
