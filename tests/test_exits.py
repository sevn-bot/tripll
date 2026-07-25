"""Loop exits — all 8 triggers, circuit breaker (W1.10)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module

_XFAIL = pytest.mark.xfail(reason="green after W6: exits module", strict=False)

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


@_XFAIL
@pytest.mark.parametrize("exit_id", range(1, 9))
def test_exit_fires_and_records(exit_id: int) -> None:
    evaluate_exit = require_module("tripll.loops.exits", attr="evaluate_exit")
    fired = evaluate_exit(exit_id, context={"trigger": _EXIT_NAMES[exit_id]})
    assert fired.exit_id == exit_id
    assert fired.recorded is True
    assert fired.name == _EXIT_NAMES[exit_id]


@_XFAIL
def test_no_progress_uses_graph_delta_hash() -> None:
    no_progress_exit = require_module("tripll.loops.exits", attr="no_progress_exit")
    assert no_progress_exit(turn_hashes=["hash-a", "hash-a", "hash-a"]) is True
    assert no_progress_exit(turn_hashes=["a", "b", "c"]) is False


@_XFAIL
def test_error_threshold_circuit_breaker_per_agent_problem() -> None:
    circuit_breaker_open = require_module("tripll.loops.exits", attr="circuit_breaker_open")
    assert circuit_breaker_open(agent="fixer", problem_type="lint", failures=5) is True
    assert circuit_breaker_open(agent="fixer", problem_type="lint", failures=0) is False
    circuit_breaker_open(agent="fixer", problem_type="lint", failures=5, reset=True)
    assert circuit_breaker_open(agent="fixer", problem_type="lint", failures=0) is False
