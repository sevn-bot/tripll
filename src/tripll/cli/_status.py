"""tripll.cli._status — status and list-runs commands (issue #16 seam).

Exports:
    register_status_commands — attach status commands to the root Typer app.
    _orchestrator_watch_lines — orchestrator table for status --watch (W3).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _cost_budget_usd,
    _refresh_report,
    _resolve_runs_root,
)
from tripll.ledger import list_waves, open_ledger

if TYPE_CHECKING:
    from tripll.pipeline import RunsRoot


def status(
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run-id to inspect; omit to list all runs."),
    ] = None,
    runs_root: RunsRootOpt = None,
    watch: Annotated[
        bool,
        typer.Option("--watch", "-w", help="Live-tail per-agent status from the events table."),
    ] = False,
    interval: Annotated[
        float,
        typer.Option("--interval", help="Refresh interval (seconds) for --watch."),
    ] = 2.0,
) -> None:
    """Show status of a run (or list all runs).

    When a RUN_ID is supplied, prints each wave's state, attempt count, and node-id.
    When omitted, lists all processing/processed/failed runs by folder.
    With ``--watch`` and a RUN_ID, live-tails per-agent phase, current action,
    tokens, and cost from the ledger ``events`` table until interrupted (Ctrl-C).
    """
    rr = _resolve_runs_root(runs_root)

    if watch:
        if run_id is None:
            typer.echo("--watch requires a RUN_ID to follow.", err=True)
            raise typer.Exit(2)
        _status_watch(rr, run_id, interval)
        return

    if run_id is None:
        _status_all(rr)
        return

    _status_run(rr, run_id)


def _find_ledger_path(rr: RunsRoot, run_id: str) -> Path | None:
    """Return the ledger path for *run_id* across the run folders, or None.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier.

    Returns:
        Path | None: Path to ``ledger.db`` when found, else None.
    """
    for folder in (rr.processing_dir, rr.processed_dir, rr.failed_dir):
        ledger_path = folder / run_id / "ledger.db"
        if ledger_path.exists():
            return ledger_path
    return None


def _orchestrator_watch_lines(run_dir: Path | None) -> list[str]:
    """Format orchestrator status table + last 3 turns for ``status --watch`` (W3)."""
    if run_dir is None:
        return []
    from tripll.orchestrator_status import read_latest, render_status_table

    snap = read_latest(run_dir)
    if not snap.rows and not snap.turns:
        return []
    lines = ["── Orchestrator ──", ""]
    if snap.rows:
        lines.append(render_status_table(snap.rows[:5]))
        lines.append("")
    recent = snap.turns[-3:]
    if recent:
        lines.append("Recent turns:")
        for turn in recent:
            summary = " ".join((turn.summary or turn.turn_type).split())
            lines.append(f"  • [{turn.turn_type}] {summary[:72]}")
        lines.append("")
    return lines


def _status_watch(rr: RunsRoot, run_id: str, interval: float) -> None:
    """Live-tail per-agent status from the events table until interrupted.

    Collapses the append-only ``events`` table to one row per node (latest phase
    and action; cumulative tokens/cost), redrawing every *interval* seconds.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier to follow.
        interval (float): Refresh interval in seconds.
    """
    import time

    from tripll.ledger import list_events

    ledger_path = _find_ledger_path(rr, run_id)
    if ledger_path is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)

    try:
        while True:
            with open_ledger(ledger_path) as lc:
                events = list_events(lc, run_id)
            # Collapse to latest state per node; tokens/cost are cumulative so
            # carry forward the last non-None value. Skip orchestrator feed rows.
            latest: dict[str, dict[str, object]] = {}
            for e in events:
                if e.phase == "orchestrator":
                    continue
                cur = latest.setdefault(
                    e.node_id,
                    {"phase": "", "action": "", "in": None, "out": None, "cost": None},
                )
                cur["phase"] = e.phase
                if e.last_action:
                    cur["action"] = e.last_action.strip()
                if e.input_tokens is not None:
                    cur["in"] = e.input_tokens
                if e.output_tokens is not None:
                    cur["out"] = e.output_tokens
                if e.cost_usd is not None:
                    cur["cost"] = e.cost_usd

            run_dir = rr.find_run_dir(run_id)
            orch_lines = _orchestrator_watch_lines(run_dir)
            agent_events = [e for e in events if e.phase != "orchestrator"]

            lines = [
                f"watching {run_id}  ({len(latest)} agents, {len(agent_events)} events)  "
                "— Ctrl-C to exit",
                "",
            ]
            lines.extend(orch_lines)
            lines += [
                f"{'NODE-ID':<32}  {'PHASE':<11}  {'TOKENS':>13}  {'COST':>8}  ACTION",
                "-" * 100,
            ]
            for node_id, s in sorted(latest.items()):
                toks = (
                    f"{s['in'] or 0}->{s['out'] or 0}"
                    if (s["in"] is not None or s["out"] is not None)
                    else "-"
                )
                cost = f"${s['cost']:.4f}" if s["cost"] is not None else "-"
                action = str(s["action"])[:46]
                lines.append(f"{node_id:<32}  {s['phase']!s:<11}  {toks:>13}  {cost:>8}  {action}")
            if not latest:
                lines.append("(no events yet)")
            # Clear screen + home, then draw the frame.
            sys.stdout.write("\033[2J\033[H" + "\n".join(lines) + "\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("")  # leave the cursor on a fresh line


def _status_all(rr: RunsRoot) -> None:
    """Print a summary of all runs across the three terminal folders.

    Args:
        rr (RunsRoot): Configured runs root.
    """
    processing = rr.list_processing()
    processed = rr.list_processed()
    failed = rr.list_failed()
    pending = rr.list_input()

    typer.echo(f"Runs root: {rr.root}\n")

    typer.echo(f"Pending input sets — input/ ({len(pending)})")
    if pending:
        for p in pending:
            typer.echo(f"  {p.name}")
    else:
        typer.echo("  (empty)")

    typer.echo(f"\nActive runs — processing/ ({len(processing)})")
    if processing:
        for rid in processing:
            typer.echo(f"  {rid}")
    else:
        typer.echo("  (empty)")

    typer.echo(f"\nCompleted runs — processed/ ({len(processed)})")
    if processed:
        for rid in processed:
            typer.echo(f"  {rid}")
    else:
        typer.echo("  (empty)")

    typer.echo(f"\nFailed runs — failed/ ({len(failed)})")
    if failed:
        for rid in failed:
            typer.echo(f"  {rid}")
    else:
        typer.echo("  (empty)")


def list_runs_cmd(runs_root: RunsRootOpt = None) -> None:
    """List pending input sets and all runs (processing, processed, failed)."""
    rr = _resolve_runs_root(runs_root)
    _status_all(rr)


def _attempt_dispatch_labels(attempts: list[Any]) -> tuple[str, str, str]:
    """Return ``(backend, model, reasoning_effort)`` from the latest attempt brief."""
    backend = "—"
    model = "—"
    effort = "—"
    for attempt in reversed(attempts):
        if backend == "—":
            b = str(getattr(attempt, "backend", "") or "").strip()
            if b:
                backend = b
        brief_path = getattr(attempt, "brief_path", None)
        if brief_path and (model == "—" or effort == "—"):
            try:
                data = json.loads(Path(str(brief_path)).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                data = None
            if isinstance(data, dict):
                if model == "—":
                    m = str(data.get("model") or "").strip()
                    if m:
                        model = m
                if effort == "—":
                    e = str(data.get("reasoning_effort") or "").strip()
                    if e:
                        effort = e
        if backend != "—" and model != "—" and effort != "—":
            break
    return backend, model, effort


def _status_run(rr: RunsRoot, run_id: str) -> None:
    """Print detailed wave status for a single run.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier.
    """
    # Find the ledger — check processing/, then processed/, then failed/
    for folder in (rr.processing_dir, rr.processed_dir, rr.failed_dir):
        ledger_path = folder / run_id / "ledger.db"
        if ledger_path.exists():
            break
    else:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)

    from tripll.ledger import (
        get_run_cost,
        get_run_cost_by_provider,
        list_attempts,
        list_fired_exit_ids,
    )

    with open_ledger(ledger_path) as lc:
        waves = list_waves(lc, run_id)
        run_cost = get_run_cost(lc, run_id)
        cost_by_provider = get_run_cost_by_provider(lc, run_id)
        fired_exits = list_fired_exit_ids(lc, run_id)
        wave_dispatch: list[tuple[str, str, str, str]] = []
        for w in waves:
            backend, model, effort = _attempt_dispatch_labels(list_attempts(lc, run_id, w.node_id))
            wave_dispatch.append((w.node_id, backend, model, effort))
        evidence = {
            w.node_id: next(
                (a.evidence for a in reversed(list_attempts(lc, run_id, w.node_id)) if a.evidence),
                None,
            )
            for w in waves
            if w.state == "blocked"
        }

    if not waves:
        typer.echo(f"Run {run_id}: no waves registered yet.")
        return

    typer.echo(f"Run: {run_id}")
    typer.echo(f"{'NODE-ID':<40}  {'STATE':<14}  {'ATTEMPTS'}")
    typer.echo("-" * 65)
    for w in waves:
        typer.echo(f"{w.node_id:<40}  {w.state:<14}  {w.attempt_count}")

    typer.echo(f"\n{'NODE-ID':<40}  {'PROVIDER':<14}  {'MODEL':<22}  {'EFFORT'}")
    typer.echo("-" * 90)
    for node_id, backend, model, effort in wave_dispatch:
        typer.echo(f"{node_id:<40}  {backend:<14}  {model:<22}  {effort}")

    budget = _cost_budget_usd()
    typer.echo(f"\nCost: ${run_cost:.4f}")
    if cost_by_provider:
        typer.echo("  by provider:")
        for backend, amount in sorted(cost_by_provider.items()):
            typer.echo(f"    {backend}: ${amount:.4f}")
    if budget > 0:
        typer.echo(f"  budget: ${budget:.2f} (${run_cost:.4f} spent)")

    if fired_exits:
        typer.echo(f"\nExits fired: {', '.join(str(exit_id) for exit_id in fired_exits)}")

    run_dir = rr.find_run_dir(run_id)
    wt_root = (run_dir / "worktrees") if run_dir else None
    if wt_root and wt_root.is_dir():
        active = [p for p in wt_root.iterdir() if p.is_dir()]
        if active:
            typer.echo("\nWorktrees (agent code lives here until merged):")
            from tripll.worktrees import branch_name

            for wt in sorted(active):
                lane = wt.name.rsplit("-", 1)[0] if "-" in wt.name else wt.name
                wave = wt.name.rsplit("-", 1)[-1] if "-" in wt.name else "w0"
                branch = branch_name(run_id, lane, wave)
                typer.echo(f"  {wt}")
                typer.echo(f"    branch: {branch}")

    blocked = [w for w in waves if w.state == "blocked"]
    if blocked:
        typer.echo("\nEscalated (blocked) waves:")
        for w in blocked:
            typer.echo(f"  {w.node_id}: {evidence.get(w.node_id) or '(no evidence)'}")

    in_flight = [w for w in waves if w.state in ("running", "dispatched", "verifying")]
    current = in_flight[0].node_id if in_flight else None
    _refresh_report(rr, run_id, current_node_id=current)
    if run_dir:
        typer.echo(f"\nReport refreshed: {run_dir / 'report.md'}")


def register_status_commands(app: typer.Typer) -> None:
    """Register status and list-runs on *app*."""

    app.command()(status)
    app.command("list-runs")(list_runs_cmd)
