"""tripll.cli._plan — validate, validate-plan, pipeline-view, plan commands (#16 seam).

Exports:
    register_plan_commands — attach plan commands and group to *app*.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — typer resolves Path for CLI arguments
from typing import Annotated

import typer

from tripll.cli._shared import (
    RunsRootOpt,  # noqa: TC001 — typer option alias used in plan_cmd signature
)
from tripll.pipeline import make_run_id
from tripll.repo_root import resolve_repo_root


def _write_validation_graph_html(input_path: Path, out_path: Path) -> None:
    """Build the RunGraph for *input_path* and write an HTML DAG to *out_path*."""
    from tripll.graph_html import write_graph_html
    from tripll.parse import build_graph_from_dir

    input_dir = input_path if input_path.is_dir() else input_path.parent
    try:
        graph = build_graph_from_dir(input_dir, run_id=make_run_id(input_dir.name))
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Graph HTML export failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    written = write_graph_html(graph, out_path, source=str(input_dir))
    typer.echo(f"Wrote graph HTML: {written}")


def validate(
    input_path: Annotated[
        Path,
        typer.Argument(help="Path to input directory or a single *-wave-plan.md file."),
    ],
    graph_html: Annotated[
        Path | None,
        typer.Option(
            "--graph-html",
            help=(
                "On success, write a self-contained HTML graph (nodes + depends_on edges) "
                "to this path. A single file resolves its graph from the parent directory."
            ),
        ),
    ] = None,
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

    if graph_html is not None:
        _write_validation_graph_html(input_path, graph_html)


# ---------------------------------------------------------------------------
# pipeline-view — charts derived from a pipeline file
# ---------------------------------------------------------------------------


def pipeline_view_cmd(
    pipeline_file: Annotated[
        Path,
        typer.Argument(help="Path to a pipeline_format = 1 TOML file."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Destination .html file."),
    ],
    view: Annotated[
        str,
        typer.Option("--view", help="Which chart to render: execution | state."),
    ] = "execution",
) -> None:
    """Render a pipeline file as a self-contained HTML graph.

    ``execution`` draws the pipeline steps (agents, phases, gates) as nodes with
    the declared transitions as edges. ``state`` draws the artifact states as
    nodes with the agent work on the edges.
    """
    from tripll.pipeline_spec import PipelineSpecError, load_pipeline_spec
    from tripll.pipeline_views import VIEWS, write_view_html

    builder = VIEWS.get(view)
    if builder is None:
        typer.echo(f"Unknown view {view!r} (expected one of {', '.join(VIEWS)})", err=True)
        raise typer.Exit(2)
    if not pipeline_file.is_file():
        typer.echo(f"Pipeline file not found: {pipeline_file}", err=True)
        raise typer.Exit(1)
    try:
        spec = load_pipeline_spec(pipeline_file)
        written = write_view_html(builder(spec), out)
    except (PipelineSpecError, ValueError) as exc:
        typer.echo(f"Pipeline view failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Wrote pipeline view: {written}")


# ---------------------------------------------------------------------------
# validate-plan — dead in-repo path refs (W4)
# ---------------------------------------------------------------------------


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


def register_plan_commands(app: typer.Typer) -> None:
    """Register validate, validate-plan, pipeline-view, and the plan group on *app*."""

    app.command()(validate)
    app.command("validate-plan")(validate_plan_cmd)
    app.command("pipeline-view")(pipeline_view_cmd)
    app.add_typer(plan_app, name="plan")
