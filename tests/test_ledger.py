"""Tests for tripll.ledger — SQLite state ledger.

Covers: schema creation, run/wave/attempt insert, state transitions,
terminal-state guard, idempotent transitions, attempt count increment.
"""

from __future__ import annotations

import pytest

from tripll.ledger import (
    append_event,
    end_attempt,
    get_run,
    get_wave,
    insert_attempt,
    insert_run,
    insert_wave,
    latest_events_by_node,
    list_attempts,
    list_waves,
    open_ledger,
    reset_wave_attempts,
    transition_run,
    transition_wave,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def lc():  # type: ignore[no-untyped-def]
    """In-memory ledger for each test."""
    ledger = open_ledger(":memory:")
    yield ledger
    ledger.close()


def _seed_run(lc, run_id: str = "r1") -> None:  # type: ignore[no-untyped-def]
    insert_run(lc, run_id=run_id, slug="test", source_mode="A", input_path="/tmp/test")


def _seed_wave(lc, run_id: str = "r1", node_id: str = "p:W1") -> None:  # type: ignore[no-untyped-def]
    insert_wave(lc, node_id=node_id, run_id=run_id, plan_id="p", wave_id="W1", lane="core")


# ---------------------------------------------------------------------------
# Schema smoke
# ---------------------------------------------------------------------------


def test_open_ledger_creates_tables(lc) -> None:  # type: ignore[no-untyped-def]
    cur = lc.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {row[0] for row in cur.fetchall()}
    assert {"runs", "waves", "attempts"}.issubset(tables)


# ---------------------------------------------------------------------------
# Run operations
# ---------------------------------------------------------------------------


def test_insert_run_default_state(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    row = get_run(lc, "r1")
    assert row.run_id == "r1"
    assert row.state == "active"
    assert row.slug == "test"
    assert row.source_mode == "A"


def test_get_run_missing_raises(lc) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(KeyError):
        get_run(lc, "no-such-run")


def test_transition_run_active_to_done(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    transition_run(lc, "r1", "done")
    assert get_run(lc, "r1").state == "done"


def test_transition_run_terminal_idempotent(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    transition_run(lc, "r1", "done")
    # Same terminal state — no error
    transition_run(lc, "r1", "done")
    assert get_run(lc, "r1").state == "done"


def test_transition_run_terminal_to_different_raises(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    transition_run(lc, "r1", "done")
    with pytest.raises(ValueError, match="terminal state"):
        transition_run(lc, "r1", "active")


# ---------------------------------------------------------------------------
# Wave operations
# ---------------------------------------------------------------------------


def test_insert_wave_default_state(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    row = get_wave(lc, "r1", "p:W1")
    assert row.state == "queued"
    assert row.attempt_count == 0
    assert row.lane == "core"


def test_get_wave_missing_raises(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    with pytest.raises(KeyError):
        get_wave(lc, "r1", "no:such")


def test_wave_full_happy_path(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    for state in ("dispatched", "running", "verifying", "done"):
        transition_wave(lc, "r1", "p:W1", state)  # type: ignore[arg-type]
    assert get_wave(lc, "r1", "p:W1").state == "done"


def test_wave_terminal_guard(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    transition_wave(lc, "r1", "p:W1", "done")
    with pytest.raises(ValueError, match="terminal state"):
        transition_wave(lc, "r1", "p:W1", "queued")


def test_wave_terminal_idempotent(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    transition_wave(lc, "r1", "p:W1", "blocked")
    transition_wave(lc, "r1", "p:W1", "blocked")  # idempotent, no error
    assert get_wave(lc, "r1", "p:W1").state == "blocked"


def test_wave_gate_pending_state(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    insert_wave(
        lc,
        node_id="p:W0",
        run_id="r1",
        plan_id="p",
        wave_id="W0",
        lane="core",
        initial_state="gate_pending",
    )
    assert get_wave(lc, "r1", "p:W0").state == "gate_pending"


def test_list_waves_ordering(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    for wid in ("W0", "W1", "W2"):
        insert_wave(lc, node_id=f"p:{wid}", run_id="r1", plan_id="p", wave_id=wid, lane="l")
    ids = [w.wave_id for w in list_waves(lc, "r1")]
    assert ids == ["W0", "W1", "W2"]


# ---------------------------------------------------------------------------
# Attempt operations
# ---------------------------------------------------------------------------


def test_insert_attempt_increments_count(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    assert get_wave(lc, "r1", "p:W1").attempt_count == 1
    insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=2, backend="claude_code")
    assert get_wave(lc, "r1", "p:W1").attempt_count == 2


def test_end_attempt_sets_outcome(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    aid = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    end_attempt(lc, aid, outcome="done")
    rows = list_attempts(lc, "r1", "p:W1")
    assert len(rows) == 1
    assert rows[0].outcome == "done"
    assert rows[0].ended_at is not None


def test_end_attempt_with_evidence(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    aid = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    end_attempt(lc, aid, outcome="scope_breach", evidence="src/sevn/gateway/agent_turn.py")
    rows = list_attempts(lc, "r1", "p:W1")
    assert rows[0].evidence == "src/sevn/gateway/agent_turn.py"


def test_end_attempt_records_run_cost(lc) -> None:  # type: ignore[no-untyped-def]
    from tripll.ledger import get_run, get_run_cost

    _seed_run(lc)
    _seed_wave(lc)
    aid = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    end_attempt(lc, aid, outcome="done", cost_usd=1.25, input_tokens=100, output_tokens=50)
    assert get_run_cost(lc, "r1") == 1.25
    row = list_attempts(lc, "r1", "p:W1")[0]
    assert row.cost_usd == 1.25
    assert row.input_tokens == 100
    assert row.output_tokens == 50
    assert get_run(lc, "r1").cost_usd == 1.25


def test_list_attempts_order(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    for n in (1, 2, 3):
        insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=n, backend="claude_code")
    rows = list_attempts(lc, "r1", "p:W1")
    assert [r.attempt_n for r in rows] == [1, 2, 3]


def test_retry_escalate_pattern(lc) -> None:  # type: ignore[no-untyped-def]
    """Simulate tests-first model: 5 attempts → escalate to blocked."""
    _seed_run(lc)
    _seed_wave(lc)
    for n in range(1, 6):
        aid = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=n, backend="claude_code")
        end_attempt(lc, aid, outcome="failed", evidence=f"failure {n}")
        if n < 5:
            transition_wave(lc, "r1", "p:W1", "queued")
        else:
            transition_wave(lc, "r1", "p:W1", "blocked")

    w = get_wave(lc, "r1", "p:W1")
    assert w.state == "blocked"
    assert w.attempt_count == 5
    rows = list_attempts(lc, "r1", "p:W1")
    assert all(r.outcome == "failed" for r in rows)


def test_reset_wave_attempts_clears_rows(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc)
    insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
    reset_wave_attempts(lc, "r1", "p:W1")
    assert list_attempts(lc, "r1", "p:W1") == []
    w = get_wave(lc, "r1", "p:W1")
    assert w.attempt_count == 0


# ---------------------------------------------------------------------------
# latest_events_by_node (D2 / W0.2)
# ---------------------------------------------------------------------------


def test_latest_events_by_node_collapses_per_node(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    _seed_wave(lc, node_id="p:W1")
    insert_wave(lc, node_id="p:W2", run_id="r1", plan_id="p", wave_id="W2", lane="core")
    append_event(
        lc,
        run_id="r1",
        node_id="p:W1",
        phase="running",
        last_action="edit foo",
        input_tokens=10,
        output_tokens=5,
    )
    append_event(
        lc,
        run_id="r1",
        node_id="p:W1",
        phase="running",
        input_tokens=30,
        output_tokens=20,
        cost_usd=0.05,
    )
    append_event(lc, run_id="r1", node_id="p:W2", phase="dispatched", last_action="queued")

    latest = latest_events_by_node(lc, "r1")
    assert set(latest) == {"p:W1", "p:W2"}
    w1 = latest["p:W1"]
    assert w1.phase == "running"
    assert w1.last_action == "edit foo"
    assert w1.input_tokens == 30
    assert w1.output_tokens == 20
    assert w1.cost_usd == 0.05
    assert latest["p:W2"].phase == "dispatched"


def test_latest_events_by_node_empty_run(lc) -> None:  # type: ignore[no-untyped-def]
    _seed_run(lc)
    assert latest_events_by_node(lc, "r1") == {}
