"""Wave postmortem — contract vs attempt reconciliation (W1.5)."""

from __future__ import annotations

import pytest

from tests.rules._helpers import require_attr

pytestmark = pytest.mark.tier1


def _sample_contract() -> dict[str, object]:
    return {
        "wave_id": "W2",
        "required": ["tripll rules derive writes .tripll/rules"],
        "forbidden": ["a rule written without an origin"],
        "targets": ["src/tripll/rules/derive.py"],
    }


def _sample_attempt(*, outcome: str, scope_breach: bool = False) -> dict[str, object]:
    return {
        "wave_id": "W2",
        "outcome": outcome,
        "attempt_n": 3,
        "scope_breaches": ["src/tripll/cli/__init__.py"] if scope_breach else [],
        "verify_results": {"make test": "failed"},
        "touched_paths": ["src/tripll/cli/__init__.py"],
    }


@pytest.mark.xfail(reason="green after W3: postmortem contract-too-vague", strict=False)
def test_postmortem_contract_too_vague_when_required_unmet_without_breach() -> None:
    """When verify fails but agent stayed in scope, blame the contract (RULE-03)."""
    classify_wave_delta = require_attr("tripll.rules.postmortem", "classify_wave_delta")
    verdict = classify_wave_delta(
        contract=_sample_contract(),
        attempt=_sample_attempt(outcome="failed", scope_breach=False),
    )
    assert str(verdict) == "contract-too-vague"


@pytest.mark.xfail(reason="green after W3: postmortem agent-diverged", strict=False)
def test_postmortem_agent_diverged_when_scope_breached() -> None:
    """Scope breach or forbidden touch ⇒ agent diverged, not vague contract."""
    classify_wave_delta = require_attr("tripll.rules.postmortem", "classify_wave_delta")
    verdict = require_attr("tripll.rules.postmortem", "PostmortemVerdict")
    result = classify_wave_delta(
        contract=_sample_contract(),
        attempt=_sample_attempt(outcome="failed", scope_breach=True),
    )
    assert result == verdict.AGENT_DIVERGED or str(result) == "agent-diverged"


@pytest.mark.xfail(reason="green after W3: postmortem render names wrong side", strict=False)
def test_postmortem_render_names_which_side_was_wrong() -> None:
    """Rendered postmortem must state contract vs agent (W3 outcome)."""
    render_postmortem = require_attr("tripll.rules.postmortem", "render_postmortem")
    classify_wave_delta = require_attr("tripll.rules.postmortem", "classify_wave_delta")
    contract = _sample_contract()
    attempt = _sample_attempt(outcome="failed", scope_breach=True)
    verdict = classify_wave_delta(contract=contract, attempt=attempt)
    text = render_postmortem(contract=contract, attempt=attempt, verdict=verdict)
    lowered = text.lower()
    assert "agent" in lowered or "contract" in lowered
    assert "diverged" in lowered or "vague" in lowered
