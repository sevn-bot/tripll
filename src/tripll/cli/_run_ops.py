"""tripll.cli._run_ops — pause, resume, approve, run lifecycle ops (issue #16 seam).

Exports:
    register_run_ops_commands — attach run operation commands to *app*.
"""

from __future__ import annotations

from typing import Annotated

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _backend_options,
    _engine_for,
    _finalize_run_result,
    _prepare_resume,
    _refresh_report,
    _resolve_runs_root,
)
from tripll.repo_root import resolve_repo_root


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


def register_run_ops_commands(app: typer.Typer) -> None:
    """Register pause, resume, approve, delete-run, reset-run, pre0-interview on *app*."""

    app.command()(pause)
    app.command()(resume)
    app.command()(approve)
    app.command("delete-run")(delete_run_cmd)
    app.command("reset-run")(reset_run_cmd)
    app.command("pre0-interview")(pre0_interview_cmd)
