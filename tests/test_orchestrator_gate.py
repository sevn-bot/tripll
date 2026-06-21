"""Tests for tripll.orchestrator_gate -- gate parser heuristics v2."""

from tripll.orchestrator_gate import parse_gate_result

# ---------------------------------------------------------------------------
# Structured token (DECISION: APPROVE / DECISION: STOP)
# ---------------------------------------------------------------------------


def test_decision_approve_structured() -> None:
    assert parse_gate_result("DECISION: APPROVE").proceed is True


def test_decision_stop_structured() -> None:
    assert parse_gate_result("DECISION: STOP").proceed is False


def test_decision_approve_case_insensitive() -> None:
    assert parse_gate_result("decision: approve").proceed is True


def test_decision_stop_case_insensitive() -> None:
    assert parse_gate_result("decision: stop").proceed is False


def test_decision_approve_with_surrounding_text() -> None:
    text = "Everything looks good.\n\nDECISION: APPROVE"
    assert parse_gate_result(text).proceed is True


def test_decision_stop_with_surrounding_text() -> None:
    text = "Blockers remain.\n\nDECISION: STOP"
    assert parse_gate_result(text).proceed is False


def test_decision_approve_extra_whitespace() -> None:
    assert parse_gate_result("DECISION :  APPROVE").proceed is True


# ---------------------------------------------------------------------------
# Hardened heuristics -- explicit negatives
# ---------------------------------------------------------------------------


def test_disapprove_is_rejected() -> None:
    """'disapprove' must NOT match 'approve' -- fail closed."""
    assert parse_gate_result("I disapprove of this, do not continue.").proceed is False


def test_do_not_approve_is_rejected() -> None:
    assert parse_gate_result("I do not approve of these changes.").proceed is False


def test_reject_is_rejected() -> None:
    assert parse_gate_result("I reject this wave.").proceed is False


def test_blocked_is_rejected() -> None:
    assert parse_gate_result("This wave is blocked by failing tests.").proceed is False


def test_do_not_proceed_is_rejected() -> None:
    assert parse_gate_result("Do not proceed until fixes land.").proceed is False


def test_plain_stop_lowercase() -> None:
    assert parse_gate_result("stop -- blockers remain").proceed is False


# ---------------------------------------------------------------------------
# Hardened heuristics -- explicit positives
# ---------------------------------------------------------------------------


def test_changes_approved() -> None:
    assert parse_gate_result("Changes approved.").proceed is True


def test_approve_to_continue() -> None:
    assert parse_gate_result("Operator: approve to continue.").proceed is True


def test_dispatch_w1() -> None:
    assert parse_gate_result("dispatch W1 when ready").proceed is True


def test_approved_word() -> None:
    assert parse_gate_result("All items approved and verified.").proceed is True


# ---------------------------------------------------------------------------
# Ambiguous / edge cases -> fail closed
# ---------------------------------------------------------------------------


def test_ambiguous_text_fails_closed() -> None:
    assert parse_gate_result("I'm not sure about this.").proceed is False


def test_empty_text_fails_closed() -> None:
    assert parse_gate_result("").proceed is False


def test_none_text_fails_closed() -> None:
    # parse_gate_result handles None via ``(text or "")``
    assert parse_gate_result(None).proceed is False  # type: ignore[arg-type]


def test_summary_is_first_line() -> None:
    result = parse_gate_result("First line\nSecond line")
    assert result.summary == "First line"


def test_raw_text_preserved() -> None:
    text = "DECISION: APPROVE\nSome details."
    result = parse_gate_result(text)
    assert result.raw_text == text
