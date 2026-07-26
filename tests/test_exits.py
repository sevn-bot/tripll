"""Loop exits — all 8 triggers, circuit breaker (W1.10)."""

from __future__ import annotations

import pytest

from tripll.loops.exits import (
    circuit_breaker_open,
    evaluate_exit,
    no_progress_exit,
    record_exit_on_run,
)

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


@pytest.mark.tier1
@pytest.mark.xfail(reason="green after W6: circuit breaker scoped per run", strict=False)
def test_circuit_breaker_does_not_contaminate_sequential_runs() -> None:
    """BUG-07: a fresh run must not inherit breaker state from a prior run."""
    circuit_breaker_open(agent="fixer", problem_type="lint", failures=5)
    assert circuit_breaker_open(agent="fixer", problem_type="lint") is False


@pytest.mark.tier1
@pytest.mark.xfail(reason="green after W6: record_exit_on_run advances updated_at", strict=False)
def test_record_exit_on_run_updates_timestamp(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """DEBT-02: exit records must bump ``runs.updated_at``."""
    from tripll.ledger import insert_run, open_ledger

    db = tmp_path / "ledger.db"
    with open_ledger(db) as lc:
        insert_run(lc, run_id="r1", slug="r1", source_mode="A", input_path="/tmp")
        before = lc.conn.execute(
            "SELECT updated_at FROM runs WHERE run_id = ?",
            ("r1",),
        ).fetchone()[0]
        record_exit_on_run(lc, run_id="r1", exit_id=3, name="budget_cap")
        after = lc.conn.execute(
            "SELECT updated_at FROM runs WHERE run_id = ?",
            ("r1",),
        ).fetchone()[0]
    assert after != before
