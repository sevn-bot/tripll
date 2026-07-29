"""Calibration — Brier score and advisory-only predictor (W1.6, R28)."""

from __future__ import annotations

import pytest

from tests.rules._helpers import require_attr

pytestmark = pytest.mark.tier1

# Fixed vectors — hand-computed Brier = mean((p - y)^2)
_BRIER_PREDICTIONS = (0.9, 0.1, 0.8, 0.2)
_BRIER_OUTCOMES = (1, 0, 1, 0)
_EXPECTED_BRIER = sum(
    (p - y) ** 2 for p, y in zip(_BRIER_PREDICTIONS, _BRIER_OUTCOMES, strict=False)
) / len(_BRIER_PREDICTIONS)


def test_brier_score_fixed_vectors() -> None:
    """CAL-02: deterministic Brier score for known predictions/outcomes."""
    brier_score = require_attr("tripll.calibrate.score", "brier_score")
    score = brier_score(list(_BRIER_PREDICTIONS), list(_BRIER_OUTCOMES))
    assert score == pytest.approx(_EXPECTED_BRIER, abs=1e-9)


def test_predict_first_pass_probability_bounded() -> None:
    """Predictor returns a probability in [0, 1] for compile-time features."""
    predict_first_pass_probability = require_attr(
        "tripll.calibrate.predict",
        "predict_first_pass_probability",
    )
    prob = predict_first_pass_probability(
        {
            "module_count": 4,
            "calls_fan_out": 12,
            "effort": "M",
            "target_count": 3,
            "contract_clause_count": 5,
            "active_rule_overlap": 1,
        }
    )
    assert 0.0 <= prob <= 1.0


def test_prediction_does_not_change_routing() -> None:
    """R28: predictor on vs off yields byte-identical dispatch decisions."""
    dispatch_decisions_snapshot = require_attr(
        "tripll.calibrate.routing",
        "dispatch_decisions_snapshot",
    )
    sample_plan = {
        "waveorch_format": 3,
        "title": "calibrate-routing-fixture",
        "slug": "cal-routing",
        "waves": [
            {
                "id": "W1",
                "title": "one",
                "role": "impl",
                "effort": "S",
                "targets": ["src/tripll/demo.py"],
            }
        ],
    }
    off = dispatch_decisions_snapshot(plan=sample_plan, predictor_enabled=False)
    on = dispatch_decisions_snapshot(plan=sample_plan, predictor_enabled=True)
    assert off == on
