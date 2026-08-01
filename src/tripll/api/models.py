"""tripll.api.models — Pydantic request/response models for the control plane."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from tripll.profiles import ProfileRow  # noqa: TC001


def _slug_profile_id(source: str) -> str:
    """Slugify *source* into a profile id (lowercase, dash-separated).

    Args:
        source (str): Raw id or name to slugify.

    Returns:
        str: A non-empty slug (``"profile"`` when *source* has no usable chars),
        truncated to 48 characters.

    Examples:
        >>> _slug_profile_id("My Agent!")
        'my-agent'
        >>> _slug_profile_id("___")
        'profile'
    """
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:48]
    return slug or "profile"


class ProfileIn(BaseModel):
    """Request body for creating / patching an agent profile."""

    name: str
    backend: str
    profile_id: str | None = Field(
        default=None,
        description=(
            "Explicit profile id (slugified). When omitted, an id is derived "
            "from name. Creating with an id that already exists returns 409."
        ),
    )
    model: str = "claude-sonnet-5"
    agent: str = "wave-plan-executor"
    skills: list[str] = Field(default_factory=list)
    scope: dict[str, Any] = Field(default_factory=dict)


class ProfileOut(BaseModel):
    """Response body for an agent profile."""

    profile_id: str
    name: str
    backend: str
    model: str
    agent: str
    skills: list[str]
    scope: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: ProfileRow) -> ProfileOut:
        """Construct from a :class:`~tripll.profiles.ProfileRow`.

        Args:
            row (ProfileRow): Hydrated profile row.

        Returns:
            ProfileOut: API response model.
        """
        return cls(
            profile_id=row.profile_id,
            name=row.name,
            backend=row.backend,
            model=row.model,
            agent=row.agent,
            skills=row.skills,
            scope=row.scope,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class HitlAnswerIn(BaseModel):
    """One HITL answer in a PUT/POST body."""

    question_id: str
    option_id: str | None = None
    checked: bool | None = None
    notes: str = ""


class HitlResponsesIn(BaseModel):
    """Operator HITL responses payload."""

    status: str = "draft"
    answers: list[HitlAnswerIn] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    """Partial update body for an agent profile (all fields optional)."""

    name: str | None = None
    backend: str | None = None
    model: str | None = None
    agent: str | None = None
    skills: list[str] | None = None
    scope: dict[str, Any] | None = None


class RunIn(BaseModel):
    """Request body to launch a new run."""

    input_path: str = Field(
        ...,
        description="Absolute path to the input directory (parallel-wave set or plain wave folder).",
    )
    profile_id: str = Field(
        ...,
        description="Profile to use for the run. Must exist in the profile store.",
    )
    runs_root: str | None = Field(
        default=None,
        description="Override runs root; defaults to the server's configured runs root.",
    )


class EventOut(BaseModel):
    """Response body for a single event row."""

    event_id: int
    run_id: str
    node_id: str
    ts: str
    phase: str
    last_action: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    attempt_n: int | None = None
    task_id: str | None = None
    metadata: str | None = None


class WaveOut(BaseModel):
    """Response body for a single wave row."""

    node_id: str
    run_id: str
    plan_id: str
    wave_id: str
    lane: str
    state: str
    attempt_count: int
    created_at: str
    updated_at: str


class ConfigOut(BaseModel):
    """Response body for API config."""

    model_default: str
    cost_budget_usd: float
    max_parallel: int


class ConfigIn(BaseModel):
    """Request body to update config env vars (runtime only — not persisted to disk)."""

    model_default: str | None = None
    cost_budget_usd: float | None = None
    max_parallel: int | None = None


class BackendOut(BaseModel):
    """Response body for a backend availability entry."""

    name: str
    available: bool
    detail: str
    streaming: bool


class InjectIn(BaseModel):
    """Request body for POST /api/runs/{id}/inject."""

    brief: str = Field(...)
    owned_paths: list[str] = Field(..., min_length=1)
    after: str = Field(...)
    verify_target: str | None = None
    provider: str | None = None
    model: str | None = None
    agent: str | None = None
    dry_run: bool = False
    force_after_drain: bool = False


class InjectOut(BaseModel):
    """Response body for a successful hotfix inject."""

    task_id: str
    node_id: str
    run_id: str
    dry_run: bool
    message: str


class ReconcileIn(BaseModel):
    """Request body for POST /api/runs/{id}/reconcile-graph."""

    dry_run: bool = False
    force_after_drain: bool = False


class ReconcileOut(BaseModel):
    """Response body for a successful graph↔ledger reconcile."""

    run_id: str
    dry_run: bool
    inserted: list[str]
    orphans: list[str]
    message: str
