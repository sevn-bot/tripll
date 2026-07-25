"""Idempotency — commit keys, decide/commit split, reconciliation (W1.9)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module

_XFAIL = pytest.mark.xfail(reason="green after W7: idempotency harness", strict=False)

_RECON_CHECKS = [
    "attempt_still_current",
    "task_still_active",
    "no_prior_outcome",
    "target_unchanged",
    "idempotency_key_free",
    "artifact_is_latest",
]


@_XFAIL
def test_commit_node_same_key_runs_once() -> None:
    IdempotencyStore = require_module("tripll.loops.idempotency", attr="IdempotencyStore")
    store = IdempotencyStore(":memory:")
    key = "push:branch:wave-1"
    assert store.record_commit(key, action="git push") is True
    assert store.record_commit(key, action="git push") is False


@_XFAIL
def test_decide_node_has_no_side_effects() -> None:
    run_decide_node = require_module("tripll.loops.idempotency", attr="run_decide_node")
    receipt = run_decide_node({"kind": "decide", "inputs": {"action": "open_pr"}})
    assert receipt.get("side_effects") == []


@_XFAIL
@pytest.mark.parametrize("check_name", _RECON_CHECKS)
def test_pre_commit_reconciliation_blocks_on_conflict(check_name: str) -> None:
    reconcile_pre_commit = require_module("tripll.harness.reconcile", attr="reconcile_pre_commit")
    with pytest.raises((ValueError, RuntimeError), match=check_name.replace("_", ".*")):
        reconcile_pre_commit(
            attempt={"id": 1, "current": True},
            conflict=check_name,
        )


@_XFAIL
def test_destructive_action_refuses_retry() -> None:
    may_retry = require_module("tripll.loops.idempotency", attr="may_retry")
    assert may_retry({"destructive": True, "retries": "disabled"}) is False


@_XFAIL
def test_two_attempts_one_cancelled_one_delayed_only_current_commits() -> None:
    reconcile_pre_commit = require_module("tripll.harness.reconcile", attr="reconcile_pre_commit")
    result = reconcile_pre_commit(
        attempts=[
            {"id": 1, "cancelled": True, "tool_results": [{"delayed": True}]},
            {"id": 2, "cancelled": False, "tool_results": [{"ok": True}], "current": True},
        ]
    )
    assert result.committed_attempt_id == 2
