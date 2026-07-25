"""spec-kit-wave CLI — ``uv run skw …``.

Entry points for the LangGraph pipeline:

- ``run`` — execute pipeline for a wave-file
- ``pipeline-build`` — compile wave-file → ``waves/<slug>.pipeline.json``
- ``pipeline-show`` — print compiled pipeline JSON
- ``next-step`` — emit next manual ``make`` command (Wave W6)
- ``render`` / ``agent-run`` — per-stage prompt render and headless dispatch

Exports:
    app — Typer application.
    main — console script entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from tripll.skw.driver import run_agent
from tripll.skw.git import commit_wave, resolve_worktree
from tripll.skw.logging import configure_logging, log_debug
from tripll.skw.nextstep import compute_next_step
from tripll.skw.paths import repo_root_for_kit
from tripll.skw.pipeline import PipelineBuilder, run_pipeline
from tripll.skw.pipeline_diagram import sync_pipeline_artifacts
from tripll.skw.render import (
    FRONTEND_STAGES,
    PRD_AUTHOR_STAGE,
    RENDER_STAGES,
    render_frontend_prompt,
    render_prd_author_prompt,
    render_prompt,
    render_wave_generator_prompt,
    resolve_prd_path,
)
from tripll.skw.resolve_wave import load_wave_data, wave_role
from tripll.skw.runtime import is_dryrun, is_pytest
from tripll.skw.tracing import configure_tracing, is_tracing_enabled
from tripll.skw.validate import load_skw_config

app = typer.Typer(
    no_args_is_help=True,
    help="spec-kit-wave — deterministic LangGraph wave pipeline",
)


def _kit_root() -> Path:
    return Path(__file__).resolve().parent


@app.callback()
def _global_options(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable DEBUG loguru logging (prompts, argv, subprocess lines)",
    ),
) -> None:
    """Global options applied before every subcommand."""
    kit_root = _kit_root()
    configure_logging(verbose=verbose, kit_root=kit_root)
    configure_tracing(enabled=is_tracing_enabled(kit_root=kit_root), kit_root=kit_root)


def _resolve_wave_path(wave: str) -> Path:
    path = Path(wave)
    if not path.is_file():
        typer.echo(f"Not found: {wave}", err=True)
        raise typer.Exit(code=1)
    return path.resolve()


@app.command("run")
def run_cmd(
    wave: str = typer.Option(..., "--wave", help="Path to wave markdown file"),
) -> None:
    """Run the full LangGraph pipeline for one wave-file (D5: graph is orchestrator)."""
    kit_root = _kit_root()
    wave_path = _resolve_wave_path(wave)
    result = run_pipeline(wave_path, kit_root)
    if result.get("__interrupt__"):
        typer.echo("STOP: review gate — operator approval required (resume after approve).")
        raise typer.Exit(code=3)
    raise typer.Exit(code=0)


@app.command("pipeline-build")
def pipeline_build_cmd(
    wave: str = typer.Option(..., "--wave", help="Path to wave markdown file"),
) -> None:
    """Compile wave-file to ``waves/<slug>.pipeline.{json,html}``."""
    kit_root = _kit_root()
    wave_path = _resolve_wave_path(wave)
    json_path, html_path = sync_pipeline_artifacts(wave_path, kit_root)
    typer.echo(f"wrote {json_path.relative_to(kit_root)}")
    typer.echo(f"wrote {html_path.relative_to(kit_root)}")


@app.command("pipeline-diagram")
def pipeline_diagram_cmd(
    wave: str = typer.Option(..., "--wave", help="Path to wave markdown file"),
) -> None:
    """Regenerate only the HTML pipeline diagram."""
    kit_root = _kit_root()
    wave_path = _resolve_wave_path(wave)
    _, html_path = sync_pipeline_artifacts(wave_path, kit_root)
    typer.echo(f"wrote {html_path.relative_to(kit_root)}")


@app.command("pipeline-show")
def pipeline_show_cmd(
    wave: str = typer.Option(..., "--wave", help="Path to wave markdown file"),
) -> None:
    """Print compiled pipeline JSON to stdout."""
    kit_root = _kit_root()
    wave_path = _resolve_wave_path(wave)
    builder = PipelineBuilder.from_wave_file(wave_path, kit_root)
    typer.echo(json.dumps(builder.to_json(), indent=2))


@app.command("next-step")
def next_step_cmd(
    wave: str = typer.Option(..., "--wave", help="Path to wave markdown file"),
    wave_id: str | None = typer.Option(None, "--wave-id", help="Wave id just completed"),
) -> None:
    """Emit the next manual ``make`` command (Wave W6)."""
    kit_root = _kit_root()
    hint = compute_next_step(
        wave_file=_resolve_wave_path(wave),
        kit_root=kit_root,
        wave_id=wave_id,
    )
    typer.echo(hint)


@app.command("render")
def render_cmd(
    wave: str | None = typer.Option(None, "--wave", help="Path to wave markdown file"),
    stage: str = typer.Option(..., "--stage", help="Pipeline stage to render"),
    wave_id: str | None = typer.Option(None, "--wave-id", help="Target wave id (run stage)"),
    slug: str | None = typer.Option(None, "--slug", help="Plan slug (wave-generator/front-end)"),
    title: str | None = typer.Option(None, "--title", help="Plan title (wave-generator/front-end)"),
    context: str | None = typer.Option(None, "--context", help="Operator brief file (front-end)"),
    paths: str | None = typer.Option(None, "--paths", help="Comma-separated paths (front-end)"),
    prd: str | None = typer.Option(None, "--prd", help="Target PRD path (prd-author)"),
    profile: str | None = typer.Option(None, "--profile", help="PRD profile (prd-author)"),
) -> None:
    """Render one prompt stage to stdout (no agent dispatch)."""
    kit_root = _kit_root()
    if stage not in RENDER_STAGES:
        valid = sorted(RENDER_STAGES)
        typer.echo(f"unknown stage {stage!r} (expected one of {valid})", err=True)
        raise typer.Exit(code=1)
    if stage == PRD_AUTHOR_STAGE:
        if not prd:
            typer.echo("--prd is required for prd-author", err=True)
            raise typer.Exit(code=1)
        explore_paths = [p.strip() for p in paths.split(",") if p.strip()] if paths else None
        prd_path = resolve_prd_path(prd, repo_root=repo_root_for_kit(kit_root), kit_root=kit_root)
        rendered = render_prd_author_prompt(
            kit_root,
            prd_path=prd_path,
            repo_root=repo_root_for_kit(kit_root),
            context_path=Path(context) if context else None,
            explore_paths=explore_paths,
            profile=profile,
        )
    elif stage in FRONTEND_STAGES:
        if not slug or not title:
            typer.echo(f"--slug and --title are required for {stage}", err=True)
            raise typer.Exit(code=1)
        explore_paths = [p.strip() for p in paths.split(",") if p.strip()] if paths else None
        rendered = render_frontend_prompt(
            kit_root,
            stage=stage,
            slug=slug,
            title=title,
            context_path=Path(context) if context else None,
            explore_paths=explore_paths,
        )
    elif stage == "wave-generator":
        if not slug or not title:
            typer.echo("--slug and --title are required for wave-generator", err=True)
            raise typer.Exit(code=1)
        explore_paths = [p.strip() for p in paths.split(",") if p.strip()] if paths else None
        rendered = render_wave_generator_prompt(
            kit_root,
            slug=slug,
            title=title,
            context_path=Path(context) if context else None,
            explore_paths=explore_paths,
        )
    else:
        if not wave:
            typer.echo("--wave is required for this stage", err=True)
            raise typer.Exit(code=1)
        rendered = render_prompt(
            _resolve_wave_path(wave),
            kit_root,
            stage=stage,
            wave_id=wave_id,
        )
    typer.echo(rendered, nl=not rendered.endswith("\n"))


def _git_branch_at(worktree: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _commit_after_run(kit_root: Path, wave_path: Path, wave_id: str) -> None:
    """Deterministically commit + push the wave's code to the plan branch (D9).

    Resolves the worktree that holds the wave-file ``branch`` and commits there so
    the loop never depends on the operator switching the current checkout. Skips
    cleanly (with a note) when no worktree holds the branch, so we never commit to
    an unrelated branch such as ``test-pre``.
    """
    data = load_wave_data(wave_path)
    branch = str(data.get("branch", "")).strip()
    slug = str(data.get("slug", "")).strip()
    if not branch:
        return

    repo_root = repo_root_for_kit(kit_root)
    worktree = resolve_worktree(branch, repo_root)
    if _git_branch_at(worktree) != branch:
        typer.echo(
            f"auto-commit skipped: branch {branch!r} is not checked out in any worktree "
            f"(checked from {repo_root}). Create one with "
            f"`git worktree add .worktrees/{slug} {branch}` or check out {branch}.",
            err=True,
        )
        return

    title = ""
    waves = data.get("waves", [])
    if isinstance(waves, list):
        for wave in waves:
            if isinstance(wave, dict) and wave.get("id") == wave_id:
                title = str(wave.get("title", ""))
                break

    cfg = load_skw_config(kit_root)
    log_debug(f"auto-commit wave {wave_id} on {branch} in {worktree}")
    commit_wave(
        wave_id=wave_id,
        title=title,
        slug=slug,
        role=wave_role(data, wave_id),
        branch=branch,
        worktree=worktree,
        git_config=cfg,
    )


@app.command("agent-run")
def agent_run_cmd(
    wave: str = typer.Option(..., "--wave", help="Path to wave markdown file"),
    stage: str = typer.Option("run", "--stage", help="Pipeline stage to dispatch"),
    wave_id: str | None = typer.Option(None, "--wave-id", help="Target wave id (run stage)"),
) -> None:
    """Render one stage, dispatch the headless agent, then auto-commit the wave (D9)."""
    kit_root = _kit_root()
    wave_path = _resolve_wave_path(wave)
    rc = run_agent(wave_file=wave_path, kit_root=kit_root, stage=stage, wave_id=wave_id)
    if rc == 0 and stage == "run" and wave_id and not is_dryrun() and not is_pytest():
        _commit_after_run(kit_root, wave_path, wave_id)
    raise typer.Exit(code=rc)


def main() -> None:
    """Console script entry for ``uv run skw``."""
    app()


if __name__ == "__main__":
    main()
