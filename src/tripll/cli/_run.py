"""tripll.cli._run — run / inject / reconcile-graph CLI commands (issue #16 seam).

Exports:
    register_run_commands — attach run subcommands to the root Typer app.
    rewrite_run_inject_argv — map ``run inject`` argv to hidden subcommands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from tripll.cli._shared import (
    RunsRootOpt,
    _backend_options,
    _cost_budget_usd,
    _engine_for,
    _finalize_run_result,
    _resolve_runs_root,
)
from tripll.pipeline import PlanPathValidationError, make_run_id
from tripll.repo_root import resolve_repo_root


def _run_dry_run(
    input_path: Path,
    *,
    backend: str,
    integrate: bool,
    deliver: bool = False,
    model: str | None = None,
    agent: str | None = None,
) -> None:
    """Print the planned run-id, backend availability, and a sample dispatch argv.

    Args:
        input_path (Path): Input directory (parallel-wave set or plain folder).
        backend (str): Backend name.
        integrate (bool): Whether ``--integrate`` was requested.
        deliver (bool): Whether ``--deliver`` was requested (requires integrate).
    """
    from tripll.adapters import get_adapter
    from tripll.brief import render_json_brief
    from tripll.parse import build_graph_from_dir
    from tripll.worktrees import branch_name

    run_id = make_run_id(input_path.name)
    typer.echo(f"[dry-run] Would claim : {input_path}")
    typer.echo(f"[dry-run] Run-id      : {run_id}")
    typer.echo(f"[dry-run] Backend     : {backend}")
    typer.echo(f"[dry-run] Integrate   : {integrate}")
    typer.echo(f"[dry-run] Deliver     : {deliver}")

    adapter = get_adapter(
        backend, options=_backend_options(backend=backend, model=model, agent=agent)[1]
    )
    caps = adapter.capabilities()
    typer.echo(f"[dry-run] Available   : {caps.available} ({caps.detail})")

    graph = build_graph_from_dir(input_path, run_id=run_id)
    if graph.pre0_gates:
        from tripll.plan.human_gates import (
            evaluate_ci_billing_canary,
            pipeline_config_for_graph,
            resolve_human_gate_mode,
            resolve_pre0_gate,
        )

        pipeline = pipeline_config_for_graph(graph, resolve_repo_root())
        mode = resolve_human_gate_mode(pipeline)
        canary = evaluate_ci_billing_canary()
        outcome = resolve_pre0_gate(mode=mode, auto_acceptable=True, canary=canary)
        typer.echo(f"[dry-run] Pre-0 gates  : {len(graph.pre0_gates)}")
        typer.echo(f"[dry-run] Human gates  : {mode} → {outcome.value}")
        typer.echo(f"[dry-run] CI canary     : {canary.detail}")

    sample = next((n for n in graph.nodes.values() if not n.is_review_gate), None)
    if sample is None:
        typer.echo("[dry-run] No dispatchable (non-gate) node found.")
        return

    branch = branch_name(run_id, sample.plan_id, sample.wave_id)
    worktree = (
        Path("wave-orchestrator")
        / "runs"
        / "processing"
        / run_id
        / "worktrees"
        / (f"{sample.plan_id}-{sample.wave_id}")
    )
    brief = render_json_brief(sample, run_id=run_id, branch=branch, worktree_path=str(worktree))
    argv = adapter.build_argv(brief, worktree)
    typer.echo(f"[dry-run] Sample node : {sample.node_id}")
    typer.echo("[dry-run] Exec argv   :")
    typer.echo("  " + " ".join(repr(a) if " " in a else a for a in argv))

    if integrate:
        from tripll.integrate import plan_integration, render_dry_run

        plan = plan_integration(graph, run_id=run_id)
        for line in render_dry_run(plan):
            typer.echo(line)
        if deliver:
            from tripll.loops.l1_pr import render_deliver_dry_run

            for line in render_deliver_dry_run(
                run_id=run_id,
                integration_branch=plan.integration_branch,
            ):
                typer.echo(line)

    trace_env = os.environ.get("TRIPLL_TRACE", "1").strip().lower()
    if trace_env not in {"0", "false", "no", "off"}:
        from tripll.obs import configure_observability, get_tracing_config
        from tripll.plan.providers import plan_from_text
        from tripll.tracing.spans import close_run_tracing, init_run_tracing, trace_span

        plan_text = ""
        if input_path.is_file() and input_path.suffix == ".md":
            plan_text = input_path.read_text(encoding="utf-8")
        elif input_path.is_dir():
            for md in sorted(input_path.glob("*.md")):
                plan_text = md.read_text(encoding="utf-8")
                break
        plan_dict = plan_from_text(plan_text) if plan_text else {}
        configure_observability(plan=plan_dict)
        rr = _resolve_runs_root(None)
        run_dir = rr.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        init_run_tracing(run_dir, get_tracing_config(), run_id=run_id)
        with trace_span("tripll.run", run_id=run_id, dry_run=True):
            pass
        close_run_tracing()
        typer.echo(f"[dry-run] Trace sinks : {run_dir / 'traces'}")


# ---------------------------------------------------------------------------
# run  — start or dry-run a wave-orchestrator pipeline
# ---------------------------------------------------------------------------


def rewrite_run_inject_argv(argv: list[str]) -> list[str]:
    """Map ``tripll run inject …`` / ``reconcile-graph`` to hidden subcommands."""
    if len(argv) >= 3 and argv[1] == "run" and argv[2] == "inject":
        return [argv[0], "run-inject", *argv[3:]]
    if len(argv) >= 4 and argv[1] == "run" and argv[2] == "reconcile-graph":
        return [argv[0], "run-reconcile-graph", *argv[3:]]
    return argv


def run(
    input_path: Annotated[
        Path | None,
        typer.Argument(
            help="Path to the input directory (parallel-wave set or plain wave folder). "
            "Defaults to first item in input/."
        ),
    ] = None,
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            "-b",
            help="Agent backend: claude_code (default), cursor_local, cursor_cloud.",
        ),
    ] = "claude_code",
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Alias for --backend (e.g. cursor_local, claude_code).",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Provider model id (e.g. auto, composer-2.5)."),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            "-a",
            help="Claude Code sub-agent slug (default wave-plan-executor).",
        ),
    ] = None,
    integrate: Annotated[
        bool,
        typer.Option(
            "--integrate/--no-integrate",
            help="Enable autonomous per-batch merge + make ci-resume + commit (default OFF).",
        ),
    ] = False,
    deliver: Annotated[
        bool,
        typer.Option(
            "--deliver/--no-deliver",
            help="After --integrate, push integration branch and open PR (default OFF).",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the planned run graph without executing."),
    ] = False,
    wait_for_hitl: Annotated[
        bool,
        typer.Option(
            "--wait-for-hitl",
            help="Block until HITL gate responses are submitted and approved, then auto-resume.",
        ),
    ] = False,
    role_dispatch: Annotated[
        bool | None,
        typer.Option(
            "--role-dispatch/--no-role-dispatch",
            help="Enable per-role agent dispatch (test-author→test-creator, impl→wave-runner).",
        ),
    ] = None,
    grep_brief: Annotated[
        bool | None,
        typer.Option(
            "--grep-brief/--graph-brief",
            help="Force legacy grep brief (default: graph-packed when kg extra installed).",
        ),
    ] = None,
    runs_root: RunsRootOpt = None,
) -> None:
    """Start (or dry-run) the wave-orchestrator pipeline on an input directory.

    Parses the input (Mode A parallel-wave set or Mode B plain folder), builds
    the run graph, and dispatches waves via the configured agent backend.
    Supports Pre-0 human gates, quota/cost pauses, and orchestrator serial mode.
    """
    rr = _resolve_runs_root(runs_root)
    backend = provider or backend

    # Resolve input
    if input_path is None:
        pending = rr.list_input()
        if not pending:
            typer.echo(
                "No input directories found. Use `tripll init` then drop a set into input/.",
                err=True,
            )
            raise typer.Exit(1)
        input_path = pending[0]
        logger.debug("run: auto-selected input {}", input_path)

    if not input_path.exists():
        typer.echo(f"Input path not found: {input_path}", err=True)
        raise typer.Exit(1)

    if deliver and not integrate:
        typer.echo(
            "--deliver requires --integrate (local integration before push/open PR).", err=True
        )
        raise typer.Exit(1)

    if dry_run:
        _run_dry_run(
            input_path,
            backend=backend,
            integrate=integrate,
            deliver=deliver,
            model=model,
            agent=agent,
        )
        return

    import asyncio

    from tripll.adapters import get_adapter

    name, opts = _backend_options(backend=backend, model=model, agent=agent)
    adapter = get_adapter(name, options=opts)
    caps = adapter.capabilities()
    if not caps.available:
        typer.echo(f"Backend unavailable: {caps.detail}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Repo: {resolve_repo_root()}")
    typer.echo(f"Backend: {name} ({caps.detail})")
    if model:
        typer.echo(f"Model: {model}")
    if agent:
        typer.echo(f"Agent: {agent}")
    engine = _engine_for(
        rr,
        backend=backend,
        model=model,
        agent=agent,
        role_dispatch=role_dispatch,
        grep_brief=grep_brief,
    )
    try:
        result = asyncio.run(engine.start(input_path))
    except PlanPathValidationError as exc:
        for line in exc.errors:
            typer.echo(line, err=True)
        raise typer.Exit(1) from exc
    _finalize_run_result(
        rr,
        result,
        integrate=integrate,
        deliver=deliver,
        wait_for_hitl=wait_for_hitl,
        engine=engine,
    )


def run_inject(
    run_id: Annotated[str, typer.Argument(help="Run-id in processing/ (must be paused).")],
    after: Annotated[
        str,
        typer.Option("--after", help="Insert hotfix after this wave (node id or wave label)."),
    ],
    brief: Annotated[
        str,
        typer.Option("--brief", help="Operator brief describing the hotfix."),
    ] = "",
    paths: Annotated[
        list[str] | None,
        typer.Option("--paths", help="Owned paths the hotfix may edit (repeatable)."),
    ] = None,
    verify_target: Annotated[
        str | None,
        typer.Option(
            "--verify-target",
            help="Override post-dispatch verify make target (default: make ci-affected).",
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="Provider override for hotfix dispatch."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override for hotfix dispatch."),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option("--agent", "-a", help="Agent slug override for hotfix dispatch."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate and write inject plan only; no ledger write."),
    ] = False,
    force_after_drain: Annotated[
        bool,
        typer.Option(
            "--force-after-drain",
            help="Allow inject when pause marker present but waves still in-flight.",
        ),
    ] = False,
    runs_root: RunsRootOpt = None,
) -> None:
    """Inject a one-shot hotfix into a paused run (L2-W5a).

    Requires ``pause-requested.md`` and a completed ``--after`` wave. Resume the
    run afterward to dispatch via the normal engine path.
    """
    from tripll.inject import InjectError, apply_hotfix_inject

    if not after.strip():
        typer.echo("--after is required", err=True)
        raise typer.Exit(1)
    if not brief.strip():
        typer.echo("--brief is required", err=True)
        raise typer.Exit(1)
    if not paths:
        typer.echo("--paths must declare at least one owned path", err=True)
        raise typer.Exit(1)

    rr = _resolve_runs_root(runs_root)
    if rr.find_run_dir(run_id) is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    if (rr.processing_dir / run_id).is_dir() is False and rr.find_run_dir(run_id) is not None:
        loc = rr.find_run_dir(run_id)
        if loc is not None and loc.parent == rr.processed_dir:
            typer.echo(f"Run already completed (processed/): {run_id}", err=True)
            raise typer.Exit(1)

    verify_targets = [verify_target or "make ci-affected"]
    try:
        task = apply_hotfix_inject(
            rr,
            run_id,
            brief=brief,
            owned_paths=list(paths),
            after=after,
            verify_targets=verify_targets,
            provider=provider,
            model=model,
            agent=agent,
            cost_budget_usd=_cost_budget_usd(),
            force_after_drain=force_after_drain,
            dry_run=dry_run,
            repo_root=resolve_repo_root(),
        )
    except InjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.exit_code) from exc

    if dry_run:
        typer.echo(f"[dry-run] Hotfix plan valid — node {task.node_id}")
        typer.echo(
            f"[dry-run] Plan artefact: {rr.injects_dir(run_id) / (task.task_id + '.plan.json')}"
        )
        return

    typer.echo(f"Inject applied: {task.node_id} (task {task.task_id})")
    typer.echo(f"Audit: {rr.injects_dir(run_id) / (task.task_id + '.json')}")
    typer.echo(f"Resume with: tripll resume {run_id}")


def run_reconcile_graph(
    run_id: Annotated[str, typer.Argument(help="Run-id in processing/ (must be paused).")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate only; no ledger or graph.json write."),
    ] = False,
    force_after_drain: Annotated[
        bool,
        typer.Option(
            "--force-after-drain",
            help="Allow reconcile when pause marker present but waves still in-flight.",
        ),
    ] = False,
    runs_root: RunsRootOpt = None,
) -> None:
    """Reconcile parsed plan files with ledger waves after a plan edit (L2-W5b).

    Requires ``pause-requested.md`` and no in-flight waves. Resume also reconciles
    automatically before dispatch.
    """
    from tripll.inject import InjectError, reconcile_run_graph
    from tripll.ledger import open_ledger

    rr = _resolve_runs_root(runs_root)
    if rr.find_run_dir(run_id) is None:
        typer.echo(f"Run not found: {run_id}", err=True)
        raise typer.Exit(1)
    loc = rr.find_run_dir(run_id)
    if loc is not None and loc.parent == rr.processed_dir:
        typer.echo(f"Run already completed (processed/): {run_id}", err=True)
        raise typer.Exit(1)

    try:
        with open_ledger(rr.ledger_path(run_id)) as lc:
            result = reconcile_run_graph(
                rr,
                run_id,
                lc=lc,
                dry_run=dry_run,
                require_pause=True,
                force_after_drain=force_after_drain,
                source="cli",
            )
    except InjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.exit_code) from exc

    if dry_run:
        typer.echo(
            f"[dry-run] Reconcile valid — would insert {list(result.inserted)} "
            f"orphan {list(result.orphans)}"
        )
        return

    typer.echo(f"Reconcile applied: inserted {list(result.inserted)}")
    if result.orphans:
        typer.echo(f"Orphan ledger rows (kept): {list(result.orphans)}")
    typer.echo(f"Resume with: tripll resume {run_id}")


def register_run_commands(app: typer.Typer) -> None:
    """Register run, run-inject, and run-reconcile-graph on *app*."""

    app.command()(run)
    app.command("run-inject", hidden=True)(run_inject)
    app.command("run-reconcile-graph", hidden=True)(run_reconcile_graph)


# Back-compat alias for tests importing from tripll.cli
_rewrite_run_inject_argv = rewrite_run_inject_argv
