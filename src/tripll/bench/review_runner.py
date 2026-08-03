"""Review-track benchmark runner with regression signal (#64 W5).

Exports:
    DEFAULT_REVIEW_ATTEMPTS — default ``-k`` attempts per Harbor task.
    DEFAULT_REVIEW_REGRESSION_THRESHOLD — max allowed ``review_f1`` drop vs baseline.
    ReviewBenchRunResult — scored review track plus mergeCraft ref and regression verdict.
    resolve_review_regression_threshold — env/config threshold for nightly failure.
    run_review_benchmark — score Harbor tasks with best-of-k attempts and delta check.
    review_bench_dashboard_payload — JSON-serializable snapshot for dashboard panels.
    write_review_bench_dashboard — persist dashboard payload to disk.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tripll.bench.review_metrics import (
    REVIEW_METRIC_KEYS,
    ReviewBenchResult,
    aggregate_review_metrics,
    compute_review_deltas,
    load_review_baseline,
    score_review_harbor_task,
)
from tripll.github.findings import load_baseline_issues
from tripll.review import resolve_mergecraft_ref

DEFAULT_REVIEW_ATTEMPTS = 3
DEFAULT_REVIEW_REGRESSION_THRESHOLD = 0.05
DEFAULT_DASHBOARD_PATH = Path(".tripll/bench-review-latest.json")

__all__ = [
    "DEFAULT_DASHBOARD_PATH",
    "DEFAULT_REVIEW_ATTEMPTS",
    "DEFAULT_REVIEW_REGRESSION_THRESHOLD",
    "ReviewBenchRunResult",
    "resolve_review_regression_threshold",
    "review_bench_dashboard_payload",
    "run_review_benchmark",
    "write_review_bench_dashboard",
]


@dataclass(frozen=True, slots=True)
class ReviewBenchRunResult:
    """Review-track run with mergeCraft attribution and regression verdict."""

    task_count: int
    attempts_per_task: int
    mergecraft_ref: str
    metrics: dict[str, float]
    baseline: dict[str, float]
    deltas: dict[str, float]
    regression_threshold: float
    regression_failed: bool
    review_f1_delta: float

    @property
    def bench_result(self) -> ReviewBenchResult:
        """Return the underlying metric snapshot (W4 compat)."""
        return ReviewBenchResult(
            task_count=self.task_count,
            metrics=self.metrics,
            baseline=self.baseline,
            deltas=self.deltas,
        )


def resolve_review_regression_threshold(
    explicit: float | None = None,
) -> float:
    """Return configured ``review_f1`` regression threshold (fraction of F1 drop).

    Precedence: explicit CLI flag → ``TRIPLL_REVIEW_BENCH_REGRESSION_THRESHOLD`` env → default.

    Args:
        explicit (float | None): Optional override from ``--regression-threshold``.

    Returns:
        float: Maximum allowed drop in ``review_f1`` vs baseline before failure.
    """
    if explicit is not None:
        return max(0.0, float(explicit))
    raw = os.environ.get("TRIPLL_REVIEW_BENCH_REGRESSION_THRESHOLD", "").strip()
    if raw:
        return max(0.0, float(raw))
    return DEFAULT_REVIEW_REGRESSION_THRESHOLD


def _review_task_groups(review_dir: Path) -> dict[str, list[dict[str, Any]]]:
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
    return grouped


def _best_of_k_task_metrics(
    task_dir: Path,
    issues: list[dict[str, Any]],
    *,
    attempts: int,
) -> dict[str, float]:
    """Score one task up to *attempts* times; keep the attempt with highest ``review_f1``."""
    attempt_count = max(1, int(attempts))
    best: dict[str, float] | None = None
    for _ in range(attempt_count):
        metrics = score_review_harbor_task(task_dir, issues)
        if best is None or metrics["review_f1"] > best["review_f1"]:
            best = metrics
    assert best is not None
    return best


def run_review_benchmark(
    *,
    bench_dir: Path | None = None,
    review_root: Path | None = None,
    attempts: int = DEFAULT_REVIEW_ATTEMPTS,
    regression_threshold: float | None = None,
    mergecraft_ref: str | None = None,
) -> ReviewBenchRunResult:
    """Run the frozen review track and compare ``review_f1`` against baseline.

    Each Harbor task is scored up to *attempts* times; the best ``review_f1`` per task
    is kept (review is high-variance). Oracle tasks score identically each attempt until
    live agent dispatch is wired.

    Args:
        bench_dir (Path | None): ``bench/`` root (auto-detect when omitted).
        review_root (Path | None): Harbor tasks root (default ``bench/review/``).
        attempts (int): Maximum attempts per task (``-k`` / ``--attempts``).
        regression_threshold (float | None): Max allowed F1 drop; env default when omitted.
        mergecraft_ref (str | None): mergeCraft SHA under test; resolved when omitted.

    Returns:
        ReviewBenchRunResult: Aggregated metrics, deltas, and regression verdict.
    """
    from tripll.bench import bench_root

    root = bench_dir or bench_root()
    review_dir = review_root or (root / "review")
    threshold = resolve_review_regression_threshold(regression_threshold)
    ref = mergecraft_ref or resolve_mergecraft_ref()

    task_metrics: list[dict[str, float]] = []
    for slug, issues in sorted(_review_task_groups(review_dir).items()):
        task_dir = review_dir / slug
        if not task_dir.is_dir():
            continue
        task_metrics.append(
            _best_of_k_task_metrics(task_dir, issues, attempts=attempts),
        )

    metrics = aggregate_review_metrics(task_metrics)
    baseline = load_review_baseline(root)
    deltas = compute_review_deltas(metrics, baseline)
    f1_delta = float(deltas.get("review_f1", 0.0))
    regression_failed = f1_delta < -threshold

    return ReviewBenchRunResult(
        task_count=len(task_metrics),
        attempts_per_task=max(1, int(attempts)),
        mergecraft_ref=ref,
        metrics=metrics,
        baseline=baseline,
        deltas=deltas,
        regression_threshold=threshold,
        regression_failed=regression_failed,
        review_f1_delta=f1_delta,
    )


def review_bench_dashboard_payload(result: ReviewBenchRunResult) -> dict[str, Any]:
    """Return a JSON-serializable snapshot for dashboard / nightly artifacts."""
    return {
        "track": "review",
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "mergecraft_ref": result.mergecraft_ref,
        "attempts_per_task": result.attempts_per_task,
        "task_count": result.task_count,
        "review_f1": result.metrics.get("review_f1", 0.0),
        "review_f1_delta": result.review_f1_delta,
        "regression_threshold": result.regression_threshold,
        "regression_failed": result.regression_failed,
        "metrics": {key: result.metrics[key] for key in REVIEW_METRIC_KEYS},
        "baseline": {key: result.baseline[key] for key in REVIEW_METRIC_KEYS},
        "deltas": {key: result.deltas[key] for key in REVIEW_METRIC_KEYS},
    }


def write_review_bench_dashboard(
    result: ReviewBenchRunResult,
    path: Path | None = None,
) -> Path:
    """Write dashboard JSON for control-plane panels (#64 W5).

    Args:
        result (ReviewBenchRunResult): Completed review bench run.
        path (Path | None): Output path (default ``.tripll/bench-review-latest.json``).

    Returns:
        Path: Written file path.
    """
    out = path or DEFAULT_DASHBOARD_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(review_bench_dashboard_payload(result), indent=2) + "\n",
        encoding="utf-8",
    )
    return out
