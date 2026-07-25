"""Outcome contracts — unverified state, grader rendering (W1.8)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module

_XFAIL = pytest.mark.xfail(reason="green after W7: outcome contracts", strict=False)


@_XFAIL
def test_all_required_and_not_forbidden() -> None:
    evaluate_outcome = require_module("tripll.harness.contracts", attr="evaluate_outcome")
    result = evaluate_outcome(
        required=["make test"],
        forbidden=["make ci"],
        grader_output={"make test": "pass", "make ci": "not_run"},
    )
    assert result.passed is True


@_XFAIL
def test_grader_cannot_run_yields_unverified() -> None:
    evaluate_outcome = require_module("tripll.harness.contracts", attr="evaluate_outcome")
    result = evaluate_outcome(required=["missing-grader"], forbidden=[], grader_output=None)
    assert result.state == "unverified"
    assert result.passed is not True


@_XFAIL
def test_completion_message_renders_grader_output() -> None:
    render_completion = require_module("tripll.harness.contracts", attr="render_completion")
    msg = render_completion(
        grader_output={"make test": "pass", "scope": "ok"},
        agent_claim="I finished everything perfectly",
    )
    assert "make test" in msg
    assert "pass" in msg
    assert "perfectly" not in msg


@_XFAIL
def test_plausible_artifact_broken_outcome_fails() -> None:
    evaluate_outcome = require_module("tripll.harness.contracts", attr="evaluate_outcome")
    result = evaluate_outcome(
        required=["tests pass"],
        forbidden=[],
        grader_output={"tests pass": "fail"},
        artifact_present=True,
    )
    assert result.passed is False
