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

import os
import sys
from typing import Annotated

import typer
from loguru import logger

from tripll import __version__
from tripll.cli._docs import register_docs_commands
from tripll.cli._findings import register_findings_commands
from tripll.cli._graph import register_graph_commands
from tripll.cli._onboard import register_onboard_commands
from tripll.cli._plan import register_plan_commands
from tripll.cli._pr import register_pr_commands
from tripll.cli._review import register_review_commands
from tripll.cli._rules import register_rules_commands
from tripll.cli._run import register_run_commands, rewrite_run_inject_argv
from tripll.cli._run_ops import register_run_ops_commands
from tripll.cli._shared import _run_integration as _run_integration
from tripll.cli._status import _orchestrator_watch_lines as _orchestrator_watch_lines
from tripll.cli._status import register_status_commands
from tripll.cli._wave import register_wave_commands
from tripll.obs import configure_observability

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


register_onboard_commands(app)
register_status_commands(app)
register_wave_commands(app)
register_run_ops_commands(app)
register_plan_commands(app)
register_graph_commands(app)
register_findings_commands(app)
register_rules_commands(app)
register_review_commands(app)
register_docs_commands(app)
register_pr_commands(app)


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
