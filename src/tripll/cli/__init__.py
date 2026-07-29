"""tripll — CLI entrypoint for the wave-orchestrator pipeline.

Subcommands: init, run, status, resume, approve, plan, validate-plan.

All subcommands share a ``--runs-root`` option (default: ``.tripll/runs/`` for
target repos, ``runs/`` for the tripll dev checkout, or ``$TRIPLL_RUNS``).

Exit codes:
    0  success
    1  general error (printed to stderr)
    2  usage / bad arguments

Exports:
    main — console script entrypoint (``tripll = "tripll.cli:main"``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import typer
from loguru import logger

from tripll import __version__
from tripll.cli._run import register_run_commands, rewrite_run_inject_argv
from tripll.cli._shared import (
    RunsRootOpt,
    _backend_options,
    _cost_budget_usd,
    _engine_for,
    _finalize_run_result,
    _prepare_resume,
    _refresh_report,
    _resolve_runs_root,
)
from tripll.cli._shared import (
    _require_run_dir as _require_run_dir,
)
from tripll.cli._shared import (
    _run_deliver as _run_deliver,
)
from tripll.cli._shared import (
    _run_integration as _run_integration,
)
from tripll.ledger import list_waves, open_ledger
from tripll.obs import configure_observability
from tripll.pipeline import make_run_id
from tripll.repo_root import resolve_repo_root
from tripll.skw.cli import app as skw_legacy_app

if TYPE_CHECKING:
    from tripll.pipeline import RunsRoot

_rewrite_run_inject_argv = rewrite_run_inject_argv

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="tripll",
    help=(
        "tripll — headless parallel wave-plan execution pipeline.\n\n"
        "Drop a parallel-wave set (or a folder of plain wave files) into the input/ "
        "directory, then run `tripll run` to start the pipeline.\n\n"
        "Exit codes: 0 success; 1 error; 2 usage."
    ),
    no_args_is_help=True,
    add_completion=False,
)

register_run_commands(app)


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Print version and exit.", is_eager=True),
    ] = False,
) -> None:
    """wave-orchestrator root callback — prints version or delegates to subcommand."""
    if version:
        typer.echo(f"tripll {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


# ---------------------------------------------------------------------------
# setup / doctor (W13)
# ---------------------------------------------------------------------------


@app.command()
def setup(
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Write config without prompts (CI / automation).",
        ),
    ] = False,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Default provider for --non-interactive (e.g. cursor_local).",
        ),
    ] = None,
) -> None:
    """One-time machine setup — providers, models, tracing (writes user config)."""
    from tripll.onboard.setup import run_setup

    run_setup(non_interactive=non_interactive, provider=provider)


@app.command()
def doctor(
    next_plan: Annotated[
        Path | None,
        typer.Option(
            "--next",
            help="Plan file path — include next-command hint from checkbox state.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
) -> None:
    """Preflight: Python, extras, providers, config layers, v3 template."""
    from tripll.onboard.doctor import run_doctor

    raise typer.Exit(run_doctor(plan_path=next_plan))


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    runs_root: RunsRootOpt = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing onboarding artefacts."),
    ] = False,
) -> None:
    """Initialise a repository for tripll (brownfield onboarding + runs layout).

    Creates ``tripll.toml``, starter specs/PRDs/plans, a repo evaluation, the
    code graph under ``.tripll/``, and the runs root (``input/``, ``processing/``,
    ``processed/``, ``failed/``). Safe to re-run: existing operator-edited files
    are preserved unless ``--force`` is set.
    """
    from tripll.onboard.brownfield import run_brownfield_init

    rr = _resolve_runs_root(runs_root)
    result = run_brownfield_init(runs_root=rr.root, force=force)
    typer.echo("Brownfield init complete.")
    for line in result.messages:
        typer.echo(f"  {line}")
    typer.echo(f"  input/      → {result.runs_root / 'input'}")
    typer.echo(f"  processing/ → {result.runs_root / 'processing'}")
    typer.echo(f"  processed/  → {result.runs_root / 'processed'}")
    typer.echo(f"  failed/     → {result.runs_root / 'failed'}")
    typer.echo("Next: tripll setup (once per machine), then tripll doctor")


@app.command()
def new(
    name: Annotated[str, typer.Argument(help="New project directory name.")],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Parent directory for the project (default: current directory).",
            file_okay=False,
            dir_okay=True,
            writable=True,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing onboarding artefacts."),
    ] = False,
    cookiecutter: Annotated[
        bool,
        typer.Option(
            "--cookiecutter",
            help="Use cookiecutter-pypackage (requires tripll scaffold extra).",
        ),
    ] = False,
) -> None:
    """Scaffold a new tripll-ready project (greenfield onboarding).

    Writes a Python project skeleton from packaged templates (offline, no network),
    then emits ``tripll.toml``, starter specs/PRDs/plans, evaluation, and ``runs/``.
    Re-running reconciles gaps without clobbering operator edits unless ``--force``.
    """
    from tripll.onboard.greenfield import GreenfieldError, new_project

    try:
        result = new_project(
            name,
            output_dir=output_dir,
            force=force,
            cookiecutter=cookiecutter,
        )
    except GreenfieldError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    typer.echo("Greenfield scaffold complete.")
    for line in result.messages:
        typer.echo(f"  {line}")
    typer.echo(f"  cd {result.project_dir.name}")
    typer.echo("Next: tripll setup (once per machine), tripll doctor, then make check")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
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


@app.command("list-runs")
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


wave_app = typer.Typer(
    name="wave",
    help="Mid-run wave graph operations (parallel lane inject).",
    no_args_is_help=True,
)
app.add_typer(wave_app, name="wave")


@wave_app.command("add")
def wave_add(
    run_id: Annotated[str, typer.Argument(help="Run-id in processing/ (must be paused).")],
    lane: Annotated[str, typer.Option("--lane", help="Lane id or display name for the new wave.")],
    wave_id: Annotated[
        str,
        typer.Option("--wave-id", help="Wave label (e.g. W7, DOCS-1)."),
    ],
    brief: Annotated[
        str,
        typer.Option("--brief", help="Operator brief describing the wave work."),
    ] = "",
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from-file",
            help="Read brief markdown from this path instead of --brief.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    paths: Annotated[
        list[str] | None,
        typer.Option("--paths", help="Owned paths the wave may edit (repeatable)."),
    ] = None,
    depends_on: Annotated[
        list[str] | None,
        typer.Option(
            "--depends-on",
            help="Node ids or wave labels this wave depends on (repeatable).",
        ),
    ] = None,
    after: Annotated[
        str | None,
        typer.Option(
            "--after",
            help="Batch anchor wave (node id or label); must be done when set.",
        ),
    ] = None,
    batch: Annotated[
        str,
        typer.Option(
            "--batch",
            help="Batch placement: current (anchor batch) or next (following batch).",
        ),
    ] = "current",
    plan_id: Annotated[
        str | None,
        typer.Option("--plan-id", help="Plan slug for node_id (default: slug of --lane)."),
    ] = None,
    verify_target: Annotated[
        str | None,
        typer.Option(
            "--verify-target",
            help="Override post-dispatch verify make target (default: make ci-affected).",
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="Provider override for wave dispatch."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override for wave dispatch."),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option("--agent", "-a", help="Agent slug override for wave dispatch."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate and write wave-add plan only; no ledger write."),
    ] = False,
    runs_root: RunsRootOpt = None,
) -> None:
    """Add a structured parallel-lane wave to a paused run (L2-W5c).

    Unlike ``tripll run inject`` (one-shot hotfix), ``wave add`` creates a full
    lane-level wave with batch placement. Requires ``pause-requested.md`` and at
    least one of ``--after`` or ``--depends-on`` for dependency/batch anchoring.
    """
    from tripll.inject import InjectError, apply_wave_add

    if batch not in ("current", "next"):
        typer.echo("--batch must be 'current' or 'next'", err=True)
        raise typer.Exit(2)
    if not lane.strip():
        typer.echo("--lane is required", err=True)
        raise typer.Exit(2)
    if not wave_id.strip():
        typer.echo("--wave-id is required", err=True)
        raise typer.Exit(2)
    if not paths:
        typer.echo("--paths must declare at least one owned path", err=True)
        raise typer.Exit(2)
    if not after and not depends_on:
        typer.echo("at least one of --after or --depends-on is required", err=True)
        raise typer.Exit(2)

    brief_text = brief.strip()
    if from_file is not None:
        brief_text = from_file.read_text(encoding="utf-8").strip()
    if not brief_text:
        typer.echo("--brief or --from-file is required", err=True)
        raise typer.Exit(2)

    rr = _resolve_runs_root(runs_root)
    if rr.find_run_dir(run_id) is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    loc = rr.find_run_dir(run_id)
    if loc is not None and loc.parent == rr.processed_dir:
        typer.echo(f"Run already completed (processed/): {run_id}", err=True)
        raise typer.Exit(1)

    verify_targets = [verify_target or "make ci-affected"]
    batch_placement: Literal["current", "next"] = "next" if batch == "next" else "current"
    try:
        task = apply_wave_add(
            rr,
            run_id,
            lane=lane,
            wave_id=wave_id,
            brief=brief_text,
            owned_paths=list(paths),
            depends_on=list(depends_on or []),
            after=after,
            batch_placement=batch_placement,
            plan_id=plan_id,
            verify_targets=verify_targets,
            provider=provider,
            model=model,
            agent=agent,
            cost_budget_usd=_cost_budget_usd(),
            dry_run=dry_run,
        )
    except InjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.exit_code) from exc

    if dry_run:
        typer.echo(f"[dry-run] Wave-add plan valid — node {task.node_id} batch {task.batch_id}")
        typer.echo(
            f"[dry-run] Plan artefact: {rr.injects_dir(run_id) / (task.task_id + '.plan.json')}"
        )
        return

    typer.echo(
        f"Wave add applied: {task.node_id} lane {task.lane_id} batch {task.batch_id} "
        f"(task {task.task_id})"
    )
    typer.echo(f"Audit: {rr.injects_dir(run_id) / (task.task_id + '.json')}")
    typer.echo(f"Resume with: tripll resume {run_id}")


@app.command()
def pause(
    run_id: Annotated[str, typer.Argument(help="Run-id to pause (processing/).")],
    runs_root: RunsRootOpt = None,
) -> None:
    """Request a pause for an active run (writes ``pause-requested.md``)."""
    rr = _resolve_runs_root(runs_root)
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    marker = run_dir / "pause-requested.md"
    marker.write_text(
        "# Pause requested\n\nWritten by `tripll pause`. "
        "The engine stops dispatching new waves at the next safe checkpoint.\n",
        encoding="utf-8",
    )
    typer.echo(f"Pause requested for {run_id} → {marker}")


# ---------------------------------------------------------------------------
# resume  — resume a paused or interrupted run
# ---------------------------------------------------------------------------


@app.command()
def resume(
    run_id: Annotated[str, typer.Argument(help="Run-id to resume.")],
    backend: Annotated[
        str | None,
        typer.Option(
            "--backend",
            "-b",
            help="Agent backend (default: dispatch-config.json from run start, else claude_code).",
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="Alias for --backend."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Provider model id (e.g. auto)."),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option("--agent", "-a", help="Claude Code sub-agent slug."),
    ] = None,
    wait_for_hitl: Annotated[
        bool,
        typer.Option(
            "--wait-for-hitl",
            help="Block until HITL gate responses are submitted and approved, then auto-resume.",
        ),
    ] = False,
    role_dispatch: Annotated[
        bool | None,
        typer.Option(
            "--role-dispatch/--no-role-dispatch",
            help="Enable per-role agent dispatch (test-author→test-creator, impl→wave-runner).",
        ),
    ] = None,
    grep_brief: Annotated[
        bool | None,
        typer.Option(
            "--grep-brief/--graph-brief",
            help="Force legacy grep brief (default: graph-packed when kg extra installed).",
        ),
    ] = None,
    runs_root: RunsRootOpt = None,
) -> None:
    """Resume a paused or in-progress run from its on-disk state.

    Rebuilds the run graph from the run directory and drives it to completion.
    Stops again at the Pre-0 gate if it has not been approved.
    Reactivates runs from ``failed/`` when resuming after quota escalation.
    """
    import asyncio

    from tripll.adapters import get_adapter

    rr = _resolve_runs_root(runs_root)
    from tripll.run_dispatch import resolve_dispatch

    loc = rr.find_run_dir(run_id)
    if loc is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    dispatch = resolve_dispatch(
        loc,
        backend=backend,
        provider=provider,
        model=model,
        agent=agent,
    )
    backend = dispatch.backend
    model = dispatch.model
    agent = dispatch.agent
    if role_dispatch is None:
        role_dispatch = dispatch.role_dispatch
    _prepare_resume(rr, run_id)

    name, opts = _backend_options(backend=backend, model=model, agent=agent)
    adapter = get_adapter(name, options=opts)
    caps = adapter.capabilities()
    if not caps.available:
        typer.echo(f"Backend unavailable: {caps.detail}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Repo: {resolve_repo_root()}")
    typer.echo(f"Backend: {name} ({caps.detail})")
    if model:
        typer.echo(f"Model: {model}")
    if agent:
        typer.echo(f"Agent: {agent}")
    typer.echo(f"Logs: {rr.run_dir(run_id) / 'logs'}")
    engine = _engine_for(
        rr,
        backend=backend,
        model=model,
        agent=agent,
        role_dispatch=role_dispatch,
        grep_brief=grep_brief,
    )
    result = asyncio.run(engine.resume(run_id))
    _finalize_run_result(
        rr,
        result,
        wait_for_hitl=wait_for_hitl,
        engine=engine,
    )


# ---------------------------------------------------------------------------
# approve  — unblock the Pre-0 human gate
# ---------------------------------------------------------------------------


@app.command()
def approve(
    run_id: Annotated[str, typer.Argument(help="Run-id to approve (unblock Pre-0 gate).")],
    node_id: Annotated[
        str | None,
        typer.Option("--node", "-n", help="Specific node-id to unblock; omit for Pre-0."),
    ] = None,
    runs_root: RunsRootOpt = None,
) -> None:
    """Approve a Pre-0 gate, unblocking the run so `tripll resume` can proceed.

    Writes the Pre-0 approval marker for the run. Use `tripll resume <run-id>`
    afterwards to continue dispatch.
    """
    from tripll.adapters import get_adapter
    from tripll.engine import Engine

    rr = _resolve_runs_root(runs_root)
    if not rr.run_dir(run_id).exists():
        typer.echo(f"Run not found in processing/: {run_id}", err=True)
        raise typer.Exit(1)
    engine = Engine(
        adapter=get_adapter("claude_code"),
        runs_root=rr,
        repo_root=resolve_repo_root(),
    )
    engine.approve(run_id)
    _refresh_report(rr, run_id)
    target = node_id or "Pre-0 gate"
    typer.echo(f"Approved {target} for run {run_id}.")
    typer.echo(f"Run `tripll resume {run_id}` to continue.")


@app.command("delete-run")
def delete_run_cmd(
    run_id: Annotated[str, typer.Argument(help="Run-id to delete.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
    runs_root: RunsRootOpt = None,
) -> None:
    """Delete a run directory from processing, processed, or failed."""
    rr = _resolve_runs_root(runs_root)
    path = rr.find_run_dir(run_id)
    if path is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    bucket = path.parent.name
    if not yes:
        typer.confirm(f"Delete {bucket}/{run_id}?", abort=True)
    deleted = rr.delete_run(run_id)
    typer.echo(f"Deleted: {deleted}")


@app.command("reset-run")
def reset_run_cmd(
    run_id: Annotated[
        str, typer.Argument(help="Run-id to reset (restore input set + delete run).")
    ],
    input_name: Annotated[
        str | None,
        typer.Option("--input-name", help="Input folder name (default: run slug from ledger)."),
    ] = None,
    runs_root: RunsRootOpt = None,
) -> None:
    """Restore plan files to input/ and delete the run directory."""
    rr = _resolve_runs_root(runs_root)
    try:
        dest = rr.reset_run(run_id, input_name=input_name)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except OSError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Restored input set: {dest}")
    typer.echo(f"Removed run: {run_id}")
    typer.echo(f"Next: make run-set SET={dest.name}")


@app.command("pre0-interview")
def pre0_interview_cmd(
    run_id: Annotated[str, typer.Argument(help="Run-id paused at Pre-0 (processing/).")],
    runs_root: RunsRootOpt = None,
) -> None:
    """Interactive Pre-0 decisions — multiple choice + notes, updates pre0-decisions.md."""
    from tripll.pre0_interview import interview_run

    rr = _resolve_runs_root(runs_root)
    path = interview_run(run_id, runs_root=rr.root)
    typer.echo(f"\nUpdated: {path}")
    typer.echo(f"Next: tripll approve {run_id}")
    typer.echo(f"      tripll resume {run_id}")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    input_path: Annotated[
        Path,
        typer.Argument(help="Path to input directory or a single *-wave-plan.md file."),
    ],
) -> None:
    """Validate wave-plan file(s) for tripll v1 execution graph format."""
    from tripll.parse.wave_plan_v1 import validate_wave_plan_v1

    paths: list[Path]
    if input_path.is_file():
        paths = [input_path]
    elif input_path.is_dir():
        paths = sorted(input_path.glob("*-wave-plan.md"))
        if not paths:
            typer.echo(f"No *-wave-plan.md files in {input_path}", err=True)
            raise typer.Exit(1)
    else:
        typer.echo(f"Path not found: {input_path}", err=True)
        raise typer.Exit(1)

    all_errors: list[str] = []
    for p in paths:
        all_errors.extend(validate_wave_plan_v1(p))

    if all_errors:
        typer.echo(f"Validation failed ({len(all_errors)} error(s)):", err=True)
        for err in all_errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(1)

    typer.echo(f"OK — {len(paths)} wave-plan file(s) valid (tripll v1 execution graph).")


# ---------------------------------------------------------------------------
# validate-plan — dead in-repo path refs (W4)
# ---------------------------------------------------------------------------


@app.command("validate-plan")
def validate_plan_cmd(
    plan_path: Annotated[
        Path,
        typer.Argument(help="Path to a wave-plan markdown file."),
    ],
    repo_root: Annotated[
        Path | None,
        typer.Option(
            "--repo-root",
            help="Repository root for resolving refs (default: inferred from CWD).",
        ),
    ] = None,
) -> None:
    """Validate in-repo path references in a wave-plan file (hard-fail gate).

    Prints one line per dead ref: ``plan → ref (try: suggested_fix)``.
    Exits non-zero when any in-repo reference does not resolve.
    """
    from tripll.plan_paths import format_plan_ref_errors, validate_plan

    if not plan_path.is_file():
        typer.echo(f"Plan file not found: {plan_path}", err=True)
        raise typer.Exit(1)

    root = (repo_root or resolve_repo_root()).resolve()
    dead = validate_plan(plan_path.resolve(), root)
    if not dead:
        typer.echo(f"OK — {plan_path} (all in-repo refs resolve)")
        return

    for line in format_plan_ref_errors(plan_path.resolve(), dead, root):
        typer.echo(line, err=True)
    raise typer.Exit(1)


def _print_graph_summary(input_path: Path, graph: object, *, run_id: str, mode: str) -> None:
    from tripll.graph import RunGraph

    assert isinstance(graph, RunGraph)
    errors = graph.validate()
    typer.echo(f"Input      : {input_path}")
    typer.echo(f"Run-id     : {run_id}")
    typer.echo(f"Mode       : {mode}")
    typer.echo(f"Lanes      : {len(graph.lanes)}   Nodes: {len(graph.nodes)}")
    typer.echo("")
    typer.echo("Batch order:")
    for batch in graph.batches:
        gate = " [HUMAN GATE]" if batch.is_human_gate else ""
        cw = f"  CW: {', '.join(batch.cw_seams)}" if batch.cw_seams else ""
        lanes = ", ".join(batch.lanes) if batch.lanes else "(none)"
        waves = ", ".join(batch.wave_ids) if batch.wave_ids else ""
        typer.echo(f"  {batch.batch_id:<6} — {batch.label}{gate}{cw}")
        typer.echo(f"           lanes: {lanes}")
        if waves:
            typer.echo(f"           waves: {waves}")
    typer.echo("")
    typer.echo(f"Pre-0 gates: {len(graph.pre0_gates)}")
    for i, g in enumerate(graph.pre0_gates, 1):
        typer.echo(f"  {i:2}. {g}")

    structural = [e for e in errors if "cycle" in e or "dangling" in e or "unknown CW" in e]
    warnings = [e for e in errors if e not in structural]

    if warnings:
        typer.echo("")
        typer.echo(f"Warnings ({len(warnings)}):")
        for w in warnings:
            typer.echo(f"  - {w}")
    if structural:
        typer.echo("")
        typer.echo(f"VALIDATION ERRORS ({len(structural)}):", err=True)
        for e in structural:
            typer.echo(f"  - {e}", err=True)
        raise typer.Exit(1)
    typer.echo("")
    typer.echo("Graph structurally valid.")


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

plan_app = typer.Typer(
    name="plan",
    help="Parse wave-plan inputs and publish breakdowns to trackers.",
    invoke_without_command=True,
)
app.add_typer(plan_app, name="plan")


@plan_app.callback(context_settings={"allow_interspersed_args": True})
def plan_cmd(
    ctx: typer.Context,
    input_path: Annotated[
        Path | None,
        typer.Argument(help="Path to the parallel-wave set or plain wave folder."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the derived graph without executing."),
    ] = True,
    write_manifest: Annotated[
        bool,
        typer.Option(
            "--write-manifest",
            help="Write deterministic parallel-wave.md into the input directory.",
        ),
    ] = False,
    runs_root: RunsRootOpt = None,
) -> None:
    """Parse an input directory and print the derived run graph (dry-run).

    Auto-detects Mode A (``parallel-wave.md`` present) or Mode B (plain wave
    files), builds the :class:`~tripll.graph.RunGraph`, validates it, and
    prints batch order, lane ownership, and Pre-0 gates.

    Use ``--write-manifest`` to regenerate ``parallel-wave.md`` deterministically.
    """
    if ctx.invoked_subcommand is not None:
        return
    if input_path is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(2)
    _ = runs_root
    if not input_path.exists():
        typer.echo(f"Input path not found: {input_path}", err=True)
        raise typer.Exit(1)

    from tripll.parse import build_graph_from_dir, detect_mode
    from tripll.parse.manifest import write_parallel_wave_manifest
    from tripll.parse.wave_plan_v1 import parse_wave_plan_v1

    run_id = make_run_id(input_path.name)
    wave_files = sorted(input_path.glob("*-wave-plan.md"))
    if wave_files and any(parse_wave_plan_v1(f).has_execution_graph for f in wave_files):
        mode = "B-v1"
    else:
        mode = detect_mode(input_path)
    graph = build_graph_from_dir(input_path, run_id=run_id)

    if write_manifest:
        manifest_path = input_path / "parallel-wave.md"
        write_parallel_wave_manifest(graph, manifest_path)
        typer.echo(f"Wrote manifest: {manifest_path}")

    if dry_run:
        _print_graph_summary(input_path, graph, run_id=run_id, mode=mode)


@plan_app.command("publish")
def plan_publish_cmd(
    plan_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a wave-plan markdown file.",
            exists=True,
            dir_okay=False,
        ),
    ],
    tracker: Annotated[
        str,
        typer.Option("--tracker", help="Tracker backend (github)."),
    ] = "github",
    parent: Annotated[
        str,
        typer.Option("--parent", help="Parent epic ref (e.g. issue number)."),
    ] = "",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Write local artifact only; skip tracker mutations."),
    ] = False,
    repo: Annotated[
        str | None,
        typer.Option("--repo", help="GitHub owner/repo override for github tracker."),
    ] = None,
) -> None:
    """Publish a plan breakdown to a tracker (local artifact → summary → tickets)."""
    if not parent.strip():
        typer.echo("--parent is required", err=True)
        raise typer.Exit(2)
    if tracker != "github":
        typer.echo(f"Unsupported tracker: {tracker!r} (only github is implemented)", err=True)
        raise typer.Exit(2)

    from tripll.trackers.github import GitHubTracker
    from tripll.trackers.publish import publish_plan_breakdown

    backend = GitHubTracker(repo=repo)
    result = publish_plan_breakdown(
        tracker=backend,
        plan_path=plan_path,
        parent_ref=parent.strip(),
        dry_run=dry_run,
    )
    typer.echo(f"artifact: {result.artifact_path}")
    if result.summary_ref:
        typer.echo(f"summary: {result.summary_ref}")
    typer.echo(f"created {result.created}, skipped {result.skipped}")


# ---------------------------------------------------------------------------
# Entrypoint (plan command continued above)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# graph  (W3 extraction / fusion / quality gate)
# ---------------------------------------------------------------------------

graph_app = typer.Typer(
    name="graph",
    help="Code KG extraction, fusion, quality gate, and query.",
    no_args_is_help=True,
)
app.add_typer(graph_app, name="graph")

findings_app = typer.Typer(
    name="findings",
    help="GitHub check/review ingestion → Finding graph (§7.12).",
    no_args_is_help=True,
)
app.add_typer(findings_app, name="findings")

rules_app = typer.Typer(
    name="rules",
    help="Derived rules and on-demand context modules (W2).",
    no_args_is_help=True,
)
app.add_typer(rules_app, name="rules")

review_app = typer.Typer(
    name="review",
    help="mergeCraft review wrappers (diff / watch / init) — external tool via uv.",
    no_args_is_help=True,
)
app.add_typer(review_app, name="review")

bench_app = typer.Typer(
    name="bench",
    help="Frozen L1 benchmark replay and metric deltas (§9.4).",
    no_args_is_help=True,
)
app.add_typer(bench_app, name="bench")


@review_app.command("diff")
def review_diff(
    base: Annotated[
        str | None,
        typer.Option("--base", help="Diff base ref (default: origin/main)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Materialize diff + prompt without calling an agent."),
    ] = False,
) -> None:
    """Advisory offline review via ``mergecraft diff-review``."""
    from tripll.config import load_config
    from tripll.review import resolve_mergecraft_ref, run_mergecraft

    cfg = load_config()
    args = ["diff-review"]
    if base:
        args.extend(["--base", base])
    else:
        args.extend(["--base", os.environ.get("TRIPLL_CI_BASE", "origin/main")])
    if dry_run:
        args.append("--dry-run")
    code = run_mergecraft(args, ref=resolve_mergecraft_ref(cfg.review))
    raise typer.Exit(code)


@review_app.command("watch")
def review_watch(
    pr: Annotated[int, typer.Option("--pr", help="Pull request number to watch.")],
    pretty: Annotated[
        bool,
        typer.Option("--pretty", "-p", help="Human-readable timeline output."),
    ] = False,
) -> None:
    """Stream PR timeline JSONL via ``mergecraft watch``."""
    from tripll.config import load_config
    from tripll.review import resolve_mergecraft_ref, run_mergecraft

    cfg = load_config()
    args = ["watch", "--pr", str(pr)]
    if pretty:
        args.append("--pretty")
    code = run_mergecraft(args, ref=resolve_mergecraft_ref(cfg.review))
    raise typer.Exit(code)


@review_app.command("init")
def review_init(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing mergeCraft scaffold files."),
    ] = False,
) -> None:
    """Scaffold ``.mergecraft/`` + workflow from ``[review]`` posture."""
    from tripll.config import load_config
    from tripll.review import scaffold_mergecraft

    root = resolve_repo_root()
    cfg = load_config(repo_root=root)
    for line in scaffold_mergecraft(root, review=cfg.review, force=force, write_workflow=True):
        typer.echo(line)


@review_app.command("dispatch")
def review_dispatch(
    pr: Annotated[int, typer.Option("--pr", help="Pull request number.")],
    mode: Annotated[
        str,
        typer.Option("--mode", help="mergeCraft mode: AddressReviews|Fix|Build|…"),
    ],
    prompt: Annotated[
        str,
        typer.Option("--prompt", help="Agent prompt body."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan only; do not call gh workflow run."),
    ] = False,
) -> None:
    """Trigger mergeCraft workflow_dispatch when ``[review].posture`` allows it."""
    from tripll.config import load_config
    from tripll.review import dispatch_mode

    cfg = load_config()
    result = dispatch_mode(
        pr=pr,
        mode=mode,
        prompt=prompt,
        workflow=cfg.review.workflow,
        review=cfg.review,
        dry_run=dry_run,
    )
    typer.echo(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise typer.Exit(1)
    if result.get("skipped") and not dry_run:
        raise typer.Exit(0)


@bench_app.command("run")
def bench_run_cmd(
    bench_dir: Annotated[
        Path | None,
        typer.Option("--bench-dir", help="Path to bench/ (default: auto-detect)."),
    ] = None,
    graph_db: Annotated[
        Path | None,
        typer.Option("--db", help="GraphStore SQLite path for graph-brief replay."),
    ] = None,
) -> None:
    """Replay sealed tasks and emit metric deltas vs baseline."""
    from tripll.bench import run_benchmark

    result = run_benchmark(
        bench_dir=bench_dir,
        graph_db=graph_db,
    )
    typer.echo(f"tasks: {result.task_count}")
    typer.echo(f"d23_verdict: {result.d23_verdict}")
    for key in sorted(result.metrics):
        delta = result.deltas[key]
        sign = "+" if delta >= 0 else ""
        typer.echo(
            f"{key}: {result.metrics[key]:.4f} (baseline {result.baseline[key]:.4f}, {sign}{delta:.4f})"
        )


@graph_app.command("extract")
def graph_extract(
    repo: Annotated[
        str,
        typer.Option("--repo", help="Target repo slug (default: tripll)."),
    ] = "tripll",
    sha: Annotated[
        str | None,
        typer.Option("--sha", help="Commit sha for incremental extraction."),
    ] = None,
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
    semantic: Annotated[
        bool,
        typer.Option("--semantic/--no-semantic", help="Run batched semantic pass."),
    ] = False,
    backend: Annotated[
        str,
        typer.Option("--backend", help="Agent backend for --semantic (default: claude_code)."),
    ] = "claude_code",
    repo_root: Annotated[
        Path | None,
        typer.Option("--repo-root", help="Target checkout root."),
    ] = None,
) -> None:
    """Extract deterministic (and optional semantic) code KG into SQLite."""
    from tripll.adapters import get_adapter
    from tripll.extract.pipeline import extract_repo
    from tripll.graphstore import SqliteGraphStore

    root = repo_root or resolve_repo_root()
    adapter = None
    if semantic:
        name, opts = _backend_options(backend=backend)
        adapter = get_adapter(name, options=opts)
        caps = adapter.capabilities()
        if not caps.available:
            typer.echo(
                f"Semantic extraction requires an available backend; {name} unavailable: "
                f"{caps.detail}",
                err=True,
            )
            raise typer.Exit(1)

    store = SqliteGraphStore(str(db))
    try:
        counts = extract_repo(
            store,
            root,
            repo=repo,
            sha=sha,
            run_semantic=semantic,
            adapter=adapter,
        )
    finally:
        store.close()
    typer.echo(
        f"extracted {counts.get('nodes', 0)} nodes, "
        f"{counts.get('edges', 0)} edges from {counts.get('files', 0)} files "
        f"(sha={sha or 'HEAD'})"
    )


@graph_app.command("fuse")
def graph_fuse(
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
) -> None:
    """Run fusion blocking and auto-merge on live Symbol nodes."""
    from tripll.extract.pipeline import fuse_store
    from tripll.graphstore import SqliteGraphStore

    store = SqliteGraphStore(str(db))
    try:
        result = fuse_store(store)
    finally:
        store.close()
    typer.echo(f"fuse: {result['merged']} merges from {result['candidates']} candidate pairs")


@graph_app.command("gate")
def graph_gate(
    predicate: Annotated[
        str,
        typer.Option("--predicate", help="Semantic predicate to gate."),
    ] = "IMPLEMENTS",
    precision: Annotated[
        float,
        typer.Option("--precision", help="Observed sample precision."),
    ] = 0.95,
    sample_size: Annotated[
        int,
        typer.Option("--sample-size", help="Sample size for the gate."),
    ] = 50,
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
) -> None:
    """Run the semantic extractor quality gate and record a Verdict node."""
    from tripll.extract.quality_gate import run_quality_gate
    from tripll.graphstore import SqliteGraphStore

    store = SqliteGraphStore(str(db))
    try:
        verdict = run_quality_gate(
            predicate=predicate,
            sample_size=sample_size,
            precision=precision,
            store=store,
        )
    finally:
        store.close()
    status = "PASS" if verdict["passed"] else "FAIL"
    typer.echo(f"gate {predicate}: {status} precision={precision} — {verdict.get('remedy', '')}")
    if not verdict["passed"]:
        raise typer.Exit(1)


@findings_app.command("sync")
def findings_sync(
    pr: Annotated[int, typer.Option("--pr", help="Pull request number to sync.")],
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Run id for Finding natural keys."),
    ] = "local",
) -> None:
    """Sync check-runs and review comments for a PR into the Finding graph."""
    from tripll.github.sync import open_store, sync_pr_findings

    store = open_store(db)
    try:
        count = sync_pr_findings(pr, store, run_id=run_id)
    finally:
        store.close()
    typer.echo(f"synced {count} finding(s) from PR #{pr}")


@findings_app.command("list")
def findings_list(
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
    state: Annotated[
        str | None,
        typer.Option("--state", help="Filter by finding state."),
    ] = None,
) -> None:
    """List Finding nodes from the graph."""
    from tripll.github.findings import list_findings_from_store
    from tripll.github.sync import open_store

    store = open_store(db)
    try:
        rows = list_findings_from_store(store, state=state)
    finally:
        store.close()
    if not rows:
        typer.echo("(no findings)")
        return
    for row in rows:
        typer.echo(
            f"{row.get('finding_id', '?'):<18}  {row.get('state', '?'):<10}  "
            f"{row.get('kind', '?'):<16}  {row.get('rule_id', '')}"
        )


@findings_app.command("triage")
def findings_triage(
    finding_id: Annotated[str, typer.Argument(help="Finding id to triage.")],
    state: Annotated[
        str,
        typer.Option("--state", help="New state: accepted|rejected|deferred|fixed."),
    ],
    rationale: Annotated[
        str | None,
        typer.Option("--rationale", help="Rationale (required for rejected)."),
    ] = None,
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
    learnings: Annotated[
        Path,
        typer.Option("--learnings", help="Rejected-findings export path."),
    ] = Path(".mergecraft/learnings.md"),
) -> None:
    """Update finding state; export learnings when rejected."""
    from tripll.github.findings import list_findings_from_store
    from tripll.github.sync import open_store, triage_and_export

    store = open_store(db)
    try:
        matches = [f for f in list_findings_from_store(store) if f.get("finding_id") == finding_id]
        if not matches:
            typer.echo(f"Finding not found: {finding_id}", err=True)
            raise typer.Exit(1)
        updated = triage_and_export(
            matches[0],
            store,
            state=state,
            rationale=rationale,
            learnings_path=learnings,
        )
    finally:
        store.close()
    typer.echo(f"triage {finding_id} → {updated.get('state')}")


@findings_app.command("export-learnings")
def findings_export_learnings(
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
    learnings: Annotated[
        Path,
        typer.Option("--learnings", help="Rejected-findings export path."),
    ] = Path(".mergecraft/learnings.md"),
) -> None:
    """Rebuild ``.mergecraft/learnings.md`` from rejected Finding nodes."""
    from tripll.github.findings import list_findings_from_store
    from tripll.github.learnings import export_learnings
    from tripll.github.sync import open_store

    store = open_store(db)
    try:
        rows = list_findings_from_store(store)
    finally:
        store.close()
    path = export_learnings(rows, path=learnings)
    rejected = sum(1 for r in rows if r.get("state") == "rejected")
    typer.echo(f"exported {rejected} rejected finding(s) → {path}")


@rules_app.command("derive")
def rules_derive(
    repo_root: Annotated[
        Path | None,
        typer.Option(
            "--repo-root",
            help="Repository root (default: resolved git root or CWD).",
            file_okay=False,
            dir_okay=True,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing rule/context markdown."),
    ] = False,
) -> None:
    """Derive cited rules and context modules from evaluation findings (CTX-01, R32)."""
    from tripll.rules.derive import derive_rules

    root = (repo_root or resolve_repo_root()).resolve()
    result = derive_rules(root, force=force)
    typer.echo(f"Derived rules for {root}")
    typer.echo(f"  rules:   {len(result.rules_written)} file(s) under .tripll/rules/")
    typer.echo(f"  context: {len(result.context_written)} file(s) under .tripll/context/")
    if result.skipped:
        typer.echo(f"  skipped: {', '.join(result.skipped)}")


@rules_app.command("list")
def rules_list(
    state: Annotated[
        str | None,
        typer.Option("--state", help="Filter by lifecycle state (proposed, active, retired)."),
    ] = None,
    repo_root: Annotated[
        Path | None,
        typer.Option(
            "--repo-root",
            help="Repository root (default: resolved git root or CWD).",
            file_okay=False,
            dir_okay=True,
        ),
    ] = None,
) -> None:
    """List rules from ``.tripll/rules/`` (operator visibility; proposed rules do not pack)."""
    from tripll.rules.store import RuleStore

    root = (repo_root or resolve_repo_root()).resolve()
    store = RuleStore(root)
    rules = store.list_rules(state=state)
    if not rules:
        typer.echo(
            f"No rules found under {store.rules_path}" + (f" (state={state})" if state else "")
        )
        return
    for rule in rules:
        typer.echo(f"{rule.rule_id}\t{rule.state}\t{rule.origin}")


@rules_app.command("promote")
def rules_promote(
    rule_id: Annotated[str, typer.Argument(help="Rule slug to activate (operator-only, R27).")],
    repo_root: Annotated[
        Path | None,
        typer.Option(
            "--repo-root",
            help="Repository root (default: resolved git root or CWD).",
            file_okay=False,
            dir_okay=True,
        ),
    ] = None,
) -> None:
    """Promote a proposed rule to active (operator-only — no agent path, R27)."""
    from tripll.rules.promote import promote_rule
    from tripll.rules.store import RuleStore

    root = (repo_root or resolve_repo_root()).resolve()
    store = RuleStore(root)
    active = promote_rule(rule_id, store=store)
    typer.echo(f"promoted {active.rule_id} → {active.state}")


@rules_app.command("retire")
def rules_retire(
    rule_id: Annotated[str, typer.Argument(help="Rule slug to retire.")],
    repo_root: Annotated[
        Path | None,
        typer.Option(
            "--repo-root",
            help="Repository root (default: resolved git root or CWD).",
            file_okay=False,
            dir_okay=True,
        ),
    ] = None,
) -> None:
    """Retire an active or proposed rule (operator-only)."""
    from tripll.rules.promote import retire_rule
    from tripll.rules.store import RuleStore

    root = (repo_root or resolve_repo_root()).resolve()
    store = RuleStore(root)
    retired = retire_rule(rule_id, store=store)
    typer.echo(f"retired {retired.rule_id} → {retired.state}")


@app.command("calibrate")
def calibrate_cmd(
    run_id: Annotated[str, typer.Option("--run", help="Run id to score against the ledger.")],
    runs_root: RunsRootOpt = None,
) -> None:
    """Score predicted first-pass probability against ledger attempts (W5, R28 advisory)."""
    from tripll.calibrate.score import calibrate_run, format_calibration_report

    rr = _resolve_runs_root(runs_root)
    report = calibrate_run(run_id=run_id, runs_root=rr.root, write_realized=True)
    typer.echo(format_calibration_report(report), nl=False)


@graph_app.command("query")
def graph_query(
    seed: Annotated[
        str,
        typer.Argument(help="Seed node_id for subgraph query."),
    ],
    hops: Annotated[
        int,
        typer.Option("--hops", help="Subgraph hop limit."),
    ] = 2,
    at_sha: Annotated[
        str | None,
        typer.Option("--at-sha", help="Evaluate graph at commit sha."),
    ] = None,
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
) -> None:
    """Query a subgraph from the Code KG."""
    from tripll.extract.pipeline import query_store
    from tripll.graphstore import SqliteGraphStore

    store = SqliteGraphStore(str(db))
    try:
        result = query_store(store, seed=seed, hops=hops, at_sha=at_sha)
    finally:
        store.close()
    typer.echo(f"nodes ({len(result['nodes'])}): {', '.join(result['nodes'][:10])}")
    typer.echo(f"edges ({len(result['edges'])})")


# ---------------------------------------------------------------------------
# serve  (W4 FastAPI control plane)
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind host (default: localhost)."),
    ] = "localhost",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Bind port (default: 8765)."),
    ] = 8765,
    runs_root: RunsRootOpt = None,
) -> None:
    """Start the FastAPI control-plane server (W4).

    Launches uvicorn on the ``tripll.api`` FastAPI app.  Requires the
    ``api`` optional-dependency extra (``uv sync --extra api``).

    Auth: set ``TRIPLL_API_TOKEN`` to require a Bearer token on all
    requests.  When unset, the server is accessible without auth (safe when
    bound to localhost, which is the default).

    Args:
        host (str): Bind host.  Default is ``localhost`` to avoid accidental
            exposure on networked interfaces.
        port (int): Bind port.  Default is 8765.
        runs_root (Path | None): Override runs root.
    """
    try:
        import uvicorn
    except ImportError as exc:
        typer.echo(
            "uvicorn not installed. Run: uv sync --extra api",
            err=True,
        )
        raise typer.Exit(1) from exc

    from tripll.api import create_app

    rr = _resolve_runs_root(runs_root)
    rr.init()  # ensure folders exist

    # Seed default profiles on first serve.
    from tripll.profiles import control_plane_db_path, open_profile_store, seed_default_profiles

    db_path = control_plane_db_path(rr.root)
    with open_profile_store(db_path) as store:
        created = seed_default_profiles(store)
        if created:
            typer.echo(f"Seeded {len(created)} default profile(s): {', '.join(created)}")

    fastapi_app = create_app(runs_root=rr.root)
    typer.echo(f"tripll control plane → http://{host}:{port}/")
    typer.echo(f"  Runs root : {rr.root}")
    typer.echo(f"  API docs  : http://{host}:{port}/docs")
    token = os.environ.get("TRIPLL_API_TOKEN", "")
    if token:
        typer.echo("  Auth      : Bearer token required (TRIPLL_API_TOKEN set)")
    else:
        typer.echo("  Auth      : NONE (dev mode — set TRIPLL_API_TOKEN for production)")
    uvicorn.run(fastapi_app, host=host, port=port)


# spec-kit-wave (absorbed skw) — doc gates and deprecated alias
# ---------------------------------------------------------------------------

app.add_typer(skw_legacy_app, name="skw")


def _skw_kit_root() -> Path:
    from tripll.skw.paths import kit_root

    return kit_root()


def _docs_repo_root(repo_root: Path | None) -> Path:
    return (repo_root or resolve_repo_root()).resolve()


def _run_docs(kind: str, directory: Path, *, repo_root: Path | None, mode: str) -> None:
    from tripll.skw.doc_folder import run_docs_command

    result = run_docs_command(
        mode,
        kind=kind,
        directory=directory.resolve(),
        repo_root=_docs_repo_root(repo_root),
        kit_root=_skw_kit_root(),
    )
    for file_result in result.files:
        for err in file_result.errors:
            typer.echo(err, err=True)
        for warn in file_result.warnings:
            typer.echo(f"warning: {warn}", err=True)
    if result.exit_code != 0:
        raise typer.Exit(result.exit_code)


spec_app = typer.Typer(name="spec", help="Spec folder validate and score.", no_args_is_help=True)
prd_app = typer.Typer(name="prd", help="PRD folder validate and score.", no_args_is_help=True)
changelog_app = typer.Typer(
    name="changelog",
    help="CHANGELOG.md structural and diff gates.",
    no_args_is_help=True,
)
app.add_typer(spec_app, name="spec")
app.add_typer(prd_app, name="prd")
app.add_typer(changelog_app, name="changelog")

# ---------------------------------------------------------------------------
# pr  (W9 PR phase — shepherd, status, merge gate)
# ---------------------------------------------------------------------------

pr_app = typer.Typer(
    name="pr",
    help="PR phase: idempotent push/open, fix loop, human merge gate.",
    no_args_is_help=True,
)
app.add_typer(pr_app, name="pr")


@pr_app.command("shepherd")
def pr_shepherd_cmd(
    run_id: Annotated[str, typer.Option("--run", "-r", help="Run id to shepherd.")],
    phase: Annotated[
        str,
        typer.Option(
            "--phase",
            help="Loop phase: deliver, investigate_and_fix, or merge.",
        ),
    ] = "investigate_and_fix",
    runs_root: RunsRootOpt = None,
) -> None:
    """Run one PR shepherd step (push/open, investigate/fix, or merge gate)."""
    from tripll.loops.l1_pr import shepherd_run

    rr = _resolve_runs_root(runs_root)
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    result = shepherd_run(run_id=run_id, run_dir=run_dir, phase=phase)
    typer.echo(json.dumps(result, indent=2, default=str))


@pr_app.command("status")
def pr_status_cmd(
    run_id: Annotated[str, typer.Argument(help="Run id.")],
    runs_root: RunsRootOpt = None,
) -> None:
    """Show PR phase state and merge-gate markers for a run."""
    from tripll.loops.l1_pr import pr_status

    rr = _resolve_runs_root(runs_root)
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(pr_status(run_dir=run_dir), indent=2))


@pr_app.command("approve-merge")
def pr_approve_merge_cmd(
    run_id: Annotated[str, typer.Argument(help="Run id parked at merge gate.")],
    runs_root: RunsRootOpt = None,
) -> None:
    """Approve the human merge gate — never auto-merges without this step."""
    from tripll.loops.l1_pr import approve_merge_gate, pr_status

    rr = _resolve_runs_root(runs_root)
    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    try:
        path = approve_merge_gate(run_dir=run_dir)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Merge gate approved: {path}")
    typer.echo(json.dumps(pr_status(run_dir=run_dir), indent=2))


@spec_app.command("validate")
def spec_validate_cmd(
    directory: Annotated[Path, typer.Argument(help="Specs directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Validate every spec in a directory."""
    _run_docs("spec", directory, repo_root=repo_root, mode="validate")


@spec_app.command("score")
def spec_score_cmd(
    directory: Annotated[Path, typer.Argument(help="Specs directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Score every spec in a directory."""
    _run_docs("spec", directory, repo_root=repo_root, mode="score")


@prd_app.command("validate")
def prd_validate_cmd(
    directory: Annotated[Path, typer.Argument(help="PRD directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Validate every PRD in a directory."""
    _run_docs("prd", directory, repo_root=repo_root, mode="validate")


@prd_app.command("score")
def prd_score_cmd(
    directory: Annotated[Path, typer.Argument(help="PRD directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Score every PRD in a directory."""
    _run_docs("prd", directory, repo_root=repo_root, mode="score")


@app.command("doc-score")
def doc_score_cmd(
    kind: Annotated[str, typer.Option("--kind", help="Doc kind: spec or prd.")] = "spec",
    directory: Annotated[Path, typer.Option("--dir", help="Folder of markdown docs.")] = Path(
        "docs"
    ),
    repo_root: Annotated[
        Path | None,
        typer.Option("--repo-root", help="Target repository root."),
    ] = None,
) -> None:
    """Score every doc in a folder for the given kind."""
    _run_docs(kind, directory, repo_root=repo_root, mode="score")


@changelog_app.command("check")
def changelog_check_cmd(
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
    base: Annotated[str, typer.Option("--base", help="Diff base ref.")] = "origin/main",
    changelog: Annotated[Path | None, typer.Option("--changelog")] = None,
) -> None:
    """Run deterministic CHANGELOG.md structural + diff gate."""
    from tripll.skw.changelog_validate import validate_changelog

    root = _docs_repo_root(repo_root)
    changelog_path = (changelog or root / "CHANGELOG.md").resolve()
    errors, warnings = validate_changelog(root, base, changelog_path=changelog_path)
    for warn in warnings:
        typer.echo(f"warning: {warn}", err=True)
    if errors:
        for err in errors:
            typer.echo(err, err=True)
        raise typer.Exit(1)
    typer.echo(f"OK — {changelog_path}")


@changelog_app.command("eval")
def changelog_eval_cmd(
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
    base: Annotated[str, typer.Option("--base")] = "origin/main",
) -> None:
    """Advisory LLM double-score for Unreleased entries (not used in CI)."""
    from tripll.skw.changelog_eval import main as changelog_eval_main

    root = _docs_repo_root(repo_root)
    raise typer.Exit(changelog_eval_main(["--repo", str(root), "--base", base, "--json"]))


def main() -> None:
    """Console script entrypoint for ``tripll``.

    Configures loguru to stderr (suppressed unless ``TRIPLL_DEBUG=1``).

    Examples:
        This function is registered as a console script; call it via the
        ``tripll`` command after installation.
    """
    log_level = (
        "DEBUG"
        if os.environ.get("TRIPLL_DEBUG")
        else ("INFO" if os.environ.get("TRIPLL_VERBOSE") else "WARNING")
    )
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="<level>{level}</level>: {message}")
    configure_observability()
    sys.argv = _rewrite_run_inject_argv(sys.argv)
    app()


if __name__ == "__main__":
    main()
