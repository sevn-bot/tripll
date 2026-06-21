"""tripll.adapters.options — per-dispatch backend configuration.

Exports:
    BackendOptions — model/agent overrides passed from CLI/Makefile to adapters.
    role_dispatch_from_env — read ``TRIPLL_ROLE_DISPATCH`` (tri-state).
    resolve_role_dispatch — merge CLI/env/plan/orchestrator-implied precedence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackendOptions:
    """Optional backend flags for one dispatch session.

    Args:
        model (str | None): Provider model id (``auto``, ``claude-sonnet-4-6``, …).
        agent (str | None): Claude Code sub-agent slug (``wave-plan-executor``, …).
        verbose (bool): Pass ``--verbose`` to Claude Code (off by default).
    """

    model: str | None = None
    agent: str | None = None
    verbose: bool = False


def role_dispatch_from_env() -> bool | None:
    """Return role-dispatch from ``TRIPLL_ROLE_DISPATCH`` (tri-state).

    Returns:
        bool | None: ``True``/``False`` when set; ``None`` when unset.

    Examples:
        >>> role_dispatch_from_env() is None  # doctest: +SKIP
        True
    """
    raw = os.environ.get("TRIPLL_ROLE_DISPATCH", "").strip().lower()
    if not raw:
        return None
    return raw in ("1", "true", "yes", "on")


def resolve_role_dispatch(
    *,
    cli: bool | None,
    env: bool | None = None,
    plan_config: bool = False,
    orchestrator_enabled: bool = False,
) -> bool:
    """Resolve effective role-dispatch per design-note §10.4 precedence.

    Precedence: CLI > env > plan config > orchestrator-implied.

    Args:
        cli (bool | None): ``--role-dispatch`` / ``--no-role-dispatch`` (``None`` = unset).
        env (bool | None): ``TRIPLL_ROLE_DISPATCH`` tri-state.
        plan_config (bool): Plan or orchestrator-config ``role_dispatch`` field.
        orchestrator_enabled (bool): Full orchestrator mode implies on unless overridden.

    Returns:
        bool: Whether per-role agent injection is active.

    Examples:
        >>> resolve_role_dispatch(cli=True, orchestrator_enabled=False)
        True
        >>> resolve_role_dispatch(cli=None, env=None, orchestrator_enabled=True)
        True
        >>> resolve_role_dispatch(cli=None, env=None, plan_config=False, orchestrator_enabled=False)
        False
    """
    if cli is not None:
        return cli
    if env is not None:
        return env
    if plan_config:
        return True
    return orchestrator_enabled
