"""tripll.api.routes.agents — agent profile CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from tripll.api._auth import require_auth
from tripll.api.models import ProfileIn, ProfileOut, ProfilePatch, _slug_profile_id
from tripll.pipeline import RunsRoot  # noqa: TC001
from tripll.profiles import (
    control_plane_db_path,
    delete_profile,
    get_profile,
    list_profiles,
    open_profile_store,
    upsert_profile,
)

router = APIRouter()


@router.get("/api/agents", response_model=list[ProfileOut], tags=["agents"])
async def list_agents(
    request: Request,
    _auth: None = Depends(require_auth),
) -> list[ProfileOut]:
    """List all agent profiles.

    Returns:
        list[ProfileOut]: All profiles ordered by creation time.
    """
    rr: RunsRoot = request.app.state.runs_root
    db_path = control_plane_db_path(rr.root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open_profile_store(db_path) as store:
        profiles = list_profiles(store)
    return [ProfileOut.from_row(p) for p in profiles]


@router.post("/api/agents", response_model=ProfileOut, status_code=201, tags=["agents"])
async def create_agent(
    data: ProfileIn,
    request: Request,
    _auth: None = Depends(require_auth),
) -> ProfileOut:
    """Create a new agent profile.

    Args:
        data (ProfileIn): Profile configuration.

    Returns:
        ProfileOut: The created profile.
    """
    rr: RunsRoot = request.app.state.runs_root
    db_path = control_plane_db_path(rr.root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    explicit = data.profile_id is not None
    profile_id = _slug_profile_id(data.profile_id if data.profile_id is not None else data.name)
    with open_profile_store(db_path) as store:
        if explicit:
            try:
                get_profile(store, profile_id)
            except KeyError:
                pass
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"Profile already exists: {profile_id}",
                )
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
        row = upsert_profile(
            store,
            profile_id=profile_id,
            name=data.name,
            backend=data.backend,
            model=data.model,
            agent=data.agent,
            skills=data.skills,
            scope=data.scope,
        )
    return ProfileOut.from_row(row)


@router.get("/api/agents/{profile_id}", response_model=ProfileOut, tags=["agents"])
async def get_agent(
    profile_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> ProfileOut:
    """Fetch a single agent profile by ID.

    Args:
        profile_id (str): Profile primary key.

    Returns:
        ProfileOut: The profile.

    Raises:
        HTTPException: 404 if not found.
    """
    rr: RunsRoot = request.app.state.runs_root
    db_path = control_plane_db_path(rr.root)
    with open_profile_store(db_path) as store:
        try:
            row = get_profile(store, profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}") from exc
    return ProfileOut.from_row(row)


@router.patch("/api/agents/{profile_id}", response_model=ProfileOut, tags=["agents"])
async def patch_agent(
    profile_id: str,
    data: ProfilePatch,
    request: Request,
    _auth: None = Depends(require_auth),
) -> ProfileOut:
    """Partially update an agent profile.

    Only supplied fields are updated; omitted fields are preserved.

    Args:
        profile_id (str): Profile primary key.
        data (ProfilePatch): Partial update fields.

    Returns:
        ProfileOut: The updated profile.

    Raises:
        HTTPException: 404 if not found.
    """
    rr: RunsRoot = request.app.state.runs_root
    db_path = control_plane_db_path(rr.root)
    with open_profile_store(db_path) as store:
        try:
            existing = get_profile(store, profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}") from exc
        row = upsert_profile(
            store,
            profile_id=profile_id,
            name=data.name if data.name is not None else existing.name,
            backend=data.backend if data.backend is not None else existing.backend,
            model=data.model if data.model is not None else existing.model,
            agent=data.agent if data.agent is not None else existing.agent,
            skills=data.skills if data.skills is not None else existing.skills,
            scope=data.scope if data.scope is not None else existing.scope,
        )
    return ProfileOut.from_row(row)


@router.delete("/api/agents/{profile_id}", status_code=204, tags=["agents"])
async def delete_agent(
    profile_id: str,
    request: Request,
    _auth: None = Depends(require_auth),
) -> Response:
    """Delete an agent profile.

    Args:
        profile_id (str): Profile primary key.

    Returns:
        Response: 204 No Content.

    Raises:
        HTTPException: 404 if not found.
    """
    rr: RunsRoot = request.app.state.runs_root
    db_path = control_plane_db_path(rr.root)
    with open_profile_store(db_path) as store:
        try:
            delete_profile(store, profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}") from exc
    return Response(status_code=204)
