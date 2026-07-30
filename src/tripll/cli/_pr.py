"""tripll.cli._pr — PR phase shepherd commands (issue #16 seam).

Exports:
    register_pr_commands — attach the pr group to *app*.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _resolve_runs_root,
)

pr_app = typer.Typer(
    name="pr",
    help="PR phase: idempotent push/open, fix loop, human merge gate.",
    no_args_is_help=True,
)


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


def register_pr_commands(app: typer.Typer) -> None:
    """Register the pr command group on *app*."""

    app.add_typer(pr_app, name="pr")
