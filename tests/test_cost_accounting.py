"""Ledger cost accounting — BUG-cost (W1.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.ledger import (
    end_attempt,
    get_run_cost,
    insert_attempt,
    insert_run,
    insert_wave,
    open_ledger,
    reset_wave_attempts,
)


@pytest.fixture
def ledger(tmp_path: Path):
    db = tmp_path / "ledger.db"
    with open_ledger(db) as lc:
        insert_run(lc, run_id="r1", slug="r1", source_mode="A", input_path="/tmp")
        insert_wave(
            lc,
            node_id="p:W1",
            run_id="r1",
            plan_id="p",
            wave_id="W1",
            lane="lane",
        )
        yield lc


@pytest.mark.tier1
def test_reset_wave_attempts_then_success_cost_not_doubled(ledger) -> None:
    """BUG-cost: ``runs.cost_usd`` equals true sum after reset + fresh attempt."""
    att1 = insert_attempt(ledger, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    end_attempt(ledger, att1, outcome="failed", cost_usd=1.50)
    reset_wave_attempts(ledger, "r1", "p:W1")
    att2 = insert_attempt(ledger, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    end_attempt(ledger, att2, outcome="done", cost_usd=2.00)
    total = get_run_cost(ledger, "r1")
    assert total == pytest.approx(2.00)


@pytest.mark.tier1
def test_run_cost_matches_attempt_sum(ledger) -> None:
    att = insert_attempt(ledger, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    end_attempt(ledger, att, outcome="done", cost_usd=3.25)
    row = ledger.conn.execute("SELECT cost_usd FROM runs WHERE run_id = ?", ("r1",)).fetchone()
    attempt_sum = ledger.conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM attempts WHERE run_id = ?",
        ("r1",),
    ).fetchone()[0]
    assert float(row[0]) == pytest.approx(float(attempt_sum))
