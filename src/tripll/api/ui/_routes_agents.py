"""tripll.api.ui._routes_agents — agent profile and settings dashboard routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates  # noqa: TC002

from tripll.api._auth import require_auth
from tripll.api._csrf import require_csrf
from tripll.api.deps import _read_config
from tripll.api.models import _slug_profile_id
from tripll.api.ui._helpers import (
    _backend_names,
    _empty_profile_form,
    _parse_agent_form,
    _profile_form_from_row,
    _ui_context,
)
from tripll.pipeline import RunsRoot  # noqa: TC001
from tripll.profiles import (
    control_plane_db_path,
    get_profile,
    list_profiles,
    open_profile_store,
    upsert_profile,
)


def make_agents_router(templates: Jinja2Templates) -> APIRouter:
    """Register agent and settings routes on a fresh ``APIRouter``."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /agents — profile list (W2.4)
    # ------------------------------------------------------------------

    @router.get("/agents", response_class=HTMLResponse)
    async def agents_list(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the agent profiles list page."""
        rr: RunsRoot = request.app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with open_profile_store(db_path) as store:
            profiles = list_profiles(store)
        ctx = _ui_context(request, nav_section="agents", profiles=profiles)
        return templates.TemplateResponse(request, "agents.html", ctx)

    # ------------------------------------------------------------------
    # GET/POST /agents/new — create profile (W2.4)
    # ------------------------------------------------------------------

    @router.get("/agents/new", response_class=HTMLResponse)
    async def agents_new_form(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the new-agent profile form."""
        ctx = _ui_context(
            request,
            nav_section="agents",
            form_title="New agent profile",
            form_action="/agents/new",
            submit_label="Create profile",
            is_new=True,
            profile=_empty_profile_form(),
            backends=_backend_names(),
        )
        return templates.TemplateResponse(request, "agent_form.html", ctx)

    @router.post("/agents/new")
    async def agents_new_submit(
        request: Request,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Create an agent profile from form POST."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        parsed = _parse_agent_form(form)
        if parsed is None:
            return RedirectResponse("/agents/new", status_code=303)

        db_path = control_plane_db_path(rr.root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        raw_id = str(form.get("profile_id", "")).strip()
        profile_id = _slug_profile_id(raw_id) if raw_id else _slug_profile_id(parsed["name"])

        with open_profile_store(db_path) as store:
            try:
                get_profile(store, profile_id)
            except KeyError:
                pass
            else:
                base_id = profile_id
                suffix = 1
                while True:
                    try:
                        get_profile(store, profile_id)
                        profile_id = f"{base_id}-{suffix}"
                        suffix += 1
                    except KeyError:
                        break
            upsert_profile(store, profile_id=profile_id, **parsed)

        return RedirectResponse("/agents", status_code=303)

    # ------------------------------------------------------------------
    # GET/POST /agents/{profile_id}/edit — edit profile (W2.4)
    # ------------------------------------------------------------------

    @router.get("/agents/{profile_id}/edit", response_class=HTMLResponse)
    async def agents_edit_form(
        request: Request,
        profile_id: str,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the edit-agent profile form."""
        rr: RunsRoot = request.app.state.runs_root
        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                row = get_profile(store, profile_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail=f"Profile not found: {profile_id}"
                ) from exc

        ctx = _ui_context(
            request,
            nav_section="agents",
            form_title=f"Edit {row.name}",
            form_action=f"/agents/{profile_id}/edit",
            submit_label="Save changes",
            is_new=False,
            profile=_profile_form_from_row(row),
            backends=_backend_names(),
        )
        return templates.TemplateResponse(request, "agent_form.html", ctx)

    @router.post("/agents/{profile_id}/edit")
    async def agents_edit_submit(
        request: Request,
        profile_id: str,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Update an agent profile from form POST."""
        rr: RunsRoot = request.app.state.runs_root
        form = await request.form()
        parsed = _parse_agent_form(form)
        if parsed is None:
            return RedirectResponse(f"/agents/{profile_id}/edit", status_code=303)

        db_path = control_plane_db_path(rr.root)
        with open_profile_store(db_path) as store:
            try:
                get_profile(store, profile_id)
            except KeyError:
                return RedirectResponse("/agents", status_code=303)
            upsert_profile(store, profile_id=profile_id, **parsed)

        return RedirectResponse("/agents", status_code=303)

    # ------------------------------------------------------------------
    # GET/POST /settings — runtime config (W2.5)
    # ------------------------------------------------------------------

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(
        request: Request,
        _auth: None = Depends(require_auth),
    ) -> HTMLResponse:
        """Render the settings form bound to runtime config env vars."""
        saved = request.query_params.get("saved") == "1"
        ctx = _ui_context(request, nav_section="settings", config=_read_config(), saved=saved)
        return templates.TemplateResponse(request, "settings.html", ctx)

    @router.post("/settings")
    async def settings_submit(
        request: Request,
        _auth: None = Depends(require_auth),
        _csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """Update runtime config from form POST."""
        form = await request.form()
        model_default = str(form.get("model_default", "")).strip()
        if model_default:
            os.environ["TRIPLL_DEFAULT_MODEL"] = model_default
        cost_raw = str(form.get("cost_budget_usd", "")).strip()
        if cost_raw:
            os.environ["TRIPLL_COST_BUDGET_USD"] = cost_raw
        max_raw = str(form.get("max_parallel", "")).strip()
        if max_raw:
            os.environ["TRIPLL_MAX_PARALLEL"] = max_raw
        return RedirectResponse("/settings?saved=1", status_code=303)

    return router
