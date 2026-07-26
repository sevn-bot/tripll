"""PR phase — idempotent actions, fix loop, merge gate (W1.12)."""

from __future__ import annotations

from unittest.mock import patch

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
    assert first.get("dry_run") is True
    assert (first.get("result") or {}).get("dry_run") is True


def test_push_invokes_git_when_not_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TRIPLL_PR_DRY_RUN is off, push must call git push (not silent stub)."""
    monkeypatch.delenv("TRIPLL_PR_DRY_RUN", raising=False)
    run_pr_action = require_module("tripll.github.pr", attr="run_pr_action")
    with patch("tripll.github.pr._git", return_value="") as git_mock:
        result = run_pr_action(
            "push",
            idempotency_key="push:live:1",
            context={"run_id": "live", "branch": "wave/test", "repo_root": "/tmp/repo"},
        )
    git_mock.assert_called_once_with(
        ["push", "origin", "wave/test"],
        cwd="/tmp/repo",
    )
    assert result["executed"] is True
    assert result.get("dry_run") is False
    assert (result.get("result") or {}).get("dry_run") is not True


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


@pytest.mark.tier3
@pytest.mark.xfail(reason="green after W9: investigate node invokes adapter", strict=False)
def test_investigate_invokes_adapter_not_just_dict() -> None:
    """L1-scaffold: ``_node_investigate`` must call an adapter, not only emit dicts."""
    import inspect

    import tripll.loops.l1_pr as l1_pr

    source = inspect.getsource(l1_pr)
    assert "dispatch_bridge" in source or "adapter.dispatch" in source


@pytest.mark.tier3
@pytest.mark.xfail(reason="green after W9: fix node invokes adapter", strict=False)
def test_fix_invokes_adapter_not_just_dict() -> None:
    import inspect

    import tripll.loops.l1_pr as l1_pr

    source = inspect.getsource(l1_pr)
    assert "FakeAdapter" not in source  # placeholder — real wiring uses adapter calls
    assert "run_dispatch" in source or "dispatch_bridge" in source


def test_exit_8_abandons_when_pr_closed_externally() -> None:
    fired = evaluate_exit(8, context={"pr_state": "closed", "merged": False})
    assert fired.exit_id == 8
    assert fired.abandon_run is True
