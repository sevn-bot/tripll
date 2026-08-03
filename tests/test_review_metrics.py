"""Tests for review-quality benchmark metrics (#64 W4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripll.bench import METRIC_KEYS
from tripll.bench.review_harbor import baseline_issue_to_mergecraft_finding
from tripll.bench.review_metrics import (
    REVIEW_METRIC_KEYS,
    aggregate_review_metrics,
    compute_review_deltas,
    compute_review_task_metrics,
    load_review_baseline,
    score_review_track,
)


def _issue(
    issue_id: str,
    *,
    context: bool = False,
    path: str = "src/demo.py",
) -> dict[str, object]:
    return {
        "id": issue_id,
        "repo": "sevn-bot/tripll",
        "pr": 64,
        "head_sha": "abc123",
        "path": path,
        "line_range": [1, 1],
        "title": f"Issue {issue_id}",
        "description": "Details",
        "provenance": "human",
        "requires_context_outside_diff": context,
    }


def test_review_metric_keys_separate_from_frozen_l1_keys() -> None:
    overlap = set(METRIC_KEYS) & set(REVIEW_METRIC_KEYS)
    assert not overlap
    assert len(REVIEW_METRIC_KEYS) == 6


def test_perfect_oracle_scores_one_point() -> None:
    issues = [_issue("tripll-pr64-01"), _issue("tripll-pr64-02", context=True)]
    predicted = [baseline_issue_to_mergecraft_finding(issue) for issue in issues]
    metrics = compute_review_task_metrics(issues, predicted)
    assert metrics["review_coverage"] == 1.0
    assert metrics["review_precision"] == 1.0
    assert metrics["review_f1"] == 1.0
    assert metrics["review_coverage_context_dependent"] == 1.0
    assert metrics["review_noise_rate"] == 0.0


def test_partial_coverage_and_precision() -> None:
    issues = [_issue("tripll-pr64-01"), _issue("tripll-pr64-02")]
    predicted = [baseline_issue_to_mergecraft_finding(issues[0])]
    metrics = compute_review_task_metrics(issues, predicted)
    assert metrics["review_coverage"] == 0.5
    assert metrics["review_precision"] == 1.0
    assert metrics["review_f1"] == pytest.approx(2.0 / 3.0)


def test_noise_rate_counts_unmatched_and_over_budget() -> None:
    issues = [_issue("tripll-pr64-01")]
    oracle = baseline_issue_to_mergecraft_finding(issues[0])
    spurious = dict(oracle)
    spurious["fingerprint"] = "deadbeef" * 3
    predicted = [oracle, spurious, spurious]
    metrics = compute_review_task_metrics(issues, predicted, inline_budget=1)
    assert metrics["review_noise_rate"] == pytest.approx(2.0 / 3.0)


def test_context_dependent_coverage_ignores_diff_local_issues() -> None:
    issues = [_issue("tripll-pr64-01", context=False), _issue("tripll-pr64-02", context=True)]
    predicted = [baseline_issue_to_mergecraft_finding(issues[1])]
    metrics = compute_review_task_metrics(issues, predicted)
    assert metrics["review_coverage"] == 0.5
    assert metrics["review_coverage_context_dependent"] == 1.0


def test_aggregate_and_deltas() -> None:
    first = compute_review_task_metrics([_issue("a-01")], [])
    second = compute_review_task_metrics(
        [_issue("b-01")],
        [baseline_issue_to_mergecraft_finding(_issue("b-01"))],
    )
    aggregated = aggregate_review_metrics([first, second])
    assert aggregated["review_coverage"] == 0.5
    baseline = {key: 0.0 for key in REVIEW_METRIC_KEYS}
    deltas = compute_review_deltas(aggregated, baseline)
    assert deltas["review_coverage"] == 0.5


def test_load_review_baseline_from_fixture() -> None:
    baseline = load_review_baseline(Path("bench"))
    assert baseline["review_f1"] == 1.0
    assert set(baseline) == set(REVIEW_METRIC_KEYS)


def test_score_review_track_on_emitted_harbor_task() -> None:
    task_dir = Path("bench/review/tripll-pr64")
    baseline = Path("bench/review/baseline.jsonl")
    if not task_dir.is_dir() or not baseline.is_file():
        pytest.skip("committed Harbor review task missing")
    result = score_review_track(Path("bench"))
    assert result.task_count >= 1
    assert result.metrics["review_f1"] == pytest.approx(1.0)
    assert set(result.metrics) == set(REVIEW_METRIC_KEYS)


def test_golden_findings_payload_is_valid_envelope() -> None:
    golden = Path("bench/review/tripll-pr64/solution/golden_findings.json")
    if not golden.is_file():
        pytest.skip("golden findings missing")
    payload = json.loads(golden.read_text(encoding="utf-8"))
    assert isinstance(payload.get("findings"), list)
    assert payload["findings"]
