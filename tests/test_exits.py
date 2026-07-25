"""Loop exits — all 8 triggers, circuit breaker (W1.10)."""

from __future__ import annotations

import pytest

from tripll.loops.exits import circuit_breaker_open, evaluate_exit, no_progress_exit

_EXIT_NAMES = {
    1: "goal_met",
    2: "turn_cap",
    3: "budget_cap",
    4: "wall_clock",
    5: "no_progress",
    6: "human_interrupt",
    7: "error_threshold",
    8: "external_event",
}


@pytest.mark.parametrize("exit_id", range(1, 9))
def test_exit_fires_and_records(exit_id: int) -> None:
    fired = evaluate_exit(exit_id, context={"trigger": _EXIT_NAMES[exit_id]})
    assert fired.exit_id == exit_id
    assert fired.recorded is True
    assert fired.name == _EXIT_NAMES[exit_id]


def test_no_progress_uses_graph_delta_hash() -> None:
    assert no_progress_exit(turn_hashes=["hash-a", "hash-a", "hash-a"]) is True
    assert no_progress_exit(turn_hashes=["a", "b", "c"]) is False


def test_error_threshold_circuit_breaker_per_agent_problem() -> None:
    assert circuit_breaker_open(agent="fixer", problem_type="lint", failures=5) is True
    assert circuit_breaker_open(agent="fixer", problem_type="lint", failures=0) is False
    circuit_breaker_open(agent="fixer", problem_type="lint", failures=5, reset=True)
    assert circuit_breaker_open(agent="fixer", problem_type="lint", failures=0) is False
