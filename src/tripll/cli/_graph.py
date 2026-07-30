"""tripll.cli._graph — graph KG and calibrate commands (issue #16 seam).

Exports:
    register_graph_commands — attach graph group and calibrate to *app*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _backend_options,
    _resolve_runs_root,
)
from tripll.repo_root import resolve_repo_root

graph_app = typer.Typer(
    name="graph",
    help="Code KG extraction, fusion, quality gate, and query.",
    no_args_is_help=True,
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


def register_graph_commands(app: typer.Typer) -> None:
    """Register graph commands, calibrate, and mount the graph group on *app*."""

    app.add_typer(graph_app, name="graph")
    app.command("calibrate")(calibrate_cmd)
