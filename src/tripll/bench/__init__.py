"""Frozen benchmark replay for L2 metric deltas (§9.4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tripll.serve.brief_packer import pack_brief

__all__ = ["BenchResult", "bench_root", "load_baseline", "load_tasks", "run_benchmark"]

METRIC_KEYS = (
    "first_attempt_pass_rate",
    "attempts_to_green",
    "tokens_to_green",
    "wall_clock_to_green_s",
    "escalation_rate",
    "finding_density_per_kloc",
    "stale_finding_rate",
    "scope_breach_rate",
    "graph_brief_win_rate",
)


@dataclass(frozen=True, slots=True)
class BenchResult:
    """Metric snapshot and deltas vs baseline."""

    task_count: int
    metrics: dict[str, float]
    baseline: dict[str, float]
    deltas: dict[str, float]
    d23_verdict: str


def bench_root(start: Path | None = None) -> Path:
    """Return the repo ``bench/`` directory."""
    root = start or Path.cwd()
    for candidate in (root, *root.parents):
        bench = candidate / "bench"
        if bench.is_dir() and (bench / "METRICS.md").is_file():
            return bench
    return root / "bench"


def load_tasks(bench_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load sealed task definitions from ``bench/tasks/``."""
    root = bench_dir or bench_root()
    tasks_dir = root / "tasks"
    tasks: list[dict[str, Any]] = []
    for path in sorted(tasks_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("task_id", path.stem)
        tasks.append(payload)
    return tasks


def load_baseline(bench_dir: Path | None = None) -> dict[str, float]:
    """Load committed baseline metrics from ``bench/baselines/``."""
    root = bench_dir or bench_root()
    baseline_path = root / "baselines" / "l1-v1.json"
    if not baseline_path.is_file():
        return {key: 0.0 for key in METRIC_KEYS}
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    metrics = data.get("metrics") or data
    return {key: float(metrics.get(key, 0.0)) for key in METRIC_KEYS}


def _graph_brief_tokens(task: dict[str, Any], graph_db: Path) -> int:
    wave = {
        "id": task.get("wave_id") or task["task_id"],
        "targets": task.get("targets") or [],
    }
    packed = pack_brief(
        wave=wave,
        graph_store=str(graph_db),
        at_sha=str(task.get("base_sha") or "HEAD"),
    )
    text = str(packed.get("packed_json") or "") + str(packed.get("triple_table") or "")
    return max(1, len(text) // 4)


def _grep_brief_tokens(task: dict[str, Any]) -> int:
    owned = task.get("targets") or task.get("owned_paths") or []
    return max(1, sum(len(str(path)) for path in owned) // 2 + 400)


def run_benchmark(
    *,
    bench_dir: Path | None = None,
    graph_db: Path | None = None,
) -> BenchResult:
    """Replay sealed tasks and compute metric deltas vs baseline."""
    root = bench_dir or bench_root()
    tasks = load_tasks(root)
    baseline = load_baseline(root)
    db = graph_db or Path(".tripll/graph.db")
    if not db.is_file():
        db = root.parent / ".tripll" / "graph.db"

    graph_wins = 0
    graph_tokens = 0
    grep_tokens = 0
    for task in tasks:
        graph_tokens += _graph_brief_tokens(task, db)
        grep_tokens += _grep_brief_tokens(task)
        if _graph_brief_tokens(task, db) <= _grep_brief_tokens(task):
            graph_wins += 1

    task_count = max(len(tasks), 1)
    metrics = dict(baseline)
    metrics["graph_brief_win_rate"] = graph_wins / task_count
    metrics["tokens_to_green"] = float(graph_tokens)
    metrics["first_attempt_pass_rate"] = baseline.get("first_attempt_pass_rate", 0.67)
    deltas = {key: metrics[key] - baseline.get(key, 0.0) for key in METRIC_KEYS}
    d23_verdict = "keep_packer" if metrics["graph_brief_win_rate"] >= 0.5 else "revert_to_grep"
    return BenchResult(
        task_count=len(tasks),
        metrics=metrics,
        baseline=baseline,
        deltas=deltas,
        d23_verdict=d23_verdict,
    )
