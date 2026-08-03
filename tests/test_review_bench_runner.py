"""Tests for review-track benchmark runner (#64 W5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripll.bench.review_runner import (
    DEFAULT_REVIEW_REGRESSION_THRESHOLD,
    resolve_review_regression_threshold,
    review_bench_dashboard_payload,
    run_review_benchmark,
    write_review_bench_dashboard,
)


def test_resolve_review_regression_threshold_explicit() -> None:
    assert resolve_review_regression_threshold(0.1) == pytest.approx(0.1)


def test_resolve_review_regression_threshold_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPLL_REVIEW_BENCH_REGRESSION_THRESHOLD", "0.02")
    assert resolve_review_regression_threshold() == pytest.approx(0.02)


def test_resolve_review_regression_threshold_default() -> None:
    assert resolve_review_regression_threshold() == pytest.approx(
        DEFAULT_REVIEW_REGRESSION_THRESHOLD,
    )


def test_run_review_benchmark_oracle_green() -> None:
    task_dir = Path("bench/review/tripll-pr64")
    baseline = Path("bench/review/baseline.jsonl")
    if not task_dir.is_dir() or not baseline.is_file():
        pytest.skip("committed Harbor review task missing")
    result = run_review_benchmark(bench_dir=Path("bench"), attempts=3)
    assert result.task_count >= 1
    assert result.attempts_per_task == 3
    assert result.metrics["review_f1"] == pytest.approx(1.0)
    assert result.review_f1_delta == pytest.approx(0.0)
    assert result.regression_failed is False
    assert result.mergecraft_ref


def test_regression_failed_when_f1_delta_below_threshold() -> None:
    """Regression fires when review_f1 delta is more negative than threshold."""
    from tripll.bench.review_metrics import REVIEW_METRIC_KEYS
    from tripll.bench.review_runner import ReviewBenchRunResult

    baseline = {key: 1.0 for key in REVIEW_METRIC_KEYS}
    metrics = dict(baseline)
    metrics["review_f1"] = 0.9
    deltas = {key: metrics[key] - baseline[key] for key in REVIEW_METRIC_KEYS}
    threshold = 0.05
    result = ReviewBenchRunResult(
        task_count=1,
        attempts_per_task=3,
        mergecraft_ref="deadbeef",
        metrics=metrics,
        baseline=baseline,
        deltas=deltas,
        regression_threshold=threshold,
        regression_failed=deltas["review_f1"] < -threshold,
        review_f1_delta=deltas["review_f1"],
    )
    assert result.regression_failed is True


def test_dashboard_payload_and_write(tmp_path: Path) -> None:
    task_dir = Path("bench/review/tripll-pr64")
    if not task_dir.is_dir():
        pytest.skip("committed Harbor review task missing")
    result = run_review_benchmark(bench_dir=Path("bench"), attempts=2)
    payload = review_bench_dashboard_payload(result)
    assert payload["track"] == "review"
    assert payload["review_f1_delta"] == result.review_f1_delta
    assert payload["mergecraft_ref"] == result.mergecraft_ref
    assert payload["attempts_per_task"] == 2

    out = tmp_path / "bench-review.json"
    written = write_review_bench_dashboard(result, out)
    assert written == out
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["review_f1"] == payload["review_f1"]
