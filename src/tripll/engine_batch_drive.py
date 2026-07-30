"""Batch wave drive seam extracted from :mod:`tripll.engine`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from tripll.adapters.quota import quota_message
from tripll.engine_exits import (
    _COST_MARKER,
    _QUOTA_MARKER,
)
from tripll.engine_human_gates import complete_human_gate_waves
from tripll.engine_orchestrator import (
    _REVIEW_GATE_MARKER,
    _configure_orchestrator,
    _drive_orchestrator_serial,
)
from tripll.engine_scheduling import nodes_for_batch, ready_nodes, select_concurrent_set
from tripll.hitl import GateKind, write_form_for_run
from tripll.ledger import (
    LedgerConnection,
    RunState,
    append_event,
    get_run_cost,
    get_wave,
    list_waves,
    open_ledger,
    transition_run,
    transition_wave,
)
from tripll.parse import build_graph_from_dir
from tripll.report import write_report
from tripll.worktrees import stage_dispatch_context

if TYPE_CHECKING:
    from tripll.engine import Engine, NodeResult, RunResult
    from tripll.graph import RunGraph, WaveNode


def _write_pre0_sheet(engine: Engine, run_id: str, graph: RunGraph) -> None:
    """Write ``pre0-decisions.md`` checklist for operator Pre-0 approval."""
    lines = [f"# Pre-0 decisions — {run_id}\n", "\n"]
    lines.append("Resolve each gate, then run `tripll approve " + run_id + "`.\n\n")
    for i, gate in enumerate(graph.pre0_gates, 1):
        lines.append(f"{i}. [ ] {gate}\n")
    (engine.runs_root.run_dir(run_id) / "pre0-decisions.md").write_text("".join(lines))


def _write_escalation(
    engine: Engine, run_id: str, blocked: list[str], results: dict[str, NodeResult]
) -> None:
    """Write ``escalation.md`` listing blocked waves and failure evidence."""
    lines = [
        f"# Escalation — {run_id}\n",
        "\n",
        f"Blocked waves ({engine.max_attempts} attempts exhausted):\n\n",
    ]
    for node_id in blocked:
        res = results[node_id]
        lines.append(f"- {node_id} ({res.attempts} attempts): {res.evidence}\n")
    (engine.runs_root.run_dir(run_id) / "escalation.md").write_text("".join(lines))


def _write_quota_pause(
    engine: Engine, run_id: str, node_id: str, evidence: str, backend: str
) -> None:
    """Write ``quota-paused.md`` with provider quota/session-limit guidance."""
    msg = quota_message(evidence)
    lines = [
        f"# Quota pause — {run_id}\n\n",
        f"Provider quota or session limit hit during `{node_id}`.\n\n",
        f"**Backend:** `{backend}`\n\n",
        f"**Message:** {msg}\n\n",
        "Resume with another provider/model when quota resets, e.g.:\n\n",
        "```bash\n",
        f"make continue-run RUN={run_id} PROVIDER=cursor_local MODEL=auto\n",
        "```\n",
    ]
    (engine.runs_root.run_dir(run_id) / _QUOTA_MARKER).write_text("".join(lines))


def _write_cost_pause(engine: Engine, run_id: str, spent_usd: float) -> None:
    """Write ``cost-budget-paused.md`` when run cost exceeds the budget."""
    lines = [
        f"# Cost budget pause — {run_id}\n\n",
        f"Run cost **${spent_usd:.4f}** reached the configured budget "
        f"(**${engine.cost_budget_usd:.2f}**).\n\n",
        "Resume after raising the budget, e.g.:\n\n",
        "```bash\n",
        f"TRIPLL_COST_BUDGET_USD=50 make resume-run RUN={run_id}\n",
        "```\n",
    ]
    (engine.runs_root.run_dir(run_id) / _COST_MARKER).write_text("".join(lines))


def _write_review_gate_pause(engine: Engine, run_id: str, wave_id: str, gate_label: str) -> None:
    """Write review-gate pause marker and HITL form for operator review."""
    lines = [
        f"# Review gate pause — {run_id}\n\n",
        f"Wave **{wave_id}** completed — **AWAITING REVIEW** ({gate_label}).\n\n",
        "Complete the HITL form in the dashboard, then approve and resume:\n\n",
        "```bash\n",
        f"make approve-run RUN={run_id}\n",
        f"make resume-run RUN={run_id}\n",
        "```\n",
    ]
    run_dir = engine.runs_root.run_dir(run_id)
    (run_dir / _REVIEW_GATE_MARKER).write_text("".join(lines))
    graph = build_graph_from_dir(run_dir, run_id=run_id)
    write_form_for_run(
        run_dir,
        graph,
        gate_kind=GateKind.REVIEW_GATE,
        wave_id=wave_id,
        gate_label=gate_label,
    )


async def drive_wave_batches(
    engine: Engine,
    run_id: str,
    graph: RunGraph,
    *,
    run_bag: dict[str, Any] | None = None,
    record_validate_snapshot: bool = True,
    finalize_run: bool = True,
) -> RunResult:
    """Dispatch all wave batches — shared Engine seam for linear and outer-loop paths.

    Args:
        run_id (str): Run identifier.
        graph (RunGraph): Parsed execution graph.
        run_bag (dict[str, Any] | None): Optional trace span bag from ``_drive``.
        record_validate_snapshot (bool): Write validate ``loop_snapshot`` when True.
        finalize_run (bool): When True, move the run dir to ``processed/`` or
            ``failed/`` after batch dispatch. Outer-loop ``waves`` passes False
            so post-wave nodes can run in ``processing/``.

    Returns:
        RunResult: Terminal or paused outcome after batch dispatch.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(Engine.drive_wave_batches)
        True
    """
    from tripll.engine import RunResult
    from tripll.loops import graph_available

    done: set[str] = set()
    blocked: list[str] = []
    results: dict[str, NodeResult] = {}

    with open_ledger(engine.runs_root.ledger_path(run_id)) as lc:
        await _prepare_run_ledger(
            engine,
            lc,
            run_id,
            graph,
            done,
            blocked,
            results,
            record_validate_snapshot=record_validate_snapshot and graph_available(),
        )

        logs_dir = engine.runs_root.logs_dir(run_id)
        logger.info(
            "engine: {} dispatching waves — logs in {}",
            run_id,
            logs_dir,
        )

        for batch in graph.batches:
            if batch.is_human_gate:
                continue
            logger.info("engine: {} batch {} — lanes {}", run_id, batch.batch_id, batch.lanes)
            batch_nodes = nodes_for_batch(graph, batch)

            pause_result = await _drain_batch(
                engine, lc, run_id, graph, batch_nodes, done, blocked, results
            )
            if pause_result is not None:
                if run_bag is not None:
                    run_bag["exit_id"] = pause_result.state
                return pause_result

        state: RunState = "failed" if blocked else "done"
        if blocked:
            _write_escalation(engine, run_id, blocked, results)
        else:
            engine._fire_goal_met_exit(
                lc,
                run_id,
                ci_green=True,
                outcome_satisfied=True,
            )
        transition_run(lc, run_id, state)

    engine._sync_report(run_id, graph, partial_results=results)

    if blocked:
        if finalize_run:
            engine.runs_root.fail_run(run_id)
        if run_bag is not None:
            run_bag["exit_id"] = "failed"
            run_bag["waves_done"] = len(done)
        return RunResult(run_id=run_id, state="failed", nodes=results)
    if finalize_run:
        engine.runs_root.complete_run(run_id)
    if run_bag is not None:
        run_bag["exit_id"] = "done"
        run_bag["waves_done"] = len(done)
    return RunResult(run_id=run_id, state="done", nodes=results)


async def _prepare_run_ledger(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    done: set[str],
    blocked: list[str],
    results: dict[str, NodeResult],
    *,
    record_validate_snapshot: bool,
) -> None:
    """Startup reconciliation, resume hydration, and human-gate completion."""
    from tripll.engine import NodeResult
    from tripll.loops.l1_outer import record_loop_snapshot

    for w in list_waves(lc, run_id):
        if w.state in ("running", "dispatched", "verifying"):
            transition_wave(lc, run_id, w.node_id, "queued")
            append_event(
                lc,
                run_id=run_id,
                node_id=w.node_id,
                phase="recovery",
                last_action=("startup reconciliation: no live dispatch for stale wave"),
            )

    transition_run(lc, run_id, "active")
    engine._init_run_wall_clock(graph)

    if record_validate_snapshot:
        record_loop_snapshot(
            lc,
            run_id=run_id,
            step="validate",
            history=[],
            next_node="waves",
            extra={"thread_id": run_id},
        )

    for w in list_waves(lc, run_id):
        if w.state == "done":
            done.add(w.node_id)
            results[w.node_id] = NodeResult(w.node_id, "done", w.attempt_count)
        elif w.state == "blocked":
            blocked.append(w.node_id)
            results[w.node_id] = NodeResult(
                w.node_id, "blocked", w.attempt_count, "already blocked on resume"
            )
    if done:
        logger.info("engine: {} resuming — {} waves already done", run_id, len(done))
    if blocked:
        logger.info("engine: {} resuming — {} waves already blocked", run_id, len(blocked))
    if engine._is_approved(run_id):
        complete_human_gate_waves(
            lc,
            run_id,
            graph,
            done=done,
            blocked=blocked,
            results=results,
        )
    engine._sync_report(run_id, graph, partial_results=results)

    engine._role_dispatch_effective = engine._resolve_role_dispatch(graph)
    if engine._pools is None:
        engine._init_provider_fabric(graph)


async def _drain_batch(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    batch_nodes: list[WaveNode],
    done: set[str],
    blocked: list[str],
    results: dict[str, NodeResult],
) -> RunResult | None:
    """Drain *batch_nodes* using repeated concurrent rounds until empty.

    Each round:

    1. Compute ``ready_nodes(undrained, done)`` — nodes whose deps are all
       satisfied and that are not yet done/blocked.
    2. If nothing is ready but undrained nodes remain → dependency deadlock.
       The undrained nodes are marked blocked and escalated.
    3. Otherwise select the maximal pairwise-disjoint subset with
       ``select_concurrent_set`` and dispatch them concurrently under
       ``_sem``.
    4. If any node returns ``quota_paused`` or ``cost_paused``, let the
       siblings finish (they were already awaited via ``gather``), then
       pause the run and return the appropriate ``RunResult``.
    5. Repeat until all batch nodes are done or blocked.

    Args:
        lc (LedgerConnection): Open ledger connection (shared across rounds).
        run_id (str): Run identifier.
        graph (RunGraph): Execution graph.
        batch_nodes (list[WaveNode]): All nodes in the current batch.
        done (set[str]): node_ids already completed (mutated in-place).
        blocked (list[str]): node_ids already blocked (mutated in-place).
        results (dict[str, NodeResult]): Accumulated results (mutated in-place).

    Returns:
        RunResult | None: A paused ``RunResult`` when a pause is triggered;
        ``None`` when the batch drained cleanly (caller continues).

    Examples:
        >>> _drain_batch.__name__
        '_drain_batch'
    """
    from tripll.engine import NodeResult, RunResult

    undrained = [n for n in batch_nodes if n.node_id not in done and n.node_id not in blocked]

    while undrained:
        # Nodes whose deps are satisfied — safe to dispatch.
        candidates = ready_nodes(undrained, done)

        if not candidates:
            # Dependency deadlock: undrained nodes exist but none are ready.
            # This should not happen in a valid graph, but guard against it.
            deadlocked = [n.node_id for n in undrained]
            reason = (
                f"dependency deadlock — {len(deadlocked)} node(s) undrained but "
                f"none are ready (done={sorted(done)!r}, "
                f"blocked={sorted(blocked)!r}): {deadlocked}"
            )
            logger.error("engine: {} {}", run_id, reason)
            for node in undrained:
                blocked.append(node.node_id)
                results[node.node_id] = NodeResult(node.node_id, "blocked", 0, reason)
                async with engine._ledger_lock:
                    transition_wave(lc, run_id, node.node_id, "blocked")
            engine._sync_report(run_id, graph, partial_results=results)
            return None  # outer loop will write escalation

        # Pause-marker check: honour API pause before dispatching new waves.
        # In-flight waves are NOT killed -- they run to completion.
        pre_exit = engine._scan_pre_dispatch_exits(lc, run_id)
        if pre_exit == 8:
            logger.warning("engine: {} external_event exit fired — abandoning run", run_id)
            async with engine._ledger_lock:
                transition_run(lc, run_id, "failed")
            engine._sync_report(run_id, graph, partial_results=results)
            return RunResult(run_id=run_id, state="failed", nodes=results)
        if pre_exit == 4:
            logger.warning("engine: {} wall_clock exit fired — pausing run", run_id)
            async with engine._ledger_lock:
                transition_run(lc, run_id, "paused")
            engine._sync_report(run_id, graph, partial_results=results)
            return RunResult(run_id=run_id, state="paused", nodes=results)
        if pre_exit == 6 or engine._pause_requested(run_id):
            logger.info(
                "engine: {} pause-requested marker found -- pausing before next dispatch",
                run_id,
            )
            async with engine._ledger_lock:
                transition_run(lc, run_id, "paused")
            engine._sync_report(run_id, graph, partial_results=results)
            return RunResult(run_id=run_id, state="paused", nodes=results)

        # Greedy maximal pairwise-disjoint subset.
        concurrent = select_concurrent_set(candidates)
        logger.info(
            "engine: {} dispatching {} node(s) concurrently: {}",
            run_id,
            len(concurrent),
            [n.node_id for n in concurrent],
        )
        engine._sync_report(run_id, graph, partial_results=results)

        # Run the selected nodes under the semaphore and gather results.
        node_results = await _run_concurrent_set(engine, lc, run_id, graph, concurrent)

        # Integrate results.
        pause_quota: NodeResult | None = None
        pause_cost: NodeResult | None = None
        for res in node_results:
            results[res.node_id] = res
            if res.state == "done":
                done.add(res.node_id)
            elif res.state == "quota_paused":
                if pause_quota is None:
                    pause_quota = res
            elif res.state == "cost_paused":
                if pause_cost is None:
                    pause_cost = res
            else:
                blocked.append(res.node_id)

        engine._sync_report(run_id, graph, partial_results=results)

        # Handle pauses: siblings already finished (gather awaited them all).
        if pause_quota is not None:
            _write_quota_pause(
                engine, run_id, pause_quota.node_id, pause_quota.evidence, engine.adapter.name
            )
            async with engine._ledger_lock:
                transition_run(lc, run_id, "paused")
            engine._sync_report(run_id, graph, partial_results=results)
            logger.warning(
                "engine: {} paused — provider quota on {} ({})",
                run_id,
                pause_quota.node_id,
                pause_quota.evidence[:120],
            )
            return RunResult(
                run_id=run_id,
                state="paused",
                nodes=results,
                quota_pending=True,
            )

        if pause_cost is not None:
            async with engine._ledger_lock:
                engine._evaluate_engine_exit(3, lc, run_id)
                _write_cost_pause(engine, run_id, get_run_cost(lc, run_id))
                transition_run(lc, run_id, "paused")
            engine._sync_report(run_id, graph, partial_results=results)
            logger.warning(
                "engine: {} paused — cost budget reached on {}",
                run_id,
                pause_cost.node_id,
            )
            return RunResult(
                run_id=run_id,
                state="paused",
                nodes=results,
                cost_pending=True,
            )

        # Recompute undrained for next round.
        undrained = [n for n in batch_nodes if n.node_id not in done and n.node_id not in blocked]

    return None


async def _run_concurrent_set(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    nodes: list[WaveNode],
) -> list[NodeResult]:
    """Dispatch *nodes* concurrently under ``_sem`` and return all results.

    Each node runs inside a semaphore slot so at most ``max_parallel``
    coroutines are executing the long ``adapter.dispatch`` at once.  All
    nodes in *nodes* are guaranteed to finish (or fail) before this method
    returns — callers must check results for pause signals.

    Args:
        lc (LedgerConnection): Open ledger connection (shared).
        run_id (str): Run identifier.
        graph (RunGraph): Execution graph.
        nodes (list[WaveNode]): Nodes to dispatch concurrently.

    Returns:
        list[NodeResult]: One result per node, in the same order as *nodes*.
    """

    from tripll.engine import NodeResult
    from tripll.tracing.spans import trace_span

    async def _guarded(node: WaveNode) -> NodeResult:
        return await engine._execute_node(lc, run_id, graph, node)

    with trace_span(  # batch_dispatch
        "tripll.batch_dispatch",
        run_id=run_id,
        batch_size=len(nodes),
        node_ids=[n.node_id for n in nodes],
    ):
        raw = await asyncio.gather(*(_guarded(n) for n in nodes), return_exceptions=True)
    results: list[NodeResult] = []
    for node, item in zip(nodes, raw, strict=True):
        if isinstance(item, BaseException):
            logger.error(
                "engine: {} node {} raised unexpectedly: {}",
                run_id,
                node.node_id,
                item,
            )
            results.append(
                NodeResult(
                    node.node_id,
                    "blocked",
                    0,
                    f"dispatch error: {item}",
                )
            )
        else:
            results.append(item)
    return results


async def _shielded_finalize_wave_ledger(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    node_id: str,
) -> None:
    """Re-queue a wave left in-flight after cancellation or crash (BUG-03).

    Uses ``asyncio.shield`` so ledger finalization completes even when the
    enclosing ``_execute_node`` coroutine is cancelled.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.
        node_id (str): Wave node identifier.
    """

    async def _do() -> None:
        row = get_wave(lc, run_id, node_id)
        if row.state not in ("running", "dispatched", "verifying"):
            return
        try:
            await asyncio.wait_for(engine._ledger_lock.acquire(), timeout=5.0)
        except TimeoutError:
            logger.warning(
                "engine: {} {} ledger lock timeout in cancellation finalizer",
                run_id,
                node_id,
            )
            return
        try:
            transition_wave(lc, run_id, node_id, "queued")
            append_event(
                lc,
                run_id=run_id,
                node_id=node_id,
                phase="recovery",
                last_action="cancellation: wave re-queued for resume",
            )
        finally:
            engine._ledger_lock.release()

    await asyncio.shield(_do())


def _scaffold_w0_worktrees(engine: Engine, run_id: str, graph: RunGraph) -> None:
    """Allocate W0 worktrees and stage plan slices before human-gate dispatch (D5).

    Args:
        run_id (str): Run identifier.
        graph (RunGraph): Parsed execution graph.

    Examples:
        >>> _scaffold_w0_worktrees.__name__
        '_scaffold_w0_worktrees'
    """
    run_dir = engine.runs_root.run_dir(run_id)
    for node in graph.nodes.values():
        if node.wave_id != "W0":
            continue
        try:
            worktree = engine.wtm.allocate(run_id, node.plan_id, node.wave_id)
            stage_dispatch_context(
                run_dir,
                worktree.path,
                node.plan_file,
                wave_id=node.wave_id,
            )
            logger.info(
                "engine: {} scaffolded W0 worktree {} on {}",
                run_id,
                node.node_id,
                worktree.path,
            )
        except Exception as exc:
            logger.warning(
                "engine: {} W0 worktree scaffold for {} failed: {}",
                run_id,
                node.node_id,
                exc,
            )


async def _drive_via_outer_loop(
    engine: Engine,
    run_id: str,
    graph: RunGraph,
    *,
    run_bag: dict[str, Any] | None = None,
) -> RunResult:
    """Run batch dispatch through the L1 outer LangGraph (``waves`` → Engine seam).

    Args:
        run_id (str): Run identifier.
        graph (RunGraph): Parsed execution graph.
        run_bag (dict[str, Any] | None): Optional trace span bag from ``_drive``.

    Returns:
        RunResult: Outcome recorded by the outer ``waves`` node.
    """
    from tripll.engine import NodeResult, RunResult
    from tripll.loops.l1_outer import checkpoint_db_path, compile_l1_outer_graph

    run_dir = engine.runs_root.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    db_path = checkpoint_db_path(run_dir)
    _configure_orchestrator(engine, graph, run_id=run_id)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as cp:
        app = compile_l1_outer_graph(
            cp,
            run_dir=run_dir,
            engine=engine,
        )
        cfg: dict[str, Any] = {
            "configurable": {"thread_id": run_id},
            "durability": "sync",
        }
        seed: dict[str, Any] = {
            "run_id": run_id,
            "thread_id": run_id,
            "run_dir": str(run_dir),
            "history": [],
            "turn": 0,
        }
        await app.ainvoke(seed, cfg)
        final = await app.aget_state(cfg)
        values = dict(final.values)
        wave_payload = values.get("wave_dispatch") or {}
        node_details = wave_payload.get("node_details") or {}
        nodes = {
            str(node_id): NodeResult(
                str(node_id),
                str(detail.get("state") or "blocked"),
                int(detail.get("attempts") or 0),
                str(detail.get("evidence") or ""),
            )
            for node_id, detail in node_details.items()
        }

        wave_state = str(wave_payload.get("state") or "failed")
        paused = bool(
            wave_payload.get("paused")
            or wave_payload.get("hitl_pending")
            or wave_payload.get("quota_pending")
            or wave_payload.get("cost_pending")
            or values.get("paused")
        )
        if paused:
            state = wave_state if wave_state != "done" else "paused"
        elif wave_state != "done":
            state = wave_state
        elif (
            not values.get("ci_green", True)
            or values.get("review_clean") is False
            or values.get("outer_generate", {}).get("ok") is False
        ):
            state = "failed"
        else:
            state = "done"

        if state == "done":
            engine.runs_root.complete_run(run_id)
        elif state == "failed":
            engine.runs_root.fail_run(run_id)

        if run_bag is not None:
            run_bag["exit_id"] = state
            run_bag["waves_done"] = int(wave_payload.get("waves_done") or 0)
        return RunResult(
            run_id=run_id,
            state=state,
            nodes=nodes,
            quota_pending=bool(wave_payload.get("quota_pending")),
            cost_pending=bool(wave_payload.get("cost_pending")),
            hitl_pending=bool(wave_payload.get("hitl_pending")),
            hitl_gate_kind=wave_payload.get("hitl_gate_kind"),
        )


async def _drive(engine: Engine, run_id: str, graph: RunGraph) -> RunResult:
    """Main run loop: batches, concurrent dispatch, gates, and terminal state."""
    from tripll.engine import _PRE0_MARKER, RunResult
    from tripll.loops import graph_available, require_graph
    from tripll.loops.l1_outer import plan_requires_langgraph

    if plan_requires_langgraph(graph):
        require_graph(feature="cyclic run plan")

    _scaffold_w0_worktrees(engine, run_id, graph)
    # Pre-0 human gate (W5.4).
    if graph.pre0_gates and not engine._is_approved(run_id):
        from tripll.plan.human_gates import (
            HumanGateOutcome,
            evaluate_ci_billing_canary,
            pipeline_config_for_graph,
            resolve_human_gate_mode,
            resolve_pre0_gate,
        )

        pipeline = pipeline_config_for_graph(graph, engine.repo_root)
        mode = resolve_human_gate_mode(pipeline)
        canary = evaluate_ci_billing_canary()
        outcome = resolve_pre0_gate(mode=mode, auto_acceptable=True, canary=canary)
        run_dir = engine.runs_root.run_dir(run_id)

        if outcome is HumanGateOutcome.FAIL:
            logger.error("engine: {} Pre-0 gate rejected (human_gates=fail)", run_id)
            with open_ledger(engine.runs_root.ledger_path(run_id)) as lc:
                transition_run(lc, run_id, "failed")
            write_report(
                engine.runs_root.run_dir(run_id),
                graph,
                run_id=run_id,
                state="failed",
                results={},
            )
            return RunResult(run_id=run_id, state="failed")

        if outcome is HumanGateOutcome.PARKED:
            logger.warning(
                "engine: {} Pre-0 PARKED — canary red under auto_accept ({})",
                run_id,
                canary.detail,
            )
            with open_ledger(engine.runs_root.ledger_path(run_id)) as lc:
                transition_run(lc, run_id, "paused")
            write_report(
                engine.runs_root.run_dir(run_id),
                graph,
                run_id=run_id,
                state="parked",
                results={},
            )
            return RunResult(run_id=run_id, state="parked")

        if outcome is HumanGateOutcome.PROCEED:
            (run_dir / _PRE0_MARKER).write_text("auto_accept\n")
            logger.info(
                "engine: {} Pre-0 auto-accepted (canary ok: {})",
                run_id,
                canary.detail,
            )
        else:
            _write_pre0_sheet(engine, run_id, graph)
            write_form_for_run(run_dir, graph, gate_kind=GateKind.PRE0)
            with open_ledger(engine.runs_root.ledger_path(run_id)) as lc:
                transition_run(lc, run_id, "paused")
            write_report(
                engine.runs_root.run_dir(run_id),
                graph,
                run_id=run_id,
                state="paused",
                results={},
            )
            logger.info("engine: {} paused at Pre-0 ({} gates)", run_id, len(graph.pre0_gates))
            return RunResult(
                run_id=run_id,
                state="paused",
                pre0_pending=True,
                hitl_pending=True,
                hitl_gate_kind=GateKind.PRE0.value,
            )

    from tripll.tracing.spans import close_run_tracing, trace_span

    engine._init_run_tracing(run_id, graph)
    slug = run_id.rsplit("-", 2)[0]
    run_attrs: dict[str, Any] = {
        "slug": slug,
        "base": getattr(graph, "base", ""),
        "branch": getattr(graph, "branch", ""),
        "target_repo": getattr(graph, "target_repo", ""),
    }

    try:
        with trace_span("tripll.run", run_id=run_id, **run_attrs) as run_bag:
            engine._active_run_graph = graph
            try:
                engine._role_dispatch_effective = engine._resolve_role_dispatch(graph)
                if engine._pools is None:
                    engine._init_provider_fabric(graph)
                _configure_orchestrator(engine, graph, run_id=run_id)

                if engine._orchestrator_mode:
                    done: set[str] = set()
                    blocked: list[str] = []
                    results: dict[str, NodeResult] = {}
                    with open_ledger(engine.runs_root.ledger_path(run_id)) as lc:
                        await _prepare_run_ledger(
                            engine,
                            lc,
                            run_id,
                            graph,
                            done,
                            blocked,
                            results,
                            record_validate_snapshot=graph_available(),
                        )
                        result = await _drive_orchestrator_serial(
                            engine, lc, run_id, graph, done, blocked, results
                        )
                    run_bag["exit_id"] = result.state
                    run_bag["waves_done"] = len(done)
                    run_bag["waves_parked"] = sum(
                        1 for r in results.values() if r.state in ("blocked", "paused")
                    )
                    return result

                if graph_available():
                    return await _drive_via_outer_loop(engine, run_id, graph, run_bag=run_bag)

                return await drive_wave_batches(
                    engine,
                    run_id,
                    graph,
                    run_bag=run_bag,
                    record_validate_snapshot=True,
                )
            finally:
                engine._active_run_graph = None
    finally:
        close_run_tracing()
