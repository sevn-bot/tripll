"""Node dispatch loop extracted from :mod:`tripll.engine` (R38)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from tripll.brief import write_brief
from tripll.engine_brief import safe_node_id
from tripll.harness.boundary import detect_structural_scope_breach
from tripll.harness.fingerprint import (
    capture_env_fingerprint,
    fingerprint_hash,
    fingerprint_to_json,
)
from tripll.harness.quality import quality_gauntlet_enabled
from tripll.ledger import (
    LedgerConnection,
    append_event,
    end_attempt,
    get_run_cost,
    get_wave,
    insert_attempt,
    transition_run,
    transition_wave,
    void_infra_attempt_count,
)
from tripll.worktrees import Worktree, WorktreeError, changed_paths, stage_dispatch_context

_MAX_NO_PROGRESS_DISPATCHES = 1
_MAX_CONSECUTIVE_INFRA = 5

if TYPE_CHECKING:
    from tripll.adapters.base import DispatchResult
    from tripll.engine import Engine, NodeResult
    from tripll.graph import RunGraph, WaveNode
    from tripll.ledger import AttemptOutcome

COMPOUNDING_TERMINAL_OUTCOMES = frozenset(
    {"done", "failed", "blocked", "scope_breach", "unverified", "timed_out"}
)


def _end_attempt_with_usage(
    engine: Engine,
    lc: LedgerConnection,
    attempt_id: str,
    *,
    outcome: AttemptOutcome,
    evidence: str | None,
    result: DispatchResult,
) -> None:
    """Close a ledger attempt row with usage fields from *result*."""
    end_attempt(
        lc,
        attempt_id,
        outcome=outcome,
        evidence=evidence,
        cost_usd=result.cost_usd,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


async def _execute_node(
    engine: Engine, lc: LedgerConnection, run_id: str, graph: RunGraph, node: WaveNode
) -> NodeResult:
    """Dispatch, verify, and checkpoint one wave node (with retries and scope checks)."""
    from tripll.tracing.spans import trace_span

    with trace_span(  # execute_node
        "tripll.execute_node",
        run_id=run_id,
        node_id=node.node_id,
        wave_id=node.wave_id,
        lane=node.lane,
    ):
        result = await _execute_node_body(engine, lc, run_id, graph, node)
        try:
            _finalize_wave_compounding(engine, lc, run_id, node, result)
        except Exception as exc:
            logger.debug(
                "engine: {} {} compounding finalize failed: {}",
                run_id,
                node.node_id,
                exc,
                exc_info=True,
            )
        return result


def _finalize_wave_compounding(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    node: WaveNode,
    result: NodeResult,
) -> None:
    """Write wave postmortem and optionally propose rules after terminal outcome (W3)."""
    if result.state not in COMPOUNDING_TERMINAL_OUTCOMES:
        return
    from tripll.config import load_config
    from tripll.ledger import list_attempts
    from tripll.rules.postmortem import finalize_wave_compounding

    cfg = load_config(repo_root=engine.repo_root)
    if not cfg.rules.enabled:
        return
    attempts = list_attempts(lc, run_id, node.node_id)
    outcome_contract = node.outcome_contract if isinstance(node.outcome_contract, dict) else {}
    required = outcome_contract.get("required")
    contract = {
        "required": list(required) if isinstance(required, list) else [],
        "forbidden": list(node.forbidden_paths),
        "targets": list(node.owned_paths) or list(node.verify_targets),
    }
    finalize_wave_compounding(
        run_id=run_id,
        node_id=node.node_id,
        wave_id=node.wave_id,
        contract=contract,
        attempts=attempts,
        wave_outcome=result.state,
        runs_root=engine.runs_root.root,
        repo_root=engine.repo_root,
        rules_config=cfg.rules,
    )


async def _execute_node_body(
    engine: Engine, lc: LedgerConnection, run_id: str, graph: RunGraph, node: WaveNode
) -> NodeResult:
    """Inner dispatch loop for :meth:`_execute_node` (ledger + verify + retries)."""
    from tripll.engine import NodeResult

    worktree = engine.wtm.allocate(run_id, node.plan_id, node.wave_id)
    engine._last_worktree_path = worktree.path
    run_dir = engine.runs_root.run_dir(run_id)
    stage_dispatch_context(run_dir, worktree.path, node.plan_file, wave_id=node.wave_id)
    # --- read: no lock needed ---
    wave = get_wave(lc, run_id, node.node_id)
    if engine._cost_budget_exceeded(lc, run_id):
        spent = get_run_cost(lc, run_id)
        engine._evaluate_engine_exit(3, lc, run_id)
        engine._write_cost_pause(run_id, spent)
        return NodeResult(
            node.node_id,
            "cost_paused",
            wave.attempt_count,
            f"cost budget ${engine.cost_budget_usd:.2f} reached (${spent:.4f} spent)",
        )
    async with engine._ledger_lock:
        if wave.state in ("running", "dispatched", "verifying"):
            transition_wave(lc, run_id, node.node_id, "queued")
    _recover_worktree(engine, worktree, run_id, node.node_id)

    prior_failures: list[str] = []
    evidence = ""
    cleanup_worktree_on_exit = False
    attempts_used = wave.attempt_count
    # Smarter retries (W2): track how many full re-dispatches produced no edits
    # in owned paths.  Once this counter reaches _MAX_NO_PROGRESS_DISPATCHES we
    # escalate immediately rather than burning all max_attempts slots.
    no_progress_dispatches: int = 0
    consecutive_infra: int = 0
    pools = engine._pools
    pool_provider: str | None = None
    try:
        while attempts_used < engine.max_attempts:
            if engine._cost_budget_exceeded(lc, run_id):
                spent = get_run_cost(lc, run_id)
                engine._evaluate_engine_exit(3, lc, run_id)
                engine._write_cost_pause(run_id, spent)
                return NodeResult(
                    node.node_id,
                    "cost_paused",
                    attempts_used,
                    f"cost budget ${engine.cost_budget_usd:.2f} reached (${spent:.4f} spent)",
                )

            # No-progress early exit: if we already hit the cap, escalate now
            # instead of dispatching another doomed full attempt.
            if no_progress_dispatches >= _MAX_NO_PROGRESS_DISPATCHES:
                from tripll.loops.exits import NO_PROGRESS_STREAK

                engine._evaluate_engine_exit(
                    5,
                    lc,
                    run_id,
                    turn_hashes=["no-progress"] * NO_PROGRESS_STREAK,
                )
                evidence = (
                    f"no-progress escalation after {no_progress_dispatches} "
                    f"dispatch(es) produced no edits in owned paths "
                    f"{node.owned_paths!r} — likely a scope-permission or "
                    f"brief-configuration problem"
                )
                logger.warning(
                    "engine: {} {} — {}",
                    run_id,
                    node.node_id,
                    evidence,
                )
                engine._fire_error_threshold_exit(lc, run_id, node=node, failures=attempts_used)
                async with engine._ledger_lock:
                    transition_wave(lc, run_id, node.node_id, "blocked")
                return NodeResult(node.node_id, "blocked", attempts_used, evidence)

            attempt = attempts_used + 1
            provider, fallback_used = engine._pick_provider(node)
            adapter = engine._resolve_adapter(node, graph, provider=provider)
            if pools is not None and pool_provider != provider:
                if pool_provider is not None:
                    pools.release(pool_provider)
                await pools.acquire(provider)
                pool_provider = provider
            brief = engine._brief_for(
                run_id, graph, node, worktree, prior_failures, attempt=attempt
            )
            if fallback_used:
                brief["fallback_used"] = True
                brief["provider"] = provider
            if node.max_budget_usd is not None:
                brief["max_budget_usd"] = node.max_budget_usd
            if node.reasoning_effort:
                brief["reasoning_effort"] = node.reasoning_effort
            write_brief(brief, engine.runs_root.briefs_dir(run_id))
            log_path = engine.runs_root.logs_dir(run_id) / (
                f"{safe_node_id(node.node_id)}-attempt{attempt}.log"
            )
            if attempt == 1 and attempts_used == 0:
                logger.info(
                    "engine: {} node {} — branch {} worktree {}",
                    run_id,
                    node.node_id,
                    worktree.branch,
                    worktree.path,
                )
            logger.info(
                "engine: {} attempt {} — log {}",
                node.node_id,
                attempt,
                log_path,
            )
            # Snapshot owned-path edits *before* dispatch so we can detect
            # whether the agent produced any new work (W2 no-progress guard).
            # None means the worktree is not git-backed (e.g. tests) — skip guard.
            pre_dispatch_owned = _owned_changed_paths(engine, worktree, node.owned_paths)

            # --- mutating sequence: insert_attempt + transition_wave x2 ---
            task_id = f"{run_id}:{node.node_id}"
            env_fp = capture_env_fingerprint(
                task_id=task_id,
                model_id=node.model or getattr(adapter, "model", None) or "",
                repo_root=engine.repo_root,
            )
            fp_json = fingerprint_to_json(env_fp)
            fp_hash = fingerprint_hash(env_fp)
            async with engine._ledger_lock:
                attempt_id = insert_attempt(
                    lc,
                    run_id=run_id,
                    node_id=node.node_id,
                    attempt_n=attempt,
                    backend=adapter.name,
                    brief_path=str(engine.runs_root.briefs_dir(run_id)),
                    log_path=str(log_path),
                    model=node.model or getattr(adapter, "model", None),
                    agent=getattr(adapter, "agent", None),
                    env_fingerprint_json=fp_json,
                    env_fingerprint_hash=fp_hash,
                )
                attempts_used += 1
                transition_wave(lc, run_id, node.node_id, "dispatched")
                append_event(
                    lc,
                    run_id=run_id,
                    node_id=node.node_id,
                    phase="dispatched",
                    attempt_n=attempt,
                )
                transition_wave(lc, run_id, node.node_id, "running")
                append_event(lc, run_id=run_id, node_id=node.node_id, phase="running")

            wave_label = node.wave_id
            start_msg = (
                f"Executing wave {wave_label}: reading the plan contract and checking branch state."
            )
            async with engine._ledger_lock:
                append_event(
                    lc,
                    run_id=run_id,
                    node_id=node.node_id,
                    phase="running",
                    last_action=start_msg,
                    attempt_n=attempt,
                )

            # Build an async callback so run_streaming can write live events.
            # The callback is throttled inside run_streaming; here we only
            # guard the ledger write under _ledger_lock.
            # Capture node_id in the default arg to avoid the B023 closure
            # binding issue (ruff: loop variable capture in function definition).
            _bound_node_id: str = node.node_id

            async def _on_stream_event(
                *,
                last_action: str | None = None,
                input_tokens: int | None = None,
                output_tokens: int | None = None,
                cost_usd: float | None = None,
                _nid: str = _bound_node_id,
            ) -> None:
                # Called from inside run_streaming — emit a running event.
                from tripll.log_format import format_terminal_summary

                async with engine._ledger_lock:
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=_nid,
                        phase="running",
                        last_action=last_action,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                    )
                # Concise terminal heartbeat — one line per agent per meaningful change.
                if last_action or output_tokens:
                    short_id = _nid.split(":", 1)[-1] if ":" in _nid else _nid
                    tok_part = (
                        f" | {input_tokens or 0}→{output_tokens or 0} tok" if output_tokens else ""
                    )
                    cost_part = f" | ${cost_usd:.4f}" if cost_usd else ""
                    action_part = f" ▸ {last_action.strip()}" if last_action else ""
                    import sys

                    sys.stderr.write(
                        format_terminal_summary(
                            f"telemetry:{short_id}{action_part}{tok_part}{cost_part}"
                        )
                        + "\n"
                    )
                    sys.stderr.flush()

            # --- long await: no lock held ---
            from tripll.tracing.spans import trace_span

            wave_model = node.model or getattr(adapter, "model", None)
            with trace_span(
                "tripll.wave",
                run_id=run_id,
                node_id=node.node_id,
                attempt_id=attempt_id,
                wave_id=node.wave_id,
                lane=node.lane,
                provider=provider,
                model=wave_model,
                reasoning_effort=node.reasoning_effort,
                attempt_n=attempt,
            ) as wave_bag:
                try:
                    result = await adapter.dispatch(
                        brief,
                        worktree_path=worktree.path,
                        log_path=log_path,
                        timeout_s=node.wall_clock_limit_s,
                        log_header={
                            "run_id": run_id,
                            "node_id": node.node_id,
                            "attempt": attempt,
                            "attempt_id": attempt_id,
                            "backend": adapter.name,
                        },
                        on_event=_on_stream_event,
                    )
                except asyncio.CancelledError:
                    wave_bag["state"] = "cancelled"
                    raise
                except Exception as exc:
                    wave_bag["state"] = "failed"
                    wave_bag["failure_class"] = "unexpected"
                    evidence = f"dispatch raised: {exc}"
                    from tripll.adapters.base import DispatchResult

                    err_result = DispatchResult(
                        outcome="failed",
                        result_text=evidence,
                        returncode=1,
                        argv=adapter.build_argv(brief, worktree.path),
                    )
                    async with engine._ledger_lock:
                        _end_attempt_with_usage(
                            engine,
                            lc,
                            attempt_id,
                            outcome="failed",
                            evidence=evidence,
                            result=err_result,
                        )
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="failed",
                            last_action=evidence[:120],
                            attempt_n=attempt,
                        )
                        transition_wave(lc, run_id, node.node_id, "blocked")
                    return NodeResult(node.node_id, "blocked", attempts_used, evidence)
                wave_bag["fallback_used"] = fallback_used
            engine._last_dispatch_result_text = result.result_text or ""
            from tripll.adapters.failure_class import classify_dispatch

            failure_class = classify_dispatch(result)
            wave_bag["failure_class"] = failure_class
            wave_bag["state"] = result.outcome
            if failure_class == "infra":
                consecutive_infra += 1
                if consecutive_infra >= _MAX_CONSECUTIVE_INFRA:
                    failure_class = "failure"
                    evidence = (
                        f"infra streak cap ({_MAX_CONSECUTIVE_INFRA}) on {provider}: "
                        f"{result.result_text or 'infra failure'}"
                    )
                    async with engine._ledger_lock:
                        _end_attempt_with_usage(
                            engine,
                            lc,
                            attempt_id,
                            outcome="failed",
                            evidence=evidence,
                            result=result,
                        )
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="failed",
                            last_action=evidence[:120],
                            attempt_n=attempt,
                        )
                    prior_failures.append(f"attempt {attempt}: {evidence}")
                    if attempts_used < engine.max_attempts:
                        async with engine._ledger_lock:
                            transition_wave(lc, run_id, node.node_id, "queued")
                    continue
                if pools is not None:
                    pools.record_infra(provider)
                async with engine._ledger_lock:
                    void_infra_attempt_count(lc, run_id=run_id, node_id=node.node_id)
                    attempts_used -= 1
                    _end_attempt_with_usage(
                        engine,
                        lc,
                        attempt_id,
                        outcome="failed",
                        evidence=result.result_text or "infra failure",
                        result=result,
                    )
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        phase="infra",
                        last_action=f"infra on {provider}: {(result.result_text or '')[:120]}",
                        attempt_n=attempt,
                    )
                    transition_wave(lc, run_id, node.node_id, "queued")
                cooldown = pools.configs[provider].cooldown_s if pools else 0
                if cooldown > 0:
                    await asyncio.sleep(float(cooldown))
                continue
            consecutive_infra = 0
            if pools is not None:
                pools.record_success(provider)
            if result.cost_usd:
                logger.info(
                    "engine: {} {} attempt {} cost ${:.4f}",
                    run_id,
                    node.node_id,
                    attempt,
                    result.cost_usd,
                )

            # W2 no-progress detection: check if any owned path was touched.
            # Skip when pre is None (non-git worktree — guard disabled).
            if pre_dispatch_owned is not None:
                post_dispatch_owned = _owned_changed_paths(engine, worktree, node.owned_paths)
                made_progress = post_dispatch_owned is None or bool(
                    post_dispatch_owned - pre_dispatch_owned
                )
                if not made_progress:
                    no_progress_dispatches += 1
                    logger.warning(
                        "engine: {} {} attempt {} — no edits in owned paths (no-progress #{}/{})",
                        run_id,
                        node.node_id,
                        attempt,
                        no_progress_dispatches,
                        _MAX_NO_PROGRESS_DISPATCHES,
                    )

            if engine._cost_budget_exceeded(lc, run_id):
                async with engine._ledger_lock:
                    _end_attempt_with_usage(
                        engine,
                        lc,
                        attempt_id,
                        outcome="failed",
                        evidence="cost budget exceeded after dispatch",
                        result=result,
                    )
                    spent = get_run_cost(lc, run_id)
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        phase="paused",
                        last_action=f"cost budget ${engine.cost_budget_usd:.2f} reached",
                        cost_usd=result.cost_usd,
                    )
                engine._evaluate_engine_exit(3, lc, run_id)
                engine._write_cost_pause(run_id, spent)
                return NodeResult(
                    node.node_id,
                    "cost_paused",
                    attempt,
                    f"cost budget ${engine.cost_budget_usd:.2f} reached (${spent:.4f} spent)",
                )
            if result.outcome == "done":
                breach = engine.wtm.scope_breach(
                    worktree,
                    node.forbidden_paths,
                    owned_paths=node.owned_paths,
                )
                structural = detect_structural_scope_breach(
                    worktree.path,
                    repo_root=engine.repo_root,
                )
                if structural:
                    breach = sorted(set(breach) | set(structural))
                if breach:
                    revert_paths = sorted(
                        {
                            item.split(":", 1)[0] if ":" in item else item
                            for item in breach
                            if item.strip()
                        }
                    )
                    engine.wtm.revert(worktree, revert_paths)
                    evidence = f"scope breach reverted: {breach}"
                    async with engine._ledger_lock:
                        _end_attempt_with_usage(
                            engine,
                            lc,
                            attempt_id,
                            outcome="scope_breach",
                            evidence=evidence,
                            result=result,
                        )
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="failed",
                            last_action=f"scope breach reverted: {str(breach)[:120]}",
                        )
                    _checkpoint_attempt(engine, worktree, run_id, node.node_id, attempt)
                else:
                    _checkpoint_attempt(engine, worktree, run_id, node.node_id, attempt)
                    outcome_contract = node.outcome_contract
                    if isinstance(outcome_contract, dict) and quality_gauntlet_enabled(
                        outcome_contract
                    ):
                        async with engine._ledger_lock:
                            transition_wave(lc, run_id, node.node_id, "quality_loop")
                            append_event(
                                lc,
                                run_id=run_id,
                                node_id=node.node_id,
                                phase="quality_loop",
                            )
                        q_ok, quality_evidence = await engine._run_quality_gauntlet(
                            run_id=run_id,
                            node=node,
                            worktree=worktree,
                            outcome=outcome_contract,
                        )
                        if not q_ok:
                            from tripll.ledger import WaveState

                            new_state: WaveState = (
                                "unverified"
                                if "unverified" in quality_evidence.lower()
                                else "failed"
                            )
                            async with engine._ledger_lock:
                                _end_attempt_with_usage(
                                    engine,
                                    lc,
                                    attempt_id,
                                    outcome="failed",
                                    evidence=quality_evidence,
                                    result=result,
                                )
                                transition_wave(lc, run_id, node.node_id, new_state)
                                append_event(
                                    lc,
                                    run_id=run_id,
                                    node_id=node.node_id,
                                    phase=new_state,
                                    last_action=f"quality gauntlet: {quality_evidence[:120]}",
                                )
                            return NodeResult(node.node_id, new_state, attempt, quality_evidence)
                    async with engine._ledger_lock:
                        transition_wave(lc, run_id, node.node_id, "verifying")
                        append_event(lc, run_id=run_id, node_id=node.node_id, phase="verifying")
                    ok, ev = engine._run_isolated_verify(
                        run_id=run_id,
                        node=node,
                        implementer_worktree=worktree.path,
                        commit_sha=engine._last_checkpoint_sha,
                        targets=node.verify_targets,
                        transcript=result.result_text,
                    )
                    if ok:
                        if (
                            engine._orchestrator_mode
                            and graph.orchestrator
                            and graph.orchestrator.commit_per_wave
                        ):
                            commit_ok, commit_result = engine._orchestrator_commit_wave(
                                run_id, graph, node, worktree
                            )
                            if not commit_ok:
                                async with engine._ledger_lock:
                                    _end_attempt_with_usage(
                                        engine,
                                        lc,
                                        attempt_id,
                                        outcome="failed",
                                        evidence=commit_result,
                                        result=result,
                                    )
                                    transition_wave(lc, run_id, node.node_id, "blocked")
                                    transition_run(lc, run_id, "paused")
                                return NodeResult(
                                    node.node_id,
                                    "blocked",
                                    attempt,
                                    commit_result,
                                )
                        async with engine._ledger_lock:
                            _end_attempt_with_usage(
                                engine,
                                lc,
                                attempt_id,
                                outcome="done",
                                evidence=ev,
                                result=result,
                            )
                            transition_wave(lc, run_id, node.node_id, "done")
                            append_event(
                                lc,
                                run_id=run_id,
                                node_id=node.node_id,
                                phase="done",
                                input_tokens=result.input_tokens,
                                output_tokens=result.output_tokens,
                                cost_usd=result.cost_usd,
                            )
                        cleanup_worktree_on_exit = True
                        logger.info("engine: {} node {} done (verify ok)", run_id, node.node_id)
                        return NodeResult(node.node_id, "done", attempt)
                    evidence = ev
                    async with engine._ledger_lock:
                        _end_attempt_with_usage(
                            engine,
                            lc,
                            attempt_id,
                            outcome="failed",
                            evidence=ev,
                            result=result,
                        )
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="failed",
                            last_action=f"verify failed: {ev[:120]}",
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost_usd=result.cost_usd,
                        )
            elif result.outcome == "quota_exhausted":
                evidence = result.result_text or result.outcome
                async with engine._ledger_lock:
                    _end_attempt_with_usage(
                        engine,
                        lc,
                        attempt_id,
                        outcome="quota_exhausted",
                        evidence=evidence,
                        result=result,
                    )
                    _checkpoint_attempt(engine, worktree, run_id, node.node_id, attempt)
                    transition_wave(lc, run_id, node.node_id, "queued")
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        phase="paused",
                        last_action="quota exhausted — pausing",
                    )
                logger.warning(
                    "engine: {} quota exhausted on {} — pausing (no retry burn)",
                    run_id,
                    node.node_id,
                )
                return NodeResult(node.node_id, "quota_paused", attempt, evidence)
            else:
                evidence = result.result_text or result.outcome
                outcome: AttemptOutcome = "timed_out" if result.outcome == "timed_out" else "failed"
                async with engine._ledger_lock:
                    _end_attempt_with_usage(
                        engine,
                        lc,
                        attempt_id,
                        outcome=outcome,
                        evidence=evidence,
                        result=result,
                    )
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        phase="failed",
                        last_action=f"attempt {attempt} {outcome}: {evidence[:120]}",
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        cost_usd=result.cost_usd,
                    )
                _checkpoint_attempt(engine, worktree, run_id, node.node_id, attempt)

            prior_failures.append(f"attempt {attempt}: {evidence}")
            if attempts_used < engine.max_attempts:
                async with engine._ledger_lock:
                    transition_wave(lc, run_id, node.node_id, "queued")

        engine._fire_error_threshold_exit(lc, run_id, node=node, failures=attempts_used)
        async with engine._ledger_lock:
            transition_wave(lc, run_id, node.node_id, "blocked")
            append_event(
                lc,
                run_id=run_id,
                node_id=node.node_id,
                phase="failed",
                last_action=f"blocked after {attempts_used} attempts: {evidence[:120]}",
            )
        return NodeResult(node.node_id, "blocked", attempts_used, evidence)
    finally:
        if pools is not None and pool_provider is not None:
            pools.release(pool_provider)
        _recover_worktree(engine, worktree, run_id, node.node_id)
        try:
            await engine._shielded_finalize_wave_ledger(lc, run_id, node.node_id)
        except Exception as exc:
            logger.warning(
                "engine: {} {} ledger finalizer failed: {}",
                run_id,
                node.node_id,
                exc,
            )
        if cleanup_worktree_on_exit and not engine._orchestrator_single_branch:
            engine.wtm.cleanup(worktree)


def _owned_changed_paths(
    engine: Engine, worktree: Worktree, owned_paths: list[str]
) -> set[str] | None:
    """Return the set of changed worktree paths that fall under *owned_paths*.

    Used by the no-progress guard (W2) to detect whether the agent made any
    edits to its assigned paths since the last dispatch.

    Returns ``None`` when the worktree is not a git repository (e.g. in-memory
    fakes in tests) — callers should treat ``None`` as "indeterminate / assume
    progress" so the guard never fires on non-git worktrees.

    Args:
        worktree (Worktree): The lane worktree.
        owned_paths (list[str]): Paths the wave is assigned to edit.

    Returns:
        set[str] | None: Repo-relative changed paths under an owned path, or
        ``None`` when the status cannot be determined.
    """
    try:
        all_changed = changed_paths(worktree.path)
    except Exception:
        # Non-git worktree (FakeWorktreeManager in tests) — cannot tell.
        return None
    if not owned_paths:
        return set(all_changed)
    owned: set[str] = set()
    for path in all_changed:
        p = path.rstrip("/")
        for op in owned_paths:
            o = op.rstrip("/")
            # Changed path is under an owned path.
            if p == o or p.startswith(o + "/"):
                owned.add(path)
                break
            # Changed path is a directory prefix of an owned path — git
            # reports untracked directories at the first new ancestor level
            # (e.g. "src/" when "src/sevn/demo/marker.txt" was created).
            # In this case the owned path is *inside* the changed directory.
            if o.startswith(p + "/") or o == p:
                owned.add(path)
                break
    return owned


def _recover_worktree(engine: Engine, worktree: Worktree, run_id: str, node_id: str) -> None:
    """Commit orphaned work in *worktree* after a crash or timeout."""
    sha = engine.wtm.recover(worktree, run_id=run_id, node_id=node_id)
    if sha:
        logger.info(
            "engine: {} {} recovery checkpoint {}",
            run_id,
            node_id,
            sha[:12],
        )


def _checkpoint_attempt(
    engine: Engine, worktree: Worktree, run_id: str, node_id: str, attempt: int
) -> None:
    """Checkpoint *worktree* after attempt *attempt* (logs SHA when present)."""
    try:
        sha = engine.wtm.checkpoint(worktree, run_id=run_id, node_id=node_id, attempt=attempt)
    except WorktreeError as exc:
        logger.error(
            "engine: {} {} attempt {} checkpoint failed: {}",
            run_id,
            node_id,
            attempt,
            exc,
        )
        return
    if sha:
        engine._last_checkpoint_sha = sha
        logger.info(
            "engine: {} {} attempt {} checkpoint {}",
            run_id,
            node_id,
            attempt,
            sha[:12],
        )
