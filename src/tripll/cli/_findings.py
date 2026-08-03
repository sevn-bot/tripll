"""tripll.cli._findings — findings ingestion commands (issue #16 seam).

Exports:
    register_findings_commands — attach the findings group to *app*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tripll.repo_root import resolve_repo_root

findings_app = typer.Typer(
    name="findings",
    help="GitHub check/review ingestion → Finding graph (§7.12).",
    no_args_is_help=True,
)


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
    gate: Annotated[
        bool,
        typer.Option("--gate", help="Run the LLM noise gate after sync (flags only)."),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="pydantic-ai model for --gate."),
    ] = None,
) -> None:
    """Sync check-runs and review comments for a PR into the Finding graph."""
    from tripll.github.findings import GateModelUnavailableError, gate_findings_in_store
    from tripll.github.sync import open_store, sync_pr_findings

    store = open_store(db)
    try:
        count = sync_pr_findings(pr, store, run_id=run_id)
        if gate:
            try:
                _, report = gate_findings_in_store(
                    store,
                    model=model,
                    pr_number=pr,
                    run_id=run_id,
                )
            except GateModelUnavailableError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(1) from exc
            typer.echo(
                f"synced {count} finding(s) from PR #{pr}; "
                f"gate precision={report.precision} (n={report.sample_size})"
            )
            return
    finally:
        store.close()
    typer.echo(f"synced {count} finding(s) from PR #{pr}")


@findings_app.command("gate")
def findings_gate(
    db: Annotated[
        Path,
        typer.Option("--db", help="GraphStore SQLite path."),
    ] = Path(".tripll/graph.db"),
    pr: Annotated[
        int | None,
        typer.Option("--pr", help="Limit gate to findings from one PR."),
    ] = None,
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Run id for Verdict natural keys."),
    ] = "local",
    model: Annotated[
        str | None,
        typer.Option("--model", help="pydantic-ai model string."),
    ] = None,
    precision_only: Annotated[
        bool,
        typer.Option(
            "--precision",
            help="Report gate precision vs operator triage without re-running the gate.",
        ),
    ] = False,
) -> None:
    """Flag review nits/questions via LLM — never auto-rejects; operator triages."""
    from tripll.github.findings import (
        GateModelUnavailableError,
        compute_gate_precision,
        gate_findings_in_store,
        gate_model_configured,
        list_findings_from_store,
    )
    from tripll.github.sync import open_store

    store = open_store(db)
    try:
        if precision_only:
            rows = list_findings_from_store(store)
            if pr is not None:
                rows = [row for row in rows if row.get("pr_number") == pr]
            report = compute_gate_precision(rows)
            typer.echo(
                f"gate precision={report.precision} recall={report.recall} "
                f"(n={report.sample_size}, tp={report.true_positive}, "
                f"fp={report.false_positive}, tn={report.true_negative}, "
                f"fn={report.false_negative})"
            )
            return
        if not gate_model_configured(model):
            typer.echo(
                "findings gate needs a judge model and API key "
                f"({GateModelUnavailableError.__name__})",
                err=True,
            )
            raise typer.Exit(1)
        gated, report = gate_findings_in_store(
            store,
            model=model,
            pr_number=pr,
            run_id=run_id,
        )
    except GateModelUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        store.close()
    candidates = sum(1 for row in gated if row.get("gate_verdict") == "baseline_candidate")
    noise = sum(1 for row in gated if row.get("gate_verdict") == "noise")
    typer.echo(
        f"gated {len(gated)} finding(s): {candidates} baseline_candidate, {noise} noise "
        f"(precision={report.precision}, n={report.sample_size})"
    )


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
    from tripll.rules.store import RuleStore

    active_rules = RuleStore(resolve_repo_root()).list_active()
    path = export_learnings(rows, path=learnings, active_rules=active_rules)
    rejected = sum(1 for r in rows if r.get("state") == "rejected")
    typer.echo(f"exported {rejected} rejected finding(s) → {path}")


def register_findings_commands(app: typer.Typer) -> None:
    """Register the findings command group on *app*."""

    app.add_typer(findings_app, name="findings")
