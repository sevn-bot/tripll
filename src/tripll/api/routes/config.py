"""tripll.api.routes.config — health, runtime config, and backend listing routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request

from tripll.api._auth import require_auth
from tripll.api.deps import _read_config
from tripll.api.models import BackendOut, ConfigIn, ConfigOut

router = APIRouter()


@router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Health check — returns status 200 with ``{"status": "ok"}``."""
    return {"status": "ok"}


@router.get("/api/config", response_model=ConfigOut, tags=["config"])
async def get_config(
    request: Request,
    _auth: None = Depends(require_auth),
) -> ConfigOut:
    """Return current runtime configuration (env-var based).

    Returns:
        ConfigOut: Model default, cost budget, and max parallelism.
    """
    _ = request.app.state.runs_root
    return _read_config()


@router.put("/api/config", response_model=ConfigOut, tags=["config"])
async def put_config(
    data: ConfigIn,
    _auth: None = Depends(require_auth),
) -> ConfigOut:
    """Update runtime configuration (mutates environment variables in-process).

    Changes apply to newly spawned subprocesses; running engines are not
    affected.

    Args:
        data (ConfigIn): Fields to update (omitted = unchanged).

    Returns:
        ConfigOut: Updated configuration.
    """
    if data.model_default is not None:
        os.environ["TRIPLL_DEFAULT_MODEL"] = data.model_default
    if data.cost_budget_usd is not None:
        os.environ["TRIPLL_COST_BUDGET_USD"] = str(data.cost_budget_usd)
    if data.max_parallel is not None:
        os.environ["TRIPLL_MAX_PARALLEL"] = str(data.max_parallel)
    return _read_config()


@router.get("/api/backends", response_model=list[BackendOut], tags=["config"])
async def list_backends(
    _auth: None = Depends(require_auth),
) -> list[BackendOut]:
    """List available backends and their availability status.

    Returns:
        list[BackendOut]: One entry per registered backend.
    """
    from tripll.adapters import BACKENDS, get_adapter

    results: list[BackendOut] = []
    for name in sorted(BACKENDS):
        try:
            adapter = get_adapter(name)
            caps = adapter.capabilities()
            results.append(
                BackendOut(
                    name=name,
                    available=caps.available,
                    detail=caps.detail,
                    streaming=caps.streaming,
                )
            )
        except Exception as exc:
            results.append(BackendOut(name=name, available=False, detail=str(exc), streaming=False))
    return results
