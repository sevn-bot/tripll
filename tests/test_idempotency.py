"""Idempotency — commit keys, decide/commit split, reconciliation (W1.9)."""

from __future__ import annotations

import pytest

from tripll.harness.reconcile import reconcile_pre_commit
from tripll.loops.idempotency import IdempotencyStore, may_retry, run_decide_node

_RECON_CHECKS = [
    "attempt_still_current",
    "task_still_active",
    "no_prior_outcome",
    "target_unchanged",
    "idempotency_key_free",
    "artifact_is_latest",
]


def test_commit_node_same_key_runs_once() -> None:
    store = IdempotencyStore(":memory:")
    key = "push:branch:wave-1"
    assert store.record_commit(key, action="git push") is True
    assert store.record_commit(key, action="git push") is False


def test_decide_node_has_no_side_effects() -> None:
    receipt = run_decide_node({"kind": "decide", "inputs": {"action": "open_pr"}})
    assert receipt.get("side_effects") == []


@pytest.mark.parametrize("check_name", _RECON_CHECKS)
def test_pre_commit_reconciliation_blocks_on_conflict(check_name: str) -> None:
    with pytest.raises((ValueError, RuntimeError), match=check_name.replace("_", ".*")):
        reconcile_pre_commit(
            attempt={"id": 1, "current": True},
            conflict=check_name,
        )


def test_destructive_action_refuses_retry() -> None:
    assert may_retry({"destructive": True, "retries": "disabled"}) is False


def test_two_attempts_one_cancelled_one_delayed_only_current_commits() -> None:
    result = reconcile_pre_commit(
        attempts=[
            {"id": 1, "cancelled": True, "tool_results": [{"delayed": True}]},
            {"id": 2, "cancelled": False, "tool_results": [{"ok": True}], "current": True},
        ]
    )
    assert result.committed_attempt_id == 2
