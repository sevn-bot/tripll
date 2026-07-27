"""Quality gate — semantic extractors only, precision threshold (W1.5)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ("IMPLEMENTS", True),
        ("ABOUT", True),
        ("DECLARES", False),
        ("CALLS", False),
        ("COVERS", False),
    ],
)
def test_gate_applies_only_to_semantic_extractors(predicate: str, expected: bool) -> None:
    applies_to = require_module("tripll.extract.quality_gate", attr="applies_to")
    assert applies_to(predicate) is expected


def test_low_precision_blocks_and_records_prompt_fix() -> None:
    run_quality_gate = require_module("tripll.extract.quality_gate", attr="run_quality_gate")
    verdict = run_quality_gate(
        predicate="IMPLEMENTS",
        sample_size=50,
        precision=0.85,
    )
    assert verdict["passed"] is False
    remedy = verdict["remedy"].lower()
    assert "prompt" in remedy or "rule" in remedy
    assert "graph" not in remedy or "never" in remedy
