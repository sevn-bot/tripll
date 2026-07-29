"""Outcome contracts — unverified state, grader rendering (W1.8)."""

from __future__ import annotations

from tripll.harness.contracts import evaluate_outcome, render_completion


def test_all_required_and_not_forbidden() -> None:
    result = evaluate_outcome(
        required=["make test"],
        forbidden=["make ci-resume"],
        grader_output={"make test": "pass", "make ci-resume": "not_run"},
    )
    assert result.passed is True


def test_grader_cannot_run_yields_unverified() -> None:
    result = evaluate_outcome(required=["missing-grader"], forbidden=[], grader_output=None)
    assert result.state == "unverified"
    assert result.passed is not True


def test_completion_message_renders_grader_output() -> None:
    msg = render_completion(
        grader_output={"make test": "pass", "scope": "ok"},
        agent_claim="I finished everything perfectly",
    )
    assert "make test" in msg
    assert "pass" in msg
    assert "perfectly" not in msg


def test_parse_outcome_contract_defaults_quality_fields() -> None:
    from tripll.harness.contracts import parse_outcome_contract

    outcome = parse_outcome_contract(None)
    assert outcome["required"] == []
    assert outcome["reference"]["kind"] == ""
    assert outcome["quality_gauntlet"]["enabled"] is False


def test_plausible_artifact_broken_outcome_fails() -> None:
    result = evaluate_outcome(
        required=["tests pass"],
        forbidden=[],
        grader_output={"tests pass": "fail"},
        artifact_present=True,
    )
    assert result.passed is False
