"""Exit evaluation helpers extracted from :mod:`tripll.engine`."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from tripll.ledger import LedgerConnection, get_run_cost, get_wave

_PAUSE_MARKER = "pause-requested.md"
_QUOTA_MARKER = "quota-paused.md"
_COST_MARKER = "cost-budget-paused.md"

if TYPE_CHECKING:
    from tripll.engine import Engine
    from tripll.graph import RunGraph, WaveNode


def _pause_requested(engine: Engine, run_id: str) -> bool:
    """Return True when an API-written pause marker exists for *run_id*.

    Args:
        run_id (str): Run identifier.

    Returns:
        bool: True when ``pause-requested.md`` is present.

    Examples:
        >>> Engine._pause_requested.__name__
        'pause_requested'
    """
    return (engine.runs_root.run_dir(run_id) / _PAUSE_MARKER).exists()


def _cost_budget_exceeded(engine: Engine, lc: LedgerConnection, run_id: str) -> bool:
    """Return True when run cost meets or exceeds ``cost_budget_usd``."""
    if engine.cost_budget_usd <= 0:
        return False
    return get_run_cost(lc, run_id) >= engine.cost_budget_usd


def _init_run_wall_clock(engine: Engine, graph: RunGraph) -> None:
    """Record run-level wall-clock deadline for exit 4."""
    import time

    engine._run_wall_clock_start = time.time()
    env_limit = os.environ.get("TRIPLL_RUN_WALL_CLOCK_S", "").strip()
    limit_s = 0.0
    if env_limit:
        try:
            limit_s = max(0.0, float(env_limit))
        except ValueError:
            limit_s = 0.0
    if limit_s <= 0:
        limit_s = float(sum(n.wall_clock_limit_s for n in graph.nodes.values()))
    engine._run_deadline_ts = engine._run_wall_clock_start + limit_s if limit_s > 0 else None


def _load_check_runs_for_run(engine: Engine, run_id: str) -> list[dict[str, Any]]:
    """Load cached GitHub check-runs for *run_id* when present."""
    run_dir = engine.runs_root.run_dir(run_id)
    path = run_dir / "check-runs.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _external_event_state(engine: Engine, run_id: str) -> tuple[str, str]:
    """Return PR/issue state inputs for exit 8."""
    pr_state = os.environ.get("TRIPLL_PR_STATE", "").strip()
    issue_state = os.environ.get("TRIPLL_ISSUE_STATE", "").strip()
    marker = engine.runs_root.run_dir(run_id) / "external-event.json"
    if marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            pr_state = str(payload.get("pr_state") or pr_state)
            issue_state = str(payload.get("issue_state") or issue_state)
    return pr_state, issue_state


def _build_exit_eval_context(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    *,
    node: WaveNode | None = None,
    turn_hashes: list[str] | None = None,
    outcome_satisfied: bool = False,
    ci_green: bool = False,
    record: bool = True,
) -> dict[str, Any]:
    """Assemble the ``evaluate_exit`` context for Engine terminal checks."""
    from tripll.github.reviews import review_success_from_check_runs

    check_runs = _load_check_runs_for_run(engine, run_id)
    pr_state, issue_state = _external_event_state(engine, run_id)
    ctx: dict[str, Any] = {
        "run_id": run_id,
        "ledger": lc,
        "record": record,
        "cost_usd": get_run_cost(lc, run_id),
        "budget_usd": engine.cost_budget_usd,
        "spent_usd": get_run_cost(lc, run_id),
        "review_success": review_success_from_check_runs(check_runs),
        "outcome_satisfied": outcome_satisfied,
        "ci_green": ci_green,
        "pr_state": pr_state,
        "issue_state": issue_state,
        "pause_requested": _pause_requested(engine, run_id),
    }
    if engine._run_deadline_ts is not None:
        ctx["deadline_ts"] = engine._run_deadline_ts
    if node is not None:
        ctx["agent"] = node.agent or node.model or "wave"
        ctx["problem_type"] = node.wave_id
        ctx["attempt_count"] = get_wave(lc, run_id, node.node_id).attempt_count
        ctx["max_attempts"] = engine.max_attempts
    if turn_hashes is not None:
        ctx["turn_hashes"] = turn_hashes
    return ctx


def _evaluate_engine_exit(
    engine: Engine,
    exit_id: int,
    lc: LedgerConnection,
    run_id: str,
    **extra: Any,
) -> Any:
    """Evaluate one exit from the Engine path; records ``exit_fired`` when it fires."""
    from tripll.loops.exits import evaluate_exit

    ctx_keys = {"node", "turn_hashes", "outcome_satisfied", "ci_green", "record"}
    ctx = _build_exit_eval_context(
        engine,
        lc,
        run_id,
        **{k: v for k, v in extra.items() if k in ctx_keys},
    )
    ctx.update(extra)
    result = evaluate_exit(exit_id, ctx)
    if result.fired:
        engine._last_fired_exit_id = result.exit_id
    return result


def _scan_pre_dispatch_exits(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
) -> int | None:
    """Evaluate human_interrupt, external_event, and wall_clock before dispatch."""
    for exit_id in (6, 8, 4):
        fired = _evaluate_engine_exit(engine, exit_id, lc, run_id)
        if fired.fired:
            return exit_id
    return None


def _fire_goal_met_exit(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    *,
    ci_green: bool,
    outcome_satisfied: bool,
) -> None:
    """Record exit 1 when the run outcome contract is satisfied."""
    _evaluate_engine_exit(
        engine,
        1,
        lc,
        run_id,
        ci_green=ci_green,
        outcome_satisfied=outcome_satisfied,
    )


def _fire_error_threshold_exit(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    *,
    node: WaveNode,
    failures: int,
) -> None:
    """Open the per-run circuit breaker and record exit 7 when tripped."""
    from tripll.loops.exits import circuit_breaker_open

    agent = str(node.agent or node.model or "wave")
    problem_type = str(node.wave_id)
    circuit_breaker_open(
        agent=agent,
        problem_type=problem_type,
        failures=failures,
        run_id=run_id,
    )
    _evaluate_engine_exit(
        engine,
        7,
        lc,
        run_id,
        node=node,
        agent=agent,
        problem_type=problem_type,
    )
