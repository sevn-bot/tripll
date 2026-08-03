"""Review-quality metrics for the frozen Harbor review track (#64 W4).

Exports:
    REVIEW_METRIC_KEYS — sibling metric set separate from frozen ``METRIC_KEYS`` (D23).
    DEFAULT_INLINE_FINDINGS_BUDGET — per-task inline finding cap for noise scoring.
    ReviewBenchResult — aggregated review-track snapshot with baseline deltas.
    load_review_baseline — load committed review baseline metrics.
    normalize_mergecraft_finding — canonical finding dict for fingerprint comparison.
    compute_review_task_metrics — score one task's predictions vs baseline issues.
    aggregate_review_metrics — mean metrics across Harbor review tasks.
    compute_review_deltas — delta map vs a review baseline snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — bench paths resolved at runtime
from typing import Any

from tripll.bench.review_harbor import baseline_issue_to_mergecraft_finding
from tripll.github.findings import load_baseline_issues

REVIEW_METRIC_KEYS = (
    "review_coverage",
    "review_precision",
    "review_f1",
    "review_coverage_context_dependent",
    "review_noise_rate",
    "review_cost_per_task",
)

DEFAULT_INLINE_FINDINGS_BUDGET = 12

__all__ = [
    "DEFAULT_INLINE_FINDINGS_BUDGET",
    "REVIEW_METRIC_KEYS",
    "ReviewBenchResult",
    "aggregate_review_metrics",
    "compute_review_deltas",
    "compute_review_task_metrics",
    "load_review_baseline",
    "normalize_mergecraft_finding",
]


@dataclass(frozen=True, slots=True)
class ReviewBenchResult:
    """Review-track metric snapshot and deltas vs baseline."""

    task_count: int
    metrics: dict[str, float]
    baseline: dict[str, float]
    deltas: dict[str, float]


def normalize_mergecraft_finding(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical mergeCraft finding dict for stable fingerprint comparison."""
    start = int(raw.get("start_line") or 1)
    end = int(raw.get("end_line") or start)
    return {
        "category": str(raw.get("category") or ""),
        "confidence": str(raw.get("confidence") or ""),
        "end_line": end,
        "fingerprint": str(raw.get("fingerprint") or ""),
        "message": str(raw.get("message") or ""),
        "path": str(raw.get("path") or ""),
        "rule_id": str(raw.get("rule_id") or ""),
        "severity": str(raw.get("severity") or ""),
        "start_line": start,
        "tool": str(raw.get("tool") or ""),
    }


def _fingerprint(raw: dict[str, Any]) -> str:
    return str(normalize_mergecraft_finding(raw).get("fingerprint") or "")


def _harmonic_f1(coverage: float, precision: float) -> float:
    if coverage <= 0.0 or precision <= 0.0:
        return 0.0
    return 2.0 * coverage * precision / (coverage + precision)


def _context_flag(issue: dict[str, Any]) -> bool:
    raw = issue.get("requires_context_outside_diff")
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return bool(raw)


def compute_review_task_metrics(
    baseline_issues: list[dict[str, Any]],
    predicted_findings: list[dict[str, Any]],
    *,
    cost_usd: float = 0.0,
    inline_budget: int = DEFAULT_INLINE_FINDINGS_BUDGET,
) -> dict[str, float]:
    """Score one Harbor review task against curated baseline issues.

    Matching uses mergeCraft ``fingerprint`` equality — the same contract as
    ``bench/review/*/tests/verify_findings.py``. Coverage counts baseline issues
    with at least one matching prediction; precision counts predictions whose
    fingerprint appears in the baseline oracle set. ``review_noise_rate`` counts
    predictions that miss the baseline or exceed the inline budget.

    Args:
        baseline_issues: Curated baseline JSONL records for the task.
        predicted_findings: Agent or oracle mergeCraft finding objects.
        cost_usd: Optional USD spend attributed to this task attempt.
        inline_budget: Maximum inline findings before surplus counts as noise.

    Returns:
        Mapping keyed by ``REVIEW_METRIC_KEYS``.
    """
    expected = {
        _fingerprint(baseline_issue_to_mergecraft_finding(issue)): issue
        for issue in baseline_issues
        if issue.get("id")
    }
    predicted = [_fingerprint(row) for row in predicted_findings if _fingerprint(row)]
    matched = {fp for fp in predicted if fp in expected}

    baseline_count = len(expected)
    predicted_count = len(predicted)
    matched_baseline = {fp for fp in expected if fp in matched}

    coverage = len(matched_baseline) / baseline_count if baseline_count else 0.0
    precision = len(matched) / predicted_count if predicted_count else 0.0

    context_expected = {fp: issue for fp, issue in expected.items() if _context_flag(issue)}
    context_matched = {fp for fp in context_expected if fp in matched}
    context_coverage = len(context_matched) / len(context_expected) if context_expected else 0.0

    noise = 0
    for index, fp in enumerate(predicted):
        if fp not in expected or index >= inline_budget:
            noise += 1
    noise_rate = noise / predicted_count if predicted_count else 0.0

    return {
        "review_coverage": coverage,
        "review_precision": precision,
        "review_f1": _harmonic_f1(coverage, precision),
        "review_coverage_context_dependent": context_coverage,
        "review_noise_rate": noise_rate,
        "review_cost_per_task": float(cost_usd),
    }


def aggregate_review_metrics(task_metrics: list[dict[str, float]]) -> dict[str, float]:
    """Return mean review metrics across one or more Harbor tasks."""
    if not task_metrics:
        return {key: 0.0 for key in REVIEW_METRIC_KEYS}
    totals = {key: 0.0 for key in REVIEW_METRIC_KEYS}
    for row in task_metrics:
        for key in REVIEW_METRIC_KEYS:
            totals[key] += float(row.get(key, 0.0))
    count = float(len(task_metrics))
    return {key: totals[key] / count for key in REVIEW_METRIC_KEYS}


def load_review_baseline(bench_dir: Path | None = None) -> dict[str, float]:
    """Load committed review-track baseline metrics from ``bench/baselines/review-v1.json``."""
    from tripll.bench import bench_root

    root = bench_dir or bench_root()
    baseline_path = root / "baselines" / "review-v1.json"
    if not baseline_path.is_file():
        return {key: 0.0 for key in REVIEW_METRIC_KEYS}
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    metrics = data.get("metrics") or data
    return {key: float(metrics.get(key, 0.0)) for key in REVIEW_METRIC_KEYS}


def compute_review_deltas(
    metrics: dict[str, float],
    baseline: dict[str, float],
) -> dict[str, float]:
    """Return metric deltas vs a review baseline snapshot."""
    return {
        key: float(metrics.get(key, 0.0)) - float(baseline.get(key, 0.0))
        for key in REVIEW_METRIC_KEYS
    }


def load_predicted_findings(path: Path) -> list[dict[str, Any]]:
    """Load mergeCraft ``{"findings": [...]}`` JSON from *path*."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: expected object envelope"
        raise ValueError(msg)
    findings = data.get("findings")
    if not isinstance(findings, list):
        msg = f"{path}: findings must be an array"
        raise ValueError(msg)
    return [row for row in findings if isinstance(row, dict)]


def score_review_harbor_task(
    task_dir: Path,
    baseline_issues: list[dict[str, Any]],
    *,
    predicted_path: Path | None = None,
    cost_usd: float = 0.0,
    inline_budget: int = DEFAULT_INLINE_FINDINGS_BUDGET,
) -> dict[str, float]:
    """Score one emitted Harbor task directory against its baseline issues."""
    findings_path = predicted_path or (task_dir / "solution" / "golden_findings.json")
    predicted = load_predicted_findings(findings_path)
    return compute_review_task_metrics(
        baseline_issues,
        predicted,
        cost_usd=cost_usd,
        inline_budget=inline_budget,
    )


def score_review_track(
    bench_dir: Path | None = None,
    *,
    review_root: Path | None = None,
) -> ReviewBenchResult:
    """Aggregate review metrics across Harbor tasks under ``bench/review/``."""
    from tripll.bench import bench_root

    root = bench_dir or bench_root()
    review_dir = review_root or (root / "review")
    baseline_path = review_dir / "baseline.jsonl"
    baseline_rows = load_baseline_issues(baseline_path) if baseline_path.is_file() else []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in baseline_rows:
        repo = str(row.get("repo") or "")
        pr_raw = row.get("pr")
        if not repo or pr_raw is None:
            continue
        slug = f"{repo.rsplit('/', 1)[-1]}-pr{int(pr_raw)}"
        grouped.setdefault(slug, []).append(row)

    task_metrics: list[dict[str, float]] = []
    for slug, issues in sorted(grouped.items()):
        task_dir = review_dir / slug
        if not task_dir.is_dir():
            continue
        task_metrics.append(score_review_harbor_task(task_dir, issues))

    metrics = aggregate_review_metrics(task_metrics)
    baseline = load_review_baseline(root)
    deltas = compute_review_deltas(metrics, baseline)
    return ReviewBenchResult(
        task_count=len(task_metrics),
        metrics=metrics,
        baseline=baseline,
        deltas=deltas,
    )
