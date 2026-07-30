"""tripll.cli._docs — serve, skw mount, spec/prd/changelog, doc-score (issue #16 seam).

Exports:
    register_docs_commands — attach docs and control-plane commands to *app*.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from tripll.cli._shared import (
    RunsRootOpt,
    _resolve_runs_root,
)
from tripll.repo_root import resolve_repo_root
from tripll.skw.cli import app as skw_legacy_app


def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind host (default: localhost)."),
    ] = "localhost",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Bind port (default: 8765)."),
    ] = 8765,
    runs_root: RunsRootOpt = None,
) -> None:
    """Start the FastAPI control-plane server (W4).

    Launches uvicorn on the ``tripll.api`` FastAPI app.  Requires the
    ``api`` optional-dependency extra (``uv sync --extra api``).

    Auth: set ``TRIPLL_API_TOKEN`` to require a Bearer token on all
    requests.  When unset, the server is accessible without auth (safe when
    bound to localhost, which is the default).

    Args:
        host (str): Bind host.  Default is ``localhost`` to avoid accidental
            exposure on networked interfaces.
        port (int): Bind port.  Default is 8765.
        runs_root (Path | None): Override runs root.
    """
    try:
        import uvicorn
    except ImportError as exc:
        typer.echo(
            "uvicorn not installed. Run: uv sync --extra api",
            err=True,
        )
        raise typer.Exit(1) from exc

    from tripll.api import create_app

    rr = _resolve_runs_root(runs_root)
    rr.init()  # ensure folders exist

    # Seed default profiles on first serve.
    from tripll.profiles import control_plane_db_path, open_profile_store, seed_default_profiles

    db_path = control_plane_db_path(rr.root)
    with open_profile_store(db_path) as store:
        created = seed_default_profiles(store)
        if created:
            typer.echo(f"Seeded {len(created)} default profile(s): {', '.join(created)}")

    fastapi_app = create_app(runs_root=rr.root)
    typer.echo(f"tripll control plane → http://{host}:{port}/")
    typer.echo(f"  Runs root : {rr.root}")
    typer.echo(f"  API docs  : http://{host}:{port}/docs")
    token = os.environ.get("TRIPLL_API_TOKEN", "")
    if token:
        typer.echo("  Auth      : Bearer token required (TRIPLL_API_TOKEN set)")
    else:
        typer.echo("  Auth      : NONE (dev mode — set TRIPLL_API_TOKEN for production)")
    uvicorn.run(fastapi_app, host=host, port=port)


def _skw_kit_root() -> Path:
    from tripll.skw.paths import kit_root

    return kit_root()


def _docs_repo_root(repo_root: Path | None) -> Path:
    return (repo_root or resolve_repo_root()).resolve()


def _run_docs(kind: str, directory: Path, *, repo_root: Path | None, mode: str) -> None:
    from tripll.skw.doc_folder import run_docs_command

    result = run_docs_command(
        mode,
        kind=kind,
        directory=directory.resolve(),
        repo_root=_docs_repo_root(repo_root),
        kit_root=_skw_kit_root(),
    )
    for file_result in result.files:
        for err in file_result.errors:
            typer.echo(err, err=True)
        for warn in file_result.warnings:
            typer.echo(f"warning: {warn}", err=True)
    if result.exit_code != 0:
        raise typer.Exit(result.exit_code)


spec_app = typer.Typer(name="spec", help="Spec folder validate and score.", no_args_is_help=True)
prd_app = typer.Typer(name="prd", help="PRD folder validate and score.", no_args_is_help=True)
changelog_app = typer.Typer(
    name="changelog",
    help="CHANGELOG.md structural and diff gates.",
    no_args_is_help=True,
)


@spec_app.command("validate")
def spec_validate_cmd(
    directory: Annotated[Path, typer.Argument(help="Specs directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Validate every spec in a directory."""
    _run_docs("spec", directory, repo_root=repo_root, mode="validate")


@spec_app.command("score")
def spec_score_cmd(
    directory: Annotated[Path, typer.Argument(help="Specs directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Score every spec in a directory."""
    _run_docs("spec", directory, repo_root=repo_root, mode="score")


@prd_app.command("validate")
def prd_validate_cmd(
    directory: Annotated[Path, typer.Argument(help="PRD directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Validate every PRD in a directory."""
    _run_docs("prd", directory, repo_root=repo_root, mode="validate")


@prd_app.command("score")
def prd_score_cmd(
    directory: Annotated[Path, typer.Argument(help="PRD directory.")],
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
) -> None:
    """Score every PRD in a directory."""
    _run_docs("prd", directory, repo_root=repo_root, mode="score")


def doc_score_cmd(
    kind: Annotated[str, typer.Option("--kind", help="Doc kind: spec or prd.")] = "spec",
    directory: Annotated[Path, typer.Option("--dir", help="Folder of markdown docs.")] = Path(
        "docs"
    ),
    repo_root: Annotated[
        Path | None,
        typer.Option("--repo-root", help="Target repository root."),
    ] = None,
) -> None:
    """Score every doc in a folder for the given kind."""
    _run_docs(kind, directory, repo_root=repo_root, mode="score")


@changelog_app.command("check")
def changelog_check_cmd(
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
    base: Annotated[str, typer.Option("--base", help="Diff base ref.")] = "origin/main",
    changelog: Annotated[Path | None, typer.Option("--changelog")] = None,
) -> None:
    """Run deterministic CHANGELOG.md structural + diff gate."""
    from tripll.skw.changelog_validate import validate_changelog

    root = _docs_repo_root(repo_root)
    changelog_path = (changelog or root / "CHANGELOG.md").resolve()
    errors, warnings = validate_changelog(root, base, changelog_path=changelog_path)
    for warn in warnings:
        typer.echo(f"warning: {warn}", err=True)
    if errors:
        for err in errors:
            typer.echo(err, err=True)
        raise typer.Exit(1)
    typer.echo(f"OK — {changelog_path}")


@changelog_app.command("eval")
def changelog_eval_cmd(
    repo_root: Annotated[Path | None, typer.Option("--repo-root")] = None,
    base: Annotated[str, typer.Option("--base")] = "origin/main",
) -> None:
    """Advisory LLM double-score for Unreleased entries (not used in CI)."""
    from tripll.skw.changelog_eval import main as changelog_eval_main

    root = _docs_repo_root(repo_root)
    raise typer.Exit(changelog_eval_main(["--repo", str(root), "--base", base, "--json"]))


def register_docs_commands(app: typer.Typer) -> None:
    """Register serve, skw, spec/prd/changelog groups, and doc-score on *app*."""

    app.command()(serve)
    app.add_typer(skw_legacy_app, name="skw")
    app.add_typer(spec_app, name="spec")
    app.add_typer(prd_app, name="prd")
    app.add_typer(changelog_app, name="changelog")
    app.command("doc-score")(doc_score_cmd)
