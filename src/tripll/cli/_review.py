"""tripll.cli._review — mergeCraft review and bench commands (issue #16 seam).

Exports:
    register_review_commands — attach review and bench groups to *app*.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from tripll.repo_root import resolve_repo_root

review_app = typer.Typer(
    name="review",
    help="mergeCraft review wrappers (diff / watch / init) — external tool via uv.",
    no_args_is_help=True,
)

bench_app = typer.Typer(
    name="bench",
    help="Frozen L1 benchmark replay and metric deltas (§9.4).",
    no_args_is_help=True,
)


@review_app.command("diff")
def review_diff(
    base: Annotated[
        str | None,
        typer.Option("--base", help="Diff base ref (default: origin/main)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Materialize diff + prompt without calling an agent."),
    ] = False,
    json_out: Annotated[
        Path | None,
        typer.Option(
            "--json",
            help="Write structured mergeCraft findings JSON to PATH (``diff-review --json``).",
        ),
    ] = None,
) -> None:
    """Advisory offline review via ``mergecraft diff-review``."""
    from tripll.config import load_config
    from tripll.review import resolve_mergecraft_ref, run_mergecraft

    cfg = load_config()
    args = ["diff-review"]
    if base:
        args.extend(["--base", base])
    else:
        args.extend(["--base", os.environ.get("TRIPLL_CI_BASE", "origin/main")])
    if dry_run:
        args.append("--dry-run")
    if json_out is not None:
        args.extend(["--json", str(json_out)])
    code = run_mergecraft(args, ref=resolve_mergecraft_ref(cfg.review))
    raise typer.Exit(code)


@review_app.command("load-json")
def review_load_json(
    path: Annotated[
        Path,
        typer.Argument(help="Path to mergeCraft ``diff-review --json`` output."),
    ],
    head_sha: Annotated[
        str,
        typer.Option("--head-sha", help="Optional git head SHA for normalized findings."),
    ] = "",
) -> None:
    """Load mergeCraft structured findings JSON and emit tripll-normalized records."""
    from tripll.review import load_mergecraft_findings_json, normalize_mergecraft_findings

    raw = load_mergecraft_findings_json(path)
    normalized = normalize_mergecraft_findings(raw, head_sha=head_sha)
    typer.echo(json.dumps({"findings": normalized}, indent=2))


@review_app.command("watch")
def review_watch(
    pr: Annotated[int, typer.Option("--pr", help="Pull request number to watch.")],
    pretty: Annotated[
        bool,
        typer.Option("--pretty", "-p", help="Human-readable timeline output."),
    ] = False,
) -> None:
    """Stream PR timeline JSONL via ``mergecraft watch``."""
    from tripll.config import load_config
    from tripll.review import resolve_mergecraft_ref, run_mergecraft

    cfg = load_config()
    args = ["watch", "--pr", str(pr)]
    if pretty:
        args.append("--pretty")
    code = run_mergecraft(args, ref=resolve_mergecraft_ref(cfg.review))
    raise typer.Exit(code)


@review_app.command("init")
def review_init(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing mergeCraft scaffold files."),
    ] = False,
) -> None:
    """Scaffold ``.mergecraft/`` + workflow from ``[review]`` posture."""
    from tripll.config import load_config
    from tripll.review import scaffold_mergecraft

    root = resolve_repo_root()
    cfg = load_config(repo_root=root)
    for line in scaffold_mergecraft(root, review=cfg.review, force=force, write_workflow=True):
        typer.echo(line)


@review_app.command("dispatch")
def review_dispatch(
    pr: Annotated[int, typer.Option("--pr", help="Pull request number.")],
    mode: Annotated[
        str,
        typer.Option("--mode", help="mergeCraft mode: AddressReviews|Fix|Build|…"),
    ],
    prompt: Annotated[
        str,
        typer.Option("--prompt", help="Agent prompt body."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan only; do not call gh workflow run."),
    ] = False,
) -> None:
    """Trigger mergeCraft workflow_dispatch when ``[review].posture`` allows it."""
    from tripll.config import load_config
    from tripll.review import dispatch_mode

    cfg = load_config()
    result = dispatch_mode(
        pr=pr,
        mode=mode,
        prompt=prompt,
        workflow=cfg.review.workflow,
        review=cfg.review,
        dry_run=dry_run,
    )
    typer.echo(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise typer.Exit(1)
    if result.get("skipped") and not dry_run:
        raise typer.Exit(0)


@bench_app.command("emit-review-tasks")
def bench_emit_review_tasks_cmd(
    baseline: Annotated[
        Path,
        typer.Option("--baseline", help="Review baseline JSONL input."),
    ] = Path("bench/review/baseline.jsonl"),
    dest: Annotated[
        Path,
        typer.Option("--dest", help="Harbor task output root (bench/review/)."),
    ] = Path("bench/review"),
    bundles_dir: Annotated[
        Path,
        typer.Option("--bundles-dir", help="Directory of {repo}-pr{N}.bundle git bundles."),
    ] = Path("bench/review/bundles"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing Harbor task directories."),
    ] = False,
) -> None:
    """Emit Harbor review tasks from frozen baseline JSONL (#64 W3)."""
    from tripll.bench.review_harbor import emit_harbor_review_tasks

    try:
        emitted = emit_harbor_review_tasks(
            baseline,
            dest,
            bundles_dir=bundles_dir,
            force=force,
        )
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    for path in emitted:
        typer.echo(f"emitted {path}")
    typer.echo(f"tasks: {len(emitted)}")


@bench_app.command("run")
def bench_run_cmd(
    bench_dir: Annotated[
        Path | None,
        typer.Option("--bench-dir", help="Path to bench/ (default: auto-detect)."),
    ] = None,
    graph_db: Annotated[
        Path | None,
        typer.Option("--db", help="GraphStore SQLite path for graph-brief replay."),
    ] = None,
) -> None:
    """Replay sealed tasks and emit metric deltas vs baseline."""
    from tripll.bench import run_benchmark

    result = run_benchmark(
        bench_dir=bench_dir,
        graph_db=graph_db,
    )
    typer.echo(f"tasks: {result.task_count}")
    typer.echo(f"d23_verdict: {result.d23_verdict}")
    for key in sorted(result.metrics):
        delta = result.deltas[key]
        sign = "+" if delta >= 0 else ""
        typer.echo(
            f"{key}: {result.metrics[key]:.4f} (baseline {result.baseline[key]:.4f}, {sign}{delta:.4f})"
        )


def register_review_commands(app: typer.Typer) -> None:
    """Register review and bench command groups on *app*."""

    app.add_typer(review_app, name="review")
    app.add_typer(bench_app, name="bench")
