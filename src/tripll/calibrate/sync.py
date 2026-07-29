"""Run-start calibration metadata sync (W5.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def sync_run_calibration_metadata(
    *,
    run_id: str,
    run_dir: Path,
    graph_db_path: Path,
    repo_root: Path,
) -> None:
    """Compile plan predictions and write Experiment/Metric nodes for *run_id*.

    Args:
        run_id (str): Active run identifier.
        run_dir (Path): Run directory containing ``input/``.
        graph_db_path (Path): Per-run GraphStore SQLite path.
        repo_root (Path): Target repository root.
    """
    from tripll.parse.plan_v3 import read_plan_file
    from tripll.plan.shape_checks import compile_plan

    input_dir = run_dir / "input"
    if not input_dir.is_dir():
        return
    plans = sorted(input_dir.glob("*-wave-plan.md")) or sorted(input_dir.glob("*.md"))
    if not plans:
        return
    plan, _warnings = read_plan_file(plans[0])
    compile_plan(
        plan,
        repo_root=repo_root,
        graph_db=graph_db_path,
        repo=repo_root.name,
        run_id=run_id,
    )
