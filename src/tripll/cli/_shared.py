"""tripll.cli._shared — shared CLI helpers and option types (issue #16 seam).

Exports:
    RunsRootOpt — annotated ``--runs-root`` option type.
    _resolve_runs_root — resolve runs root from CLI option.
    _cost_budget_usd — read TRIPLL_COST_BUDGET_USD.
    _backend_options — resolve backend name and BackendOptions.
    _engine_for — construct Engine for dispatch/resume.
    _finalize_run_result — print run outcome and exit.
    _prepare_resume — ensure run is resumable.
    _refresh_report — rewrite report.md from ledger.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from loguru import logger

from tripll.pipeline import RunsRoot, resolve_runs_root
from tripll.repo_root import resolve_repo_root

if TYPE_CHECKING:
    from tripll.adapters.options import BackendOptions
    from tripll.engine import Engine, RunResult

RunsRootOpt = Annotated[
    Path | None,
    typer.Option(
        "--runs-root",
        "-r",
        envvar="TRIPLL_RUNS",
        help=(
            "Runs root directory (default: <repo>/.tripll/runs for target repos, "
            "<repo>/runs for tripll dev checkout, or $TRIPLL_RUNS)."
        ),
        show_default=True,
    ),
]


def _resolve_runs_root(runs_root: Path | None) -> RunsRoot:
    """Resolve and return a :class:`~tripll.pipeline.RunsRoot`.

    Delegates to :func:`~tripll.pipeline.resolve_runs_root`.

    Args:
        runs_root (Path | None): Explicit path from CLI, or ``None`` to use default.

    Returns:
        RunsRoot: Configured runs root instance.
    """
    return resolve_runs_root(runs_root)


def _cost_budget_usd() -> float:
    raw = os.environ.get("TRIPLL_COST_BUDGET_USD", "0").strip()
    try:
        return max(0.0, float(raw or 0))
    except ValueError:
        return 0.0


def _claude_verbose() -> bool:
    return os.environ.get("TRIPLL_CLAUDE_VERBOSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _backend_options(
    *,
    backend: str,
    model: str | None = None,
    agent: str | None = None,
) -> tuple[str, BackendOptions]:
    """Resolve backend name and options (``--provider`` alias → ``--backend``)."""
    from tripll.adapters import BackendOptions

    name = backend
    return name, BackendOptions(
        model=model or None,
        agent=agent or None,
        verbose=_claude_verbose(),
    )


def _engine_for(
    rr: RunsRoot,
    *,
    backend: str = "claude_code",
    model: str | None = None,
    agent: str | None = None,
    role_dispatch: bool | None = None,
    grep_brief: bool | None = None,
) -> Engine:
    """Build an :class:`~tripll.engine.Engine` with resolved repo root."""
    from tripll.adapters import get_adapter
    from tripll.engine import Engine as _Engine

    name, opts = _backend_options(backend=backend, model=model, agent=agent)
    repo_root = resolve_repo_root()
    logger.info("tripll: repo_root={}", repo_root)
    return _Engine(
        adapter=get_adapter(name, options=opts),
        runs_root=rr,
        repo_root=repo_root,
        cost_budget_usd=_cost_budget_usd(),
        role_dispatch=role_dispatch,
        grep_brief=grep_brief,
    )


def _hitl_poll_seconds() -> float:
    raw = os.environ.get("TRIPLL_HITL_POLL_S", "2").strip()
    try:
        return max(0.5, float(raw or 2))
    except ValueError:
        return 2.0


def _hitl_dashboard_url(run_id: str) -> str:
    host = os.environ.get("TRIPLL_SERVE_HOST", "localhost")
    port = os.environ.get("TRIPLL_SERVE_PORT", "8765")
    return f"http://{host}:{port}/runs/{run_id}"


def _emit_hitl_wait_banner(run_id: str, gate_kind: str | None) -> None:
    typer.echo("")
    typer.echo(f"PAUSED at HITL gate ({gate_kind or 'pre0'}) — waiting for operator input.")
    typer.echo(f"  Dashboard: {_hitl_dashboard_url(run_id)}")
    typer.echo(f"  Or: make pre0-interview RUN={run_id}  (terminal fallback)")
    typer.echo("  Complete hitl-responses.json + approve, or use dashboard Submit & approve.")


def _wait_for_hitl_loop(engine: Engine, run_id: str, result: RunResult) -> RunResult:
    """Poll until HITL responses are complete, then approve and resume repeatedly."""
    import asyncio
    import time

    from tripll import hitl

    run_dir = engine.runs_root.run_dir(run_id)
    poll_s = _hitl_poll_seconds()
    current = result

    while current.hitl_pending or (
        current.state == "paused" and hitl.detect_pending_gate(run_dir) is not None
    ):
        _emit_hitl_wait_banner(run_id, current.hitl_gate_kind)
        while hitl.detect_pending_gate(run_dir) is not None:
            if hitl.gate_poll_ready(run_dir):
                try:
                    engine.approve(run_id)
                    _refresh_report(engine.runs_root, run_id)
                    typer.echo("HITL responses complete — approved; resuming run…")
                    current = asyncio.run(engine.resume(run_id))
                    break
                except ValueError as exc:
                    typer.echo(f"Approve blocked: {exc}", err=True)
            time.sleep(poll_s)
        else:
            if not current.hitl_pending:
                break
            time.sleep(poll_s)
            continue
        if not current.hitl_pending and hitl.detect_pending_gate(run_dir) is None:
            break
    return current


def _finalize_run_result(
    rr: RunsRoot,
    result: RunResult,
    *,
    integrate: bool = False,
    deliver: bool = False,
    wait_for_hitl: bool = False,
    engine: Engine | None = None,
) -> None:
    """Print run outcome and exit with appropriate code."""
    typer.echo(f"Run: {result.run_id}")
    typer.echo(f"State: {result.state}")
    typer.echo(f"Logs: {rr.run_dir(result.run_id) / 'logs'}")

    if wait_for_hitl and engine is not None and (result.hitl_pending or result.pre0_pending):
        result = _wait_for_hitl_loop(engine, result.run_id, result)

    if result.pre0_pending and not wait_for_hitl:
        typer.echo("")
        typer.echo("STOPPED at Pre-0 human gate. Resolve the decisions sheet, then run:")
        typer.echo(f"  tripll approve {result.run_id}")
        typer.echo(f"  tripll resume {result.run_id}")
        raise typer.Exit(0)
    if result.hitl_pending and not wait_for_hitl:
        _emit_hitl_wait_banner(result.run_id, result.hitl_gate_kind)
        typer.echo(f"  tripll approve {result.run_id}")
        typer.echo(f"  tripll resume {result.run_id}")
        raise typer.Exit(0)
    if result.quota_pending:
        typer.echo("")
        typer.echo("PAUSED — provider quota/session limit. Switch provider/model and resume:")
        typer.echo(f"  make resume-run RUN={result.run_id} PROVIDER=cursor_local MODEL=auto")
        raise typer.Exit(0)
    if result.cost_pending:
        typer.echo("")
        typer.echo("PAUSED — cost budget reached. Raise TRIPLL_COST_BUDGET_USD and resume:")
        typer.echo(f"  TRIPLL_COST_BUDGET_USD=50 make resume-run RUN={result.run_id}")
        raise typer.Exit(0)
    if result.state == "parked":
        typer.echo("")
        typer.echo("PARKED — tier-4 canary red under auto_accept; resolve externally before retry.")
        raise typer.Exit(0)
    for node_id, nr in result.nodes.items():
        typer.echo(f"  {node_id:<40}  {nr.state:<8}  attempts={nr.attempts}")
    if result.state == "failed":
        raise typer.Exit(1)
    if integrate and result.state == "done":
        _run_integration(rr, result.run_id, deliver=deliver)


def _require_run_dir(rr: RunsRoot, run_id: str) -> Path:
    """Locate a run directory under processing, processed, or failed."""
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    return run_dir


def _run_integration(rr: RunsRoot, run_id: str, *, deliver: bool = False) -> None:
    """Execute autonomous per-batch integration for a completed run."""
    from tripll.integrate import GitMakeRunner, execute_integration, plan_integration
    from tripll.parse import build_graph_from_dir
    from tripll.worktrees import branch_name

    run_dir = _require_run_dir(rr, run_id)
    graph = build_graph_from_dir(run_dir, run_id=run_id)
    plan = plan_integration(graph, run_id=run_id)
    branch_for_lane = {
        lane_id: branch_name(run_id, lane.waves[0].plan_id, lane.waves[0].wave_id)
        for lane_id, lane in graph.lanes.items()
        if lane.waves
    }
    runner = GitMakeRunner(Path.cwd(), branch_for_lane=branch_for_lane)
    typer.echo("")
    typer.echo("[integrate] Running per-batch integration…")
    for line in execute_integration(plan, runner):
        typer.echo(f"  {line}")
    if deliver:
        _run_deliver(rr, run_id)


def _run_deliver(rr: RunsRoot, run_id: str) -> None:
    """Push integration branch and open PR after successful integrate (D15: no auto-merge)."""
    from tripll.loops.l1_pr import shepherd_run

    run_dir = _require_run_dir(rr, run_id)
    typer.echo("")
    typer.echo("[deliver] Pushing integration branch and opening PR…")
    result = shepherd_run(run_id=run_id, run_dir=run_dir, phase="deliver")
    if not isinstance(result, dict):
        typer.echo("[deliver] Unexpected shepherd result.", err=True)
        raise typer.Exit(1)
    for action in result.get("actions") or []:
        name = action.get("action", "?")
        replayed = action.get("replayed")
        dry = action.get("dry_run")
        suffix = ""
        if replayed:
            suffix = " (replayed — no side effect)"
        elif dry:
            suffix = " (dry-run — no side effect)"
        typer.echo(f"  {name}: ok{suffix}")
        payload = action.get("result") or {}
        if url := payload.get("url"):
            typer.echo(f"    PR: {url}")
    typer.echo("")
    typer.echo(
        "[deliver] Next: tripll findings sync, tripll pr shepherd --phase investigate_and_fix"
    )
    typer.echo("[deliver] Merge gate: tripll pr approve-merge (never auto-merge)")


def _refresh_report(rr: RunsRoot, run_id: str, *, current_node_id: str | None = None) -> None:
    """Rewrite ``report.md`` from the ledger (operator live view)."""
    from tripll.parse import build_graph_from_dir
    from tripll.report import sync_report

    run_dir = rr.run_dir(run_id)
    ledger_path = rr.ledger_path(run_id)
    if not ledger_path.is_file():
        return
    try:
        graph = build_graph_from_dir(run_dir, run_id=run_id)
    except FileNotFoundError:
        return
    sync_report(
        run_dir,
        graph,
        ledger_path,
        run_id=run_id,
        current_node_id=current_node_id,
        pre0_approved=(run_dir / "pre0-approved").exists(),
    )


def _prepare_resume(rr: RunsRoot, run_id: str) -> None:
    """Ensure *run_id* is resumable from processing/ (reactivate from failed/ if needed)."""
    from tripll.ledger import (
        list_waves,
        open_ledger,
        reset_wave_attempts,
        transition_run,
        transition_wave,
    )

    loc = rr.find_run_dir(run_id)
    if loc is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    if loc.parent == rr.processed_dir:
        typer.echo(f"Run already completed: {run_id}", err=True)
        raise typer.Exit(1)
    if loc.parent == rr.failed_dir:
        rr.reactivate_run(run_id)
        with open_ledger(rr.ledger_path(run_id)) as lc:
            transition_run(lc, run_id, "paused")
            for w in list_waves(lc, run_id):
                if w.state == "blocked":
                    transition_wave(lc, run_id, w.node_id, "queued")
                    reset_wave_attempts(lc, run_id, w.node_id)
        for name in ("escalation.md", "quota-paused.md", "cost-budget-paused.md"):
            path = rr.run_dir(run_id) / name
            if path.exists():
                path.unlink()
        typer.echo(f"Reactivated failed run → processing/{run_id}/")
    elif loc.parent == rr.processing_dir:
        with open_ledger(rr.ledger_path(run_id)) as lc:
            for w in list_waves(lc, run_id):
                if w.state in ("running", "dispatched", "verifying", "blocked"):
                    transition_wave(lc, run_id, w.node_id, "queued")
                    reset_wave_attempts(lc, run_id, w.node_id)
        typer.echo(f"Resuming run in processing/{run_id}/")
    _refresh_report(rr, run_id)
