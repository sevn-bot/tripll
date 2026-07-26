"""Per-provider asyncio semaphore pools with adaptive throttle (PROV-02, P1.5).

Acquire order is fixed **global → provider**; release is the reverse so deadlocks
cannot form across the two semaphores.

Exports:
    ProviderConfig — per-backend pool limits and cooldown.
    ProviderPoolRegistry — global + per-provider semaphores with infra throttle.
    default_provider_configs — built-in limits when a plan omits ``[providers.*]``.
    pools_from_plan — build a registry from v3 plan TOML + env overrides.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

INFRA_STREAK_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Per-provider concurrency and cooldown settings.

    Args:
        max_parallel (int): Concurrent dispatches allowed for this provider.
        default_model (str | None): Provider default when a wave omits ``model``.
        cooldown_s (int): Seconds to wait after infra throttle activates.
    """

    max_parallel: int
    default_model: str | None = None
    cooldown_s: int = 30


def default_provider_configs() -> dict[str, ProviderConfig]:
    """Return built-in provider limits when a plan omits ``[providers.*]``.

    Returns:
        dict[str, ProviderConfig]: Known backend → config.

    Examples:
        >>> "cursor_local" in default_provider_configs()
        True
    """
    return {
        "claude_code": ProviderConfig(max_parallel=3, default_model="claude-sonnet-5"),
        "cursor_local": ProviderConfig(max_parallel=5, default_model="auto", cooldown_s=30),
        "cursor_cloud": ProviderConfig(max_parallel=8, default_model="auto", cooldown_s=60),
    }


def _max_parallel_from_env() -> int:
    try:
        return max(1, int(os.environ.get("TRIPLL_MAX_PARALLEL", "3")))
    except (ValueError, TypeError):
        return 3


def _parse_providers_table(raw: dict[str, Any]) -> dict[str, ProviderConfig]:
    defaults = default_provider_configs()
    out = dict(defaults)
    providers = raw.get("providers")
    if not isinstance(providers, dict):
        return out
    for name, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        base = out.get(str(name), ProviderConfig(max_parallel=3))
        max_par = int(cfg.get("max_parallel", base.max_parallel))
        cooldown = int(cfg.get("cooldown_s", base.cooldown_s))
        model_raw = cfg.get("default_model")
        default_model = str(model_raw) if model_raw is not None else base.default_model
        out[str(name)] = ProviderConfig(
            max_parallel=max(1, max_par),
            default_model=default_model,
            cooldown_s=max(0, cooldown),
        )
    return out


def pools_from_plan(
    plan: dict[str, Any] | None,
    *,
    global_limit: int | None = None,
) -> tuple[ProviderPoolRegistry, str]:
    """Build a :class:`ProviderPoolRegistry` from a v3 plan dict.

    Args:
        plan (dict[str, Any] | None): Parsed v3 plan (``pipeline`` + ``providers``).
        global_limit (int | None): Override global ceiling (default env/plan).

    Returns:
        tuple[ProviderPoolRegistry, str]: Registry and ``default_provider`` name.

    Examples:
        >>> reg, default = pools_from_plan({"pipeline": {"default_provider": "cursor_local"}})
        >>> default
        'cursor_local'
    """
    pipeline = (plan or {}).get("pipeline") if isinstance(plan, dict) else {}
    if not isinstance(pipeline, dict):
        pipeline = {}
    providers = _parse_providers_table(plan or {})
    ceiling = global_limit
    if ceiling is None:
        plan_global = pipeline.get("max_parallel")
        ceiling = int(plan_global) if plan_global is not None else _max_parallel_from_env()
    default_provider = str(pipeline.get("default_provider") or "claude_code")
    return ProviderPoolRegistry(ceiling, providers), default_provider


class ProviderPoolRegistry:
    """Global + per-provider semaphores with infra adaptive throttle."""

    def __init__(
        self,
        global_limit: int,
        providers: dict[str, ProviderConfig],
        *,
        clock: Callable[[], float] | None = None,
        infra_threshold: int = INFRA_STREAK_THRESHOLD,
    ) -> None:
        """See class docstring."""
        self._global = asyncio.Semaphore(max(1, global_limit))
        self._configs = dict(providers)
        self._base_limits: dict[str, int] = {
            name: cfg.max_parallel for name, cfg in providers.items()
        }
        self._effective_limits: dict[str, int] = dict(self._base_limits)
        self._provider_sems: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(limit) for name, limit in self._effective_limits.items()
        }
        self._clock = clock or time.monotonic
        self._cooldown_until: dict[str, float] = {}
        self._consecutive_infra: dict[str, int] = {}
        self._infra_threshold = max(1, infra_threshold)
        self._acquire_order: list[tuple[str, str]] = []

    @property
    def configs(self) -> dict[str, ProviderConfig]:
        """Return the configured provider table."""
        return dict(self._configs)

    def effective_limit(self, provider: str) -> int:
        """Return the current semaphore limit for *provider* (may be throttled)."""
        return self._effective_limits.get(provider, 1)

    def in_cooldown(self, provider: str) -> bool:
        """Return True when *provider* is in post-infra cooldown."""
        until = self._cooldown_until.get(provider, 0.0)
        return self._clock() < until

    def cooldown_remaining_s(self, provider: str) -> float:
        """Return seconds remaining in *provider*'s cooldown (0 when none)."""
        until = self._cooldown_until.get(provider, 0.0)
        return max(0.0, until - self._clock())

    def _resize_provider(self, provider: str, new_limit: int) -> None:
        limit = max(1, min(new_limit, self._base_limits.get(provider, new_limit)))
        if limit == self._effective_limits.get(provider):
            return
        self._effective_limits[provider] = limit
        self._provider_sems[provider] = asyncio.Semaphore(limit)

    async def acquire(self, provider: str) -> None:
        """Acquire global then provider semaphores (fixed order)."""
        await self._global.acquire()
        sem = self._provider_sems.get(provider)
        if sem is None:
            cfg = ProviderConfig(max_parallel=1)
            self._configs[provider] = cfg
            self._base_limits[provider] = 1
            self._effective_limits[provider] = 1
            sem = asyncio.Semaphore(1)
            self._provider_sems[provider] = sem
        try:
            await sem.acquire()
        except BaseException:
            self._global.release()
            raise
        self._acquire_order.append(("global", provider))

    def release(self, provider: str) -> None:
        """Release provider then global semaphores (reverse order)."""
        sem = self._provider_sems.get(provider)
        if sem is not None:
            sem.release()
        self._global.release()
        if self._acquire_order:
            self._acquire_order.pop()

    def record_infra(self, provider: str) -> None:
        """Halve the pool and start cooldown after repeated infra failures."""
        streak = self._consecutive_infra.get(provider, 0) + 1
        self._consecutive_infra[provider] = streak
        cfg = self._configs.get(provider, ProviderConfig(max_parallel=1))
        if streak >= self._infra_threshold:
            current = self._effective_limits.get(provider, cfg.max_parallel)
            self._resize_provider(provider, max(1, current // 2))
            self._cooldown_until[provider] = self._clock() + float(cfg.cooldown_s)

    def record_success(self, provider: str) -> None:
        """Restore one step toward the base limit after a clean dispatch."""
        self._consecutive_infra[provider] = 0
        base = self._base_limits.get(provider, 1)
        current = self._effective_limits.get(provider, base)
        if current < base:
            self._resize_provider(provider, min(base, current + 1))
