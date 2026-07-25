"""LangGraph recovery — kill/resume and ledger fallback (W1.14)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module

_XFAIL = pytest.mark.xfail(reason="green after W6: LangGraph recovery", strict=False)


@_XFAIL
def test_kill_mid_loop_resumes_same_thread_id() -> None:
    simulate_recovery = require_module("tripll.loops.l1_outer", attr="simulate_recovery")
    result = simulate_recovery(
        thread_id="run-abc",
        checkpoint_db=":memory:",
        kill_after_node="verify",
    )
    assert result["thread_id"] == "run-abc"
    assert result["resumed_from"] == "verify"
    assert result["state_preserved"] is True


@_XFAIL
def test_deleted_checkpoint_recoverable_from_ledger() -> None:
    recover_from_ledger = require_module("tripll.loops.l1_outer", attr="recover_from_ledger")
    ledger = require_module("tripll.ledger", attr="open_ledger")(":memory:")
    result = recover_from_ledger(
        run_id="run-abc",
        ledger=ledger,
        checkpoint_db=":memory:",
        delete_checkpoint=True,
    )
    assert result["recovered"] is True
    assert result["source"] == "ledger"
