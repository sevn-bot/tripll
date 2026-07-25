"""PR phase — idempotent actions, fix loop, merge gate (W1.12)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module
from tripll.loops.exits import evaluate_exit


@pytest.mark.parametrize("action", ["push", "open_pr", "comment"])
def test_external_actions_idempotent_under_replay(action: str) -> None:
    run_pr_action = require_module("tripll.github.pr", attr="run_pr_action")
    key = f"{action}:run-1:sha-abc"
    first = run_pr_action(action, idempotency_key=key, context={"run_id": "r1"})
    second = run_pr_action(action, idempotency_key=key, context={"run_id": "r1"})
    assert first["executed"] is True
    assert second["executed"] is False
    assert second["replayed"] is True


def test_loop_dispatches_investigator_then_fixer() -> None:
    run_pr_loop_step = require_module("tripll.loops.l1_pr", attr="run_pr_loop_step")
    steps = run_pr_loop_step(
        findings=[{"kind": "ci_check", "state": "open"}],
        phase="investigate_and_fix",
    )
    roles = [s["agent"] for s in steps]
    assert "ci-investigator" in roles
    assert "check-fixer" in roles
    assert roles.index("ci-investigator") < roles.index("check-fixer")


def test_parks_at_merge_gate_never_auto_merges() -> None:
    run_pr_loop_step = require_module("tripll.loops.l1_pr", attr="run_pr_loop_step")
    result = run_pr_loop_step(findings=[], phase="merge", ci_green=True, review_clean=True)
    assert result["state"] == "merge_gate_pending"
    assert result.get("merged") is not True


def test_exit_8_abandons_when_pr_closed_externally() -> None:
    fired = evaluate_exit(8, context={"pr_state": "closed", "merged": False})
    assert fired.exit_id == 8
    assert fired.abandon_run is True
