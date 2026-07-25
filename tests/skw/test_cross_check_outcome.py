"""Regression tests for cross_check_outcome fail-loud semantics (Fix-W1.5)."""

from __future__ import annotations

import pytest

from tripll.skw.pipeline import cross_check_outcome
from tripll.skw.states import PipelineState


@pytest.mark.parametrize(
    "verdict",
    [
        "",
        "unknown",
        "ship",
        "REQUEST CHANGES",
        "approve",
    ],
)
def test_cross_check_unknown_verdict_raises(verdict: str) -> None:
    state: PipelineState = {
        "verdict": verdict,
        "new_wave_files": [],
    }
    with pytest.raises(ValueError, match=r"verdict|unknown|invalid"):
        cross_check_outcome(state)


def test_cross_check_missing_verdict_raises() -> None:
    state: PipelineState = {"new_wave_files": []}
    with pytest.raises(ValueError, match=r"verdict|missing|unknown"):
        cross_check_outcome(state)
