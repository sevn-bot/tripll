"""Advisory routing snapshot — R28 byte-identical dispatch decisions (W5.4)."""

from __future__ import annotations

from typing import Any

from tripll.plan.providers import wave_node_from_v3


def dispatch_decisions_snapshot(
    plan: dict[str, Any],
    *,
    predictor_enabled: bool = False,
    default_provider: str | None = None,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Return dispatch routing metadata for every wave in *plan*.

    ``predictor_enabled`` is accepted for API symmetry but **never** changes the
    snapshot (R28 — calibration is advisory only).

    Args:
        plan (dict[str, Any]): Parsed v3 plan dict.
        predictor_enabled (bool): Ignored; routing must not depend on calibration.
        default_provider (str | None): Override plan default provider.
        max_attempts (int): Attempt budget mirrored from the engine default.

    Returns:
        dict[str, Any]: JSON-serialisable routing snapshot for equality checks.

    Examples:
        >>> sample = {
        ...     "slug": "demo",
        ...     "pipeline": {"default_provider": "cursor_local"},
        ...     "waves": [{"id": "W1", "role": "impl", "effort": "S", "targets": ["src/a.py"]}],
        ... }
        >>> off = dispatch_decisions_snapshot(plan=sample, predictor_enabled=False)
        >>> on = dispatch_decisions_snapshot(plan=sample, predictor_enabled=True)
        >>> off == on
        True
    """
    _ = predictor_enabled
    slug = str(plan.get("slug") or "plan")
    pipeline = plan.get("pipeline") or {}
    provider_default = (
        default_provider or str(pipeline.get("default_provider") or "").strip() or "claude_code"
    )
    waves = [w for w in (plan.get("waves") or []) if isinstance(w, dict)]
    node_id_map = {str(w["id"]): f"{slug}:{w['id']}" for w in waves if w.get("id")}
    owned_paths: list[str] = []
    for wave in waves:
        owned_paths.extend(str(t) for t in (wave.get("targets") or []))

    per_wave: dict[str, Any] = {}
    for wave in waves:
        wave_id = str(wave.get("id") or "")
        if not wave_id:
            continue
        node = wave_node_from_v3(
            wave,
            plan_id=slug,
            plan_file=f"{slug}-wave-plan.md",
            lane=str(plan.get("title") or slug),
            owned_paths=owned_paths,
            node_id_map=node_id_map,
        )
        primary = node.provider or provider_default
        chain = [primary, *[p for p in node.fallback if p != primary]]
        per_wave[node.node_id] = {
            "wave_id": wave_id,
            "provider": primary,
            "provider_chain": chain,
            "model": node.model,
            "agent": node.agent,
            "max_attempts": max_attempts,
            "wall_clock_limit_s": node.wall_clock_limit_s,
            "is_review_gate": node.is_review_gate,
            "reasoning_effort": node.reasoning_effort,
        }

    return {
        "default_provider": provider_default,
        "max_attempts": max_attempts,
        "waves": per_wave,
    }
