"""tripll.cli._onboard — setup, doctor, init, new commands (issue #16 seam).

Exports:
    register_onboard_commands — attach onboarding commands to the root Typer app.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — typer resolves Path for CLI options
from typing import Annotated

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _resolve_runs_root,
)


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


def register_onboard_commands(app: typer.Typer) -> None:
    """Register setup, doctor, init, and new on *app*."""

    app.command()(setup)
    app.command()(doctor)
    app.command()(init)
    app.command()(new)
