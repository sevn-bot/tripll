"""Human-gate config — prompt, auto_accept, fail, and canary parking (P0.8)."""

from __future__ import annotations

from tripll.plan.human_gates import (
    CanaryResult,
    HumanGateOutcome,
    evaluate_ci_billing_canary,
    resolve_human_gate_mode,
    resolve_pre0_gate,
)


def test_env_override_wins_over_plan_pipeline() -> None:
    mode = resolve_human_gate_mode(
        {"human_gates": "fail"},
        env={"TRIPLL_HUMAN_GATES": "auto_accept"},
    )
    assert mode == "auto_accept"


def test_auto_accept_red_canary_parks() -> None:
    outcome = resolve_pre0_gate(
        mode="auto_accept",
        canary=CanaryResult(ok=False, detail="blocked"),
    )
    assert outcome is HumanGateOutcome.PARKED


def test_auto_accept_green_canary_proceeds() -> None:
    outcome = resolve_pre0_gate(
        mode="auto_accept",
        canary=CanaryResult(ok=True, detail="completed"),
    )
    assert outcome is HumanGateOutcome.PROCEED


def test_fail_mode_rejects_without_prompt() -> None:
    assert resolve_pre0_gate(mode="fail") is HumanGateOutcome.FAIL


def test_evaluate_ci_billing_canary_parses_gh_json(monkeypatch) -> None:
    class _Proc:
        returncode = 0
        stdout = '[{"status":"completed","databaseId":"123"}]'
        stderr = ""

    monkeypatch.setattr("tripll.plan.human_gates.subprocess.run", lambda *a, **k: _Proc())
    result = evaluate_ci_billing_canary(env={"PATH": "/usr/bin"})
    assert result.ok is True
    assert result.run_id == "123"
