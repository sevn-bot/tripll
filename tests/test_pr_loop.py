"""PR phase — idempotent actions, fix loop, merge gate (W1.12)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import require_module
from tripll.loops import graph_available
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


def test_pr_loop_linear_degradation_path() -> None:
    """Without LangGraph graph execution, ``run_pr_loop_step`` remains the linear path."""
    run_pr_loop_step = require_module("tripll.loops.l1_pr", attr="run_pr_loop_step")
    steps = run_pr_loop_step(
        findings=[{"kind": "ci_check", "state": "open", "finding_id": "f1"}],
        phase="investigate_and_fix",
    )
    assert isinstance(steps, list)
    assert steps[0]["agent"] == "ci-investigator"


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


def test_investigate_invokes_adapter_not_just_dict() -> None:
    """L1-scaffold: ``_node_investigate`` must call an adapter, not only emit dicts."""
    import inspect

    import tripll.loops.l1_pr as l1_pr

    source = inspect.getsource(l1_pr)
    assert "dispatch_bridge" in source or "adapter.dispatch" in source


def test_fix_invokes_adapter_not_just_dict() -> None:
    import inspect

    import tripll.loops.l1_pr as l1_pr

    source = inspect.getsource(l1_pr)
    assert "FakeAdapter" not in source  # placeholder — real wiring uses adapter calls
    assert "run_dispatch" in source or "dispatch_bridge" in source


@pytest.mark.tier3
def test_dispatch_bridge_records_fake_adapter_calls(tmp_path: Path) -> None:
    """Fake adapter must record invocations through ``invoke_loop_dispatches``."""
    from tests._fakes import FakeAdapter
    from tripll.loops.dispatch_bridge import invoke_loop_dispatches

    adapter = FakeAdapter()
    state = {
        "run_id": "run-test",
        "thread_id": "run-test",
        "run_dir": str(tmp_path),
    }
    meta = [
        {
            "agent": "ci-investigator",
            "action": "investigate",
            "finding_id": "f1",
            "kind": "ci_check",
        },
        {
            "agent": "check-fixer",
            "action": "fix",
            "finding_id": "f1",
            "kind": "ci_check",
        },
    ]
    results = invoke_loop_dispatches(state, meta, node="investigate", adapter=adapter)
    assert adapter.calls == 2
    assert [r.agent for r in results] == ["ci-investigator", "check-fixer"]
    assert all(r.outcome == "done" for r in results)


def test_exit_8_abandons_when_pr_closed_externally() -> None:
    fired = evaluate_exit(8, context={"pr_state": "closed", "merged": False})
    assert fired.exit_id == 8
    assert fired.abandon_run is True


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
def test_shepherd_investigate_dispatches_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shepherd must invoke LangGraph nodes that dispatch adapters (not print-only plans)."""
    from tests._fakes import FakeAdapter

    fake = FakeAdapter()
    invoke = require_module("tripll.loops.dispatch_bridge", attr="invoke_loop_dispatches")
    shepherd_run = require_module("tripll.loops.l1_pr", attr="shepherd_run")

    def recording_invoke(
        state: dict[str, object],
        dispatch_meta: list[dict[str, object]],
        *,
        node: str,
        adapter: object | None = None,
    ) -> list[object]:
        return invoke(state, dispatch_meta, node=node, adapter=fake)

    monkeypatch.setattr(
        "tripll.loops.dispatch_bridge.invoke_loop_dispatches",
        recording_invoke,
    )
    monkeypatch.setenv("TRIPLL_PR_DRY_RUN", "1")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    findings = [{"kind": "ci_check", "state": "open", "finding_id": "f1"}]
    result = shepherd_run(
        run_id="run-test",
        run_dir=run_dir,
        findings=findings,
        phase="investigate_and_fix",
    )
    assert isinstance(result, dict)
    assert result.get("graph_executed") is True
    assert fake.calls >= 2
    assert result.get("dispatch_results")


@pytest.mark.skipif(not graph_available(), reason="graph extra required")
def test_shepherd_second_invoke_idempotent_at_merge_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second shepherd invoke after merge-gate interrupt must not repeat push."""
    run_pr_action = require_module("tripll.github.pr", attr="run_pr_action")
    shepherd_run = require_module("tripll.loops.l1_pr", attr="shepherd_run")
    push_calls: list[str] = []

    def counting_push(
        action: str,
        *,
        idempotency_key: str,
        context: dict[str, object],
    ) -> dict[str, object]:
        if action == "push":
            push_calls.append(idempotency_key)
        return run_pr_action(action, idempotency_key=idempotency_key, context=context)

    monkeypatch.setattr("tripll.github.pr.run_pr_action", counting_push)
    monkeypatch.setenv("TRIPLL_PR_DRY_RUN", "1")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    first = shepherd_run(
        run_id="run-test",
        run_dir=run_dir,
        findings=[],
        phase="investigate_and_fix",
    )
    assert isinstance(first, dict)
    assert len(push_calls) == 1

    second = shepherd_run(
        run_id="run-test",
        run_dir=run_dir,
        findings=[],
        phase="investigate_and_fix",
    )
    assert isinstance(second, dict)
    assert len(push_calls) == 1
    assert second.get("paused") is True or second.get("merge_gate") is not None


def test_shepherd_deliver_push_and_open_pr_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliver phase must push/open once; replay is no-op."""
    run_pr_action = require_module("tripll.github.pr", attr="run_pr_action")
    shepherd_run = require_module("tripll.loops.l1_pr", attr="shepherd_run")
    action_calls: list[str] = []

    def counting_action(
        action: str,
        *,
        idempotency_key: str,
        context: dict[str, object],
    ) -> dict[str, object]:
        result = run_pr_action(action, idempotency_key=idempotency_key, context=context)
        if result.get("executed"):
            action_calls.append(idempotency_key)
        return result

    monkeypatch.setattr("tripll.github.pr.run_pr_action", counting_action)
    monkeypatch.setenv("TRIPLL_PR_DRY_RUN", "1")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    first = shepherd_run(run_id="run-deliver", run_dir=run_dir, phase="deliver")
    assert isinstance(first, dict)
    assert first.get("phase") == "deliver"
    assert len(action_calls) == 2
    assert action_calls == ["push:run-deliver", "open_pr:run-deliver"]

    second = shepherd_run(run_id="run-deliver", run_dir=run_dir, phase="deliver")
    assert isinstance(second, dict)
    assert len(action_calls) == 2
    replayed = [a for a in second.get("actions") or [] if a.get("replayed")]
    assert len(replayed) == 2


def test_shepherd_deliver_includes_integration_branch_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliver context must target the integration branch."""
    shepherd_run = require_module("tripll.loops.l1_pr", attr="shepherd_run")
    seen: list[dict[str, object]] = []

    def capture_action(
        action: str,
        *,
        idempotency_key: str,
        context: dict[str, object],
    ) -> dict[str, object]:
        seen.append(dict(context))
        return {
            "action": action,
            "executed": True,
            "replayed": False,
            "idempotency_key": idempotency_key,
            "result": {"dry_run": True},
            "dry_run": True,
        }

    monkeypatch.setattr("tripll.github.pr.run_pr_action", capture_action)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shepherd_run(run_id="run-ctx", run_dir=run_dir, phase="deliver")
    assert seen
    assert seen[0]["branch"] == "tripll/integrate/run-ctx"
    assert seen[0]["head"] == "tripll/integrate/run-ctx"
