"""Tests for Makefile next-step hint computation (Wave W1.4)."""

from __future__ import annotations

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.nextstep import compute_next_step

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"


def test_next_step_after_test_author_complete() -> None:
    hint = compute_next_step(
        wave_file=PIPELINE_FIXTURE,
        kit_root=KIT_ROOT,
        wave_id="W1",
    )
    assert "wave-runner-run" in hint
    assert "WAVE=" in hint
    assert "WAVE_ID=W2" in hint


def test_next_step_reviewer_after_all_impl_waves() -> None:
    hint = compute_next_step(
        wave_file=PIPELINE_FIXTURE,
        kit_root=KIT_ROOT,
        wave_id="Final",
        all_impl_complete=True,
    )
    assert "reviewer-run" in hint


def test_next_step_generator_on_changes_required() -> None:
    hint = compute_next_step(
        wave_file=PIPELINE_FIXTURE,
        kit_root=KIT_ROOT,
        verdict="changes_required",
    )
    assert "post-review-wave-generator-run" in hint


def test_next_step_pass_when_done() -> None:
    hint = compute_next_step(
        wave_file=PIPELINE_FIXTURE,
        kit_root=KIT_ROOT,
        plan_complete=True,
    )
    assert hint.strip().upper() == "PASS"


def test_next_step_pending_test_author() -> None:
    hint = compute_next_step(
        wave_file=PIPELINE_FIXTURE,
        kit_root=KIT_ROOT,
    )
    assert "test-creator-run" in hint
    assert "WAVE_ID=W1" in hint
