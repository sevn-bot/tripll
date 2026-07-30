"""tripll.cli._wave — wave add command group (issue #16 seam).

Exports:
    register_wave_commands — attach the wave Typer group to *app*.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — typer resolves Path for CLI options
from typing import Annotated, Literal

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _cost_budget_usd,
    _resolve_runs_root,
)

wave_app = typer.Typer(
    name="wave",
    help="Mid-run wave graph operations (parallel lane inject).",
    no_args_is_help=True,
)


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


def register_wave_commands(app: typer.Typer) -> None:
    """Register the wave command group on *app*."""

    app.add_typer(wave_app, name="wave")
