"""First-pass probability from compile-time features (CAL-01, W5.1)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from tripll.harness.contracts import parse_outcome_contract
from tripll.rules.pack import scope_intersects

if TYPE_CHECKING:
    from pathlib import Path

PREDICTOR_VERSION = "linear-v1"

# Published linear model — interpretable weights, not fitted (W5.1).
_INTERCEPT = 0.85
_WEIGHTS: dict[str, float] = {
    "module_count": -0.08,
    "calls_fan_out": -0.015,
    "effort_score": -0.22,
    "target_count": -0.04,
    "contract_clause_count": -0.025,
    "active_rule_overlap": -0.18,
}

_EFFORT_SCORE = {"S": 0.0, "M": 1.0, "L": 2.0, "XL": 3.0}


def _effort_score(effort: str) -> float:
    token = str(effort or "M").strip().upper().split()[0]
    return _EFFORT_SCORE.get(token, 1.0)


def _contract_clause_count(wave: dict[str, Any]) -> int:
    outcome = wave.get("outcome")
    if not isinstance(outcome, dict):
        return 0
    parsed = parse_outcome_contract(outcome)
    return len(parsed.get("required") or []) + len(parsed.get("forbidden") or [])


def _active_rule_overlap(
    wave_targets: list[str],
    *,
    repo_root: Path | None,
) -> int:
    if repo_root is None or not wave_targets:
        return 0
    from tripll.rules.store import RuleStore

    store = RuleStore(repo_root)
    active = [rule for rule in store.list_rules() if rule.state == "active"]
    return sum(1 for rule in active if scope_intersects(rule.scope, wave_targets))


def extract_wave_features(
    wave: dict[str, Any],
    *,
    repo_root: Path | None = None,
    graph_db: Path | str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Collect compile-time features for one wave row.

    Args:
        wave (dict[str, Any]): One ``[[waves]]`` table from a v3 plan.
        repo_root (Path | None): Repository root for active-rule scope lookup.
        graph_db (Path | str | None): Optional GraphStore for CALLS fan-out.
        repo (str | None): Repository slug for code-graph resolution.

    Returns:
        dict[str, Any]: Feature vector consumed by :func:`predict_first_pass_probability`.
    """
    targets = [str(t) for t in (wave.get("targets") or []) if str(t).strip()]
    module_count = len(targets)
    calls_fan_out = 0
    if graph_db is not None and targets:
        from tripll.plan.code_graph import routing_hints_for_wave

        hints = routing_hints_for_wave(
            targets=targets,
            graph_store=str(graph_db),
            repo=repo or (repo_root.name if repo_root is not None else "tripll"),
        )
        module_count = int(hints.get("module_count") or module_count)
        calls_fan_out = int(hints.get("calls_fanout") or 0)
    overlap = _active_rule_overlap(targets, repo_root=repo_root)
    return {
        "module_count": module_count,
        "calls_fan_out": calls_fan_out,
        "effort": str(wave.get("effort") or "M"),
        "effort_score": _effort_score(str(wave.get("effort") or "M")),
        "target_count": len(targets),
        "contract_clause_count": _contract_clause_count(wave),
        "active_rule_overlap": overlap,
    }


def predict_first_pass_probability(features: dict[str, Any]) -> float:
    """Return first-attempt pass probability from a feature vector.

    Uses a published linear model in logit space, clamped to ``[0, 1]``.

    Args:
        features (dict[str, Any]): Output of :func:`extract_wave_features`.

    Returns:
        float: Probability in ``[0, 1]``.

    Examples:
        >>> 0.0 <= predict_first_pass_probability(
        ...     {
        ...         "module_count": 2,
        ...         "calls_fan_out": 5,
        ...         "effort_score": 1.0,
        ...         "target_count": 2,
        ...         "contract_clause_count": 3,
        ...         "active_rule_overlap": 0,
        ...     }
        ... ) <= 1.0
        True
    """
    logit = _INTERCEPT
    for key, weight in _WEIGHTS.items():
        raw = features.get(key, 0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        logit += weight * value
    probability = 1.0 / (1.0 + math.exp(-logit))
    return max(0.0, min(1.0, probability))


def build_wave_predictions(
    plan: dict[str, Any],
    *,
    repo_root: Path | None = None,
    graph_db: Path | str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Build per-wave first-pass probabilities for a compiled plan.

    Args:
        plan (dict[str, Any]): Plan dict (typically output of :func:`compile_plan`).
        repo_root (Path | None): Repository root for rule overlap.
        graph_db (Path | str | None): Optional GraphStore path.
        repo (str | None): Repository slug for code graph.

    Returns:
        dict[str, Any]: ``predictor_version`` and ``waves`` mapping wave id → payload.
    """
    slug = str(plan.get("slug") or "plan")
    waves_out: dict[str, Any] = {}
    for wave in plan.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        wave_id = str(wave.get("id") or "")
        if not wave_id:
            continue
        features = extract_wave_features(
            wave,
            repo_root=repo_root,
            graph_db=graph_db,
            repo=repo,
        )
        probability = predict_first_pass_probability(features)
        waves_out[wave_id] = {
            "node_id": f"{slug}:{wave_id}",
            "features": features,
            "first_pass_probability": probability,
        }
    return {
        "predictor_version": PREDICTOR_VERSION,
        "waves": waves_out,
    }
