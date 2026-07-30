"""tripll.cli._rules — derived rules commands (issue #16 seam).

Exports:
    register_rules_commands — attach the rules group to *app*.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — typer resolves Path for CLI options
from typing import Annotated

import typer

from tripll.repo_root import resolve_repo_root

rules_app = typer.Typer(
    name="rules",
    help="Derived rules and on-demand context modules (W2).",
    no_args_is_help=True,
)


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
    from tripll.rules.operator import require_operator
    from tripll.rules.promote import promote_rule
    from tripll.rules.store import RuleStore

    try:
        require_operator(f"tripll rules promote {rule_id}")
    except PermissionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

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
    from tripll.rules.operator import require_operator
    from tripll.rules.promote import retire_rule
    from tripll.rules.store import RuleStore

    try:
        require_operator(f"tripll rules retire {rule_id}")
    except PermissionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    root = (repo_root or resolve_repo_root()).resolve()
    store = RuleStore(root)
    retired = retire_rule(rule_id, store=store)
    typer.echo(f"retired {retired.rule_id} → {retired.state}")


def register_rules_commands(app: typer.Typer) -> None:
    """Register the rules command group on *app*."""

    app.add_typer(rules_app, name="rules")
