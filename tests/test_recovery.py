"""LangGraph recovery — kill/resume and ledger fallback (W1.14)."""

from __future__ import annotations

from tripll.ledger import open_ledger
from tripll.loops.l1_outer import recover_from_ledger, simulate_recovery


def test_kill_mid_loop_resumes_same_thread_id() -> None:
    result = simulate_recovery(
        thread_id="run-abc",
        checkpoint_db=":memory:",
        kill_after_node="verify",
    )
    assert result["thread_id"] == "run-abc"
    assert result["resumed_from"] == "verify"
    assert result["state_preserved"] is True


def test_deleted_checkpoint_recoverable_from_ledger() -> None:
    ledger = open_ledger(":memory:")
    result = recover_from_ledger(
        run_id="run-abc",
        ledger=ledger,
        checkpoint_db=":memory:",
        delete_checkpoint=True,
    )
    assert result["recovered"] is True
    assert result["source"] == "ledger"
