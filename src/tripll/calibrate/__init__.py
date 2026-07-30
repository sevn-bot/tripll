"""Calibration loop — predicted first-pass probability scored against the ledger (W5)."""

from __future__ import annotations

from tripll.calibrate.predict import (
    PREDICTOR_VERSION,
    extract_wave_features,
    predict_first_pass_probability,
)
from tripll.calibrate.routing import dispatch_decisions_snapshot
from tripll.calibrate.score import (
    MIN_PRIOR_RUNS,
    brier_score,
    calibrate_run,
    first_attempt_pass_rate,
    wave_attempts_to_green,
)

__all__ = [
    "MIN_PRIOR_RUNS",
    "PREDICTOR_VERSION",
    "brier_score",
    "calibrate_run",
    "dispatch_decisions_snapshot",
    "extract_wave_features",
    "first_attempt_pass_rate",
    "predict_first_pass_probability",
    "wave_attempts_to_green",
]
