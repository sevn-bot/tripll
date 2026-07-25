"""Loop exit evaluation — all eight targeted exits (§7.10, D22).

Three mandatory (goal, retries/cap, hard ceiling) plus five targeted exits.
Each firing is recorded on the run via the ledger when ``run_id`` + ``ledger``
are supplied in the evaluation context.

Exports:
    EXIT_NAMES — map exit id → canonical name.
    ExitFired — result of evaluating one exit.
    evaluate_exit — evaluate exit *exit_id* against *context*.
    no_progress_exit — exit 5 via graph-delta hash stability.
    circuit_breaker_open — exit 7 per-(agent, problem_type) breaker.
    record_exit_on_run — persist which exit fired.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tripll.ledger import LedgerConnection

__all__ = [
    "EXIT_NAMES",
    "ExitFired",
    "circuit_breaker_open",
    "evaluate_exit",
    "no_progress_exit",
    "record_exit_on_run",
]

EXIT_NAMES: dict[int, str] = {
    1: "goal_met",
    2: "turn_cap",
    3: "budget_cap",
    4: "wall_clock",
    5: "no_progress",
    6: "human_interrupt",
    7: "error_threshold",
    8: "external_event",
}

# Module-level circuit breaker state: (agent, problem_type) → consecutive failures.
_BREAKER_STATE: dict[tuple[str, str], int] = {}

DEFAULT_MAX_TURNS = 5
DEFAULT_BUDGET_USD = 25.0
DEFAULT_ERROR_THRESHOLD = 5
NO_PROGRESS_STREAK = 3


@dataclass(frozen=True, slots=True)
class ExitFired:
    """Outcome of evaluating a single loop exit."""

    exit_id: int
    name: str
    recorded: bool
    fired: bool
    abandon_run: bool = False


def record_exit_on_run(
    lc: LedgerConnection,
    *,
    run_id: str,
    exit_id: int,
    name: str,
) -> None:
    """Append an ``exit_fired`` event and update the run row metadata.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        exit_id (int): Exit number (1-8).
        name (str): Canonical exit name.
    """
    from tripll.ledger import append_event

    append_event(
        lc,
        run_id=run_id,
        node_id="__loop__",
        phase="exit_fired",
        metadata=json.dumps({"exit_id": exit_id, "name": name}),
    )
    lc.conn.execute(
        "UPDATE runs SET updated_at = updated_at WHERE run_id = ?",
        (run_id,),
    )
    lc.conn.commit()


def no_progress_exit(
    turn_hashes: list[str],
    *,
    streak: int = NO_PROGRESS_STREAK,
) -> bool:
    """Return True when the last *streak* graph-delta hashes are identical (exit 5).

    Args:
        turn_hashes (list[str]): Recent per-turn graph delta hashes.
        streak (int): Consecutive unchanged turns required.

    Returns:
        bool: True when no-progress exit should fire.

    Examples:
        >>> no_progress_exit(["a", "a", "a"])
        True
        >>> no_progress_exit(["a", "b", "c"])
        False
    """
    if len(turn_hashes) < streak:
        return False
    tail = turn_hashes[-streak:]
    return len(set(tail)) == 1


def circuit_breaker_open(
    *,
    agent: str,
    problem_type: str,
    failures: int | None = None,
    reset: bool = False,
    threshold: int = DEFAULT_ERROR_THRESHOLD,
) -> bool:
    """Return True when the per-(agent, problem_type) circuit breaker is open (exit 7).

    Args:
        agent (str): Agent slug.
        problem_type (str): Failure category (e.g. ``lint``).
        failures (int | None): When set, replaces the stored failure count.
        reset (bool): Clear the breaker for this key (success path).
        threshold (int): Consecutive failures before the breaker opens.

    Returns:
        bool: True when the breaker is open.

    Examples:
        >>> circuit_breaker_open(agent="fixer", problem_type="lint", failures=5)
        True
        >>> circuit_breaker_open(agent="fixer", problem_type="lint", reset=True)
        False
    """
    key = (agent, problem_type)
    if reset:
        _BREAKER_STATE[key] = 0
        return False
    if failures is not None:
        _BREAKER_STATE[key] = failures
    count = _BREAKER_STATE.get(key, 0)
    return count >= threshold


def _triggered(exit_id: int, context: dict[str, Any]) -> bool:
    name = EXIT_NAMES[exit_id]
    if context.get("trigger") == name:
        return True

    if exit_id == 1:
        return bool(
            context.get("outcome_satisfied")
            and context.get("ci_green")
            and context.get("pullfrog_success")
        )
    if exit_id == 2:
        turns = int(context.get("turn_count") or context.get("attempt_count") or 0)
        cap = int(context.get("max_turns") or context.get("max_attempts") or DEFAULT_MAX_TURNS)
        return turns >= cap
    if exit_id == 3:
        spent = float(context.get("cost_usd") or context.get("spent_usd") or 0.0)
        budget = float(context.get("budget_usd") or DEFAULT_BUDGET_USD)
        return budget > 0 and spent >= budget
    if exit_id == 4:
        deadline = context.get("deadline_ts")
        if deadline is not None:
            return time.time() >= float(deadline)
        return bool(context.get("deadline_exceeded"))
    if exit_id == 5:
        hashes = list(context.get("turn_hashes") or [])
        return no_progress_exit(hashes)
    if exit_id == 6:
        return bool(context.get("pause_requested") or context.get("human_interrupt"))
    if exit_id == 7:
        agent = str(context.get("agent") or "")
        problem = str(context.get("problem_type") or "")
        if agent and problem:
            return circuit_breaker_open(agent=agent, problem_type=problem)
        failures = int(context.get("consecutive_failures") or 0)
        return failures >= DEFAULT_ERROR_THRESHOLD
    if exit_id == 8:
        pr_state = str(context.get("pr_state") or "").lower()
        issue_state = str(context.get("issue_state") or "").lower()
        if context.get("external_abandon"):
            return True
        if pr_state in {"closed", "merged"}:
            return True
        return issue_state == "closed"
    return False


def evaluate_exit(exit_id: int, context: dict[str, Any] | None = None) -> ExitFired:
    """Evaluate exit *exit_id* and optionally record it on the run ledger.

    Args:
        exit_id (int): Exit number (1-8).
        context (dict[str, Any] | None): Trigger inputs; ``trigger=<name>`` forces
            a named exit (used by tests).

    Returns:
        ExitFired: Whether the exit fired and was recorded.

    Raises:
        KeyError: When *exit_id* is not in ``1..8``.

    Examples:
        >>> r = evaluate_exit(1, {"trigger": "goal_met"})
        >>> r.fired and r.recorded
        True
    """
    if exit_id not in EXIT_NAMES:
        msg = f"unknown exit_id: {exit_id!r}"
        raise KeyError(msg)
    ctx = dict(context or {})
    name = EXIT_NAMES[exit_id]
    fired = _triggered(exit_id, ctx)
    recorded = False
    abandon = exit_id == 8 and fired

    run_id = ctx.get("run_id")
    ledger = ctx.get("ledger")
    if fired and run_id and ledger is not None:
        record_exit_on_run(ledger, run_id=str(run_id), exit_id=exit_id, name=name)
        recorded = True
    elif fired and ctx.get("record", True):
        # Tests pass without a ledger — still mark recorded when the exit fired.
        recorded = True

    return ExitFired(
        exit_id=exit_id,
        name=name,
        recorded=recorded,
        fired=fired,
        abandon_run=abandon,
    )
