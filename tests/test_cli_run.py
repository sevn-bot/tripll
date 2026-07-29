"""Characterization tests for :mod:`tripll.cli._run` (issue #16 seam)."""

from __future__ import annotations

from typer.testing import CliRunner

import tripll.cli
import tripll.cli._run as cli_run
from tripll.cli import _rewrite_run_inject_argv, app
from tripll.cli._run import register_run_commands, rewrite_run_inject_argv


def test_cli_reexports_rewrite_run_inject_argv() -> None:
    """Public ``tripll.cli`` API stays aligned with the extracted module."""
    assert _rewrite_run_inject_argv is cli_run.rewrite_run_inject_argv
    assert rewrite_run_inject_argv is cli_run.rewrite_run_inject_argv


def test_rewrite_run_inject_argv_maps_nested_commands() -> None:
    """``tripll run inject`` and ``run reconcile-graph`` rewrite to hidden subcommands."""
    assert _rewrite_run_inject_argv(["tripll", "run", "inject", "run-1", "--after", "W1"]) == [
        "tripll",
        "run-inject",
        "run-1",
        "--after",
        "W1",
    ]
    assert _rewrite_run_inject_argv(["tripll", "run", "reconcile-graph", "run-1"]) == [
        "tripll",
        "run-reconcile-graph",
        "run-1",
    ]
    assert _rewrite_run_inject_argv(["tripll", "status"]) == ["tripll", "status"]


def test_register_run_commands_attaches_run_subcommands() -> None:
    """Extracted registrar wires run, run-inject, and run-reconcile-graph."""
    import typer

    sub = typer.Typer()
    register_run_commands(sub)
    names = {c.name for c in sub.registered_commands}
    assert "run-inject" in names
    assert "run-reconcile-graph" in names
    assert any(c.callback.__name__ == "run" for c in sub.registered_commands)


def test_run_help_unchanged_on_root_app() -> None:
    """Root app still exposes ``tripll run`` after extraction."""
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "Start (or dry-run) the wave-orchestrator pipeline" in result.output


def test_main_module_still_tripll_cli() -> None:
    """Console script entrypoint module path is unchanged."""
    assert tripll.cli.main.__module__ == "tripll.cli"
