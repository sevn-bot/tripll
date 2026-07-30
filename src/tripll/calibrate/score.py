"""Score predicted first-pass probability against ledger attempts (CAL-03, W5.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

MIN_PRIOR_RUNS = 3
_EXTRACTOR = "tripll.calibrate.score"


@dataclass(frozen=True, slots=True)
class WaveCalibrationRow:
    """Predicted vs realised metrics for one wave."""

    node_id: str
    wave_id: str
    predicted: float | None
    first_attempt_pass: float
    attempts_to_green: int


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Run-level calibration summary."""

    run_id: str
    predictor_version: str
    rows: tuple[WaveCalibrationRow, ...]
    brier_score: float | None
    prior_runs: int
    uncalibrated: bool
    realized_written: int = 0


def brier_score(predictions: list[float], outcomes: list[int | float]) -> float:
    """Return mean squared error for probability forecasts.

    Args:
        predictions (list[float]): Forecast probabilities in ``[0, 1]``.
        outcomes (list[int | float]): Binary outcomes (0/1).

    Returns:
        float: Brier score — lower is better.

    Examples:
        >>> brier_score([0.9, 0.1], [1, 0])
        0.01
    """
    if not predictions or len(predictions) != len(outcomes):
        msg = "predictions and outcomes must be the same non-empty length"
        raise ValueError(msg)
    total = 0.0
    for pred, outcome in zip(predictions, outcomes, strict=True):
        total += (float(pred) - float(outcome)) ** 2
    return total / len(predictions)


def first_attempt_pass_rate(attempts: list[Any]) -> float:
    """Return ``1.0`` when the first attempt outcome is ``done``, else ``0.0``.

    Args:
        attempts (list[Any]): Attempt rows ordered by ``attempt_n``.

    Returns:
        float: First-attempt pass indicator.
    """
    if not attempts:
        return 0.0
    first = attempts[0]
    outcome = (
        getattr(first, "outcome", None) if not isinstance(first, dict) else first.get("outcome")
    )
    return 1.0 if str(outcome or "") == "done" else 0.0


def wave_attempts_to_green(attempts: list[Any]) -> int:
    """Count attempts until the first ``done`` outcome (CAL-03).

    Args:
        attempts (list[Any]): Attempt rows ordered by ``attempt_n``.

    Returns:
        int: Attempt count to first green, or total attempts when never green.
    """
    if not attempts:
        return 0
    for index, attempt in enumerate(attempts, start=1):
        outcome = (
            getattr(attempt, "outcome", None)
            if not isinstance(attempt, dict)
            else attempt.get("outcome")
        )
        if str(outcome or "") == "done":
            return index
    return len(attempts)


def _load_predicted_metrics(
    graph_db: Path,
    *,
    run_id: str,
    predictor_version: str,
) -> dict[str, float]:
    import sqlite3

    predicted: dict[str, float] = {}
    if not graph_db.is_file():
        return predicted
    conn = sqlite3.connect(str(graph_db))
    try:
        rows = conn.execute(
            """SELECT node_id, props FROM nodes
               WHERE layer = 'finding' AND kind = 'Metric'
                 AND node_id LIKE ?""",
            (f"finding:Metric:{run_id}#%#first_pass_probability#{predictor_version}",),
        ).fetchall()
    finally:
        conn.close()
    for node_id, props_raw in rows:
        props = json.loads(str(props_raw or "{}"))
        wave_id = str(props.get("wave_id") or "")
        if wave_id:
            predicted[wave_id] = float(props.get("value") or 0.0)
        else:
            # Fallback: parse wave id from node_id …{run_id}#{wave_id}#first_pass…
            marker = f"{run_id}#"
            if marker in str(node_id):
                fragment = str(node_id).split(marker, 1)[1]
                wave_id = fragment.split("#first_pass_probability#", 1)[0]
                if wave_id:
                    predicted[wave_id] = float(props.get("value") or 0.0)
    return predicted


def _count_prior_runs(runs_root: Path, *, exclude_run_id: str) -> int:
    count = 0
    for bucket in ("processed", "processing", "failed"):
        bucket_dir = runs_root / bucket
        if not bucket_dir.is_dir():
            continue
        for child in bucket_dir.iterdir():
            if not child.is_dir() or child.name == exclude_run_id:
                continue
            if (child / "ledger.db").is_file():
                count += 1
    return count


def calibrate_run(
    *,
    run_id: str,
    runs_root: Path,
    write_realized: bool = True,
) -> CalibrationReport:
    """Read ledger attempts, score predictions, optionally write REALIZED metrics.

    Args:
        run_id (str): Run identifier.
        runs_root (Path): Runs root containing *run_id*.
        write_realized (bool): When True, upsert REALIZED Metric nodes.

    Returns:
        CalibrationReport: Per-wave rows and optional Brier score.
    """
    from tripll.calibrate.predict import PREDICTOR_VERSION, build_wave_predictions
    from tripll.graphstore.task_sync import sync_calibration_experiment
    from tripll.ledger import list_attempts, list_waves, open_ledger
    from tripll.parse.plan_v3 import read_plan_file
    from tripll.plan.shape_checks import compile_plan

    run_dir = runs_root / "processing" / run_id
    for bucket in ("processing", "processed", "failed"):
        candidate = runs_root / bucket / run_id
        if candidate.is_dir():
            run_dir = candidate
            break
    if not run_dir.is_dir():
        msg = f"run directory not found for {run_id!r}"
        raise FileNotFoundError(msg)

    ledger_path = run_dir / "ledger.db"
    graph_db = run_dir / "graph.db"
    prior_runs = _count_prior_runs(runs_root, exclude_run_id=run_id)

    plan_path = _first_plan_path(run_dir / "input")
    plan: dict[str, Any] = {}
    if plan_path is not None:
        plan, _warnings = read_plan_file(plan_path)
        plan = compile_plan(
            plan,
            repo_root=runs_root.parent,
            graph_db=graph_db if graph_db.is_file() else None,
        )

    if plan and write_realized and graph_db.parent.exists():
        sync_calibration_experiment(
            store=str(graph_db),
            run_id=run_id,
            calibration=plan.get("_calibration")
            or build_wave_predictions(
                plan,
                repo_root=runs_root.parent,
                graph_db=graph_db if graph_db.is_file() else None,
            ),
        )

    predicted_by_wave: dict[str, float] = {}
    if graph_db.is_file():
        predicted_by_wave = _load_predicted_metrics(
            graph_db,
            run_id=run_id,
            predictor_version=PREDICTOR_VERSION,
        )

    rows: list[WaveCalibrationRow] = []
    predictions: list[float] = []
    outcomes: list[float] = []
    realized_written = 0

    with open_ledger(ledger_path) as lc:
        waves = list_waves(lc, run_id)
        for wave in waves:
            attempts = list_attempts(lc, run_id, wave.node_id)
            pass_rate = first_attempt_pass_rate(attempts)
            attempts_green = wave_attempts_to_green(attempts)
            predicted = predicted_by_wave.get(wave.wave_id)
            if predicted is None and plan:
                cal = (plan.get("_calibration") or {}).get("waves") or {}
                wave_cal = cal.get(wave.wave_id) or {}
                predicted = wave_cal.get("first_pass_probability")
            rows.append(
                WaveCalibrationRow(
                    node_id=wave.node_id,
                    wave_id=wave.wave_id,
                    predicted=float(predicted) if predicted is not None else None,
                    first_attempt_pass=pass_rate,
                    attempts_to_green=attempts_green,
                )
            )
            if predicted is not None:
                predictions.append(float(predicted))
                outcomes.append(pass_rate)

        if write_realized and graph_db.is_file():
            realized_written = _write_realized_metrics(
                graph_db=graph_db,
                run_id=run_id,
                rows=rows,
                predictor_version=PREDICTOR_VERSION,
            )

    uncalibrated = prior_runs < MIN_PRIOR_RUNS
    score: float | None = None
    if predictions and not uncalibrated:
        score = brier_score(predictions, outcomes)

    return CalibrationReport(
        run_id=run_id,
        predictor_version=PREDICTOR_VERSION,
        rows=tuple(rows),
        brier_score=score,
        prior_runs=prior_runs,
        uncalibrated=uncalibrated,
        realized_written=realized_written,
    )


def _first_plan_path(input_dir: Path) -> Path | None:
    if not input_dir.is_dir():
        return None
    v3 = sorted(input_dir.glob("*-wave-plan.md"))
    if v3:
        return v3[0]
    plain = sorted(input_dir.glob("*.md"))
    return plain[0] if plain else None


def _write_realized_metrics(
    *,
    graph_db: Path,
    run_id: str,
    rows: list[WaveCalibrationRow],
    predictor_version: str,
) -> int:
    from datetime import UTC, datetime

    from tripll.graphstore import EdgeInput, NodeInput, SqliteGraphStore

    store = SqliteGraphStore(str(graph_db))
    now = datetime.now(tz=UTC).isoformat()
    base = {
        "source": _EXTRACTOR,
        "evidence": f"run:{run_id}",
        "extractor": _EXTRACTOR,
        "extractor_version": "0.1.0",
        "confidence": 1.0,
        "extracted_at": now,
    }
    experiment_id = f"finding:Experiment:{run_id}#calibration"
    nodes: list[NodeInput] = []
    edges: list[EdgeInput] = []
    written = 0

    for row in rows:
        for metric_name, value in (
            ("first_attempt_pass_rate", row.first_attempt_pass),
            ("attempts_to_green", float(row.attempts_to_green)),
        ):
            natural_key = f"{run_id}#{row.wave_id}#{metric_name}#{predictor_version}"
            node_id = f"finding:Metric:{natural_key}"
            nodes.append(
                NodeInput(
                    node_id=node_id,
                    layer="finding",
                    kind="Metric",
                    natural_key=natural_key,
                    repo=None,
                    props=json.dumps(
                        {
                            "name": metric_name,
                            "version": predictor_version,
                            "value": value,
                            "wave_id": row.wave_id,
                            "node_id": row.node_id,
                            "run_id": run_id,
                        }
                    ),
                    **base,
                )
            )
            edges.append(
                EdgeInput(
                    edge_id=f"realized:{experiment_id}:{node_id}",
                    predicate="REALIZED",
                    src=experiment_id,
                    dst=node_id,
                    **base,
                )
            )
            written += 1

    if nodes:
        store.upsert_nodes(nodes)
        store.upsert_edges(edges)
    store.close()
    return written


def format_calibration_report(report: CalibrationReport) -> str:
    """Render a human-readable calibration summary."""
    lines = [
        f"Calibration — {report.run_id}",
        f"Predictor: {report.predictor_version}",
        "",
        "Wave                     Predicted  Actual (1st pass)  Attempts to green",
        "-----------------------  ---------  -----------------  -----------------",
    ]
    for row in report.rows:
        predicted = f"{row.predicted:.3f}" if row.predicted is not None else "—"
        lines.append(
            f"{row.wave_id:<23}  {predicted:>9}  {row.first_attempt_pass:>17.0f}  "
            f"{row.attempts_to_green:>17}"
        )
    lines.append("")
    if report.uncalibrated:
        lines.append(
            f"Brier score: uncalibrated (prior runs={report.prior_runs}, need {MIN_PRIOR_RUNS})"
        )
    elif report.brier_score is not None:
        lines.append(f"Brier score: {report.brier_score:.4f}")
    else:
        lines.append("Brier score: — (no predictions recorded)")
    return "\n".join(lines) + "\n"
