"""Orchestrator row helpers extracted from :mod:`tripll.engine`."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from loguru import logger

from tripll.adapters.pools import pools_from_plan
from tripll.brief import extract_wave_summary
from tripll.engine_scheduling import orchestrator_serial_nodes
from tripll.engine_worktrees import GitWorktreeManager, SingleBranchWorktreeManager
from tripll.git_commit import commit_and_push_wave
from tripll.hitl import GateKind
from tripll.ledger import (
    ORCHESTRATOR_NODE_ID,
    LedgerConnection,
    RunState,
    append_event,
    open_ledger,
    transition_run,
)
from tripll.orchestrator_status import OrchestratorTurn, StatusRow, sync_orchestrator_status

_REVIEW_GATE_MARKER = "review-gate-pending.md"
_REVIEW_GATE_APPROVED = "review-gate-approved"

if TYPE_CHECKING:
    from tripll.engine import Engine, NodeResult, RunResult
    from tripll.graph import OrchestratorConfig, RunGraph, WaveNode
    from tripll.worktrees import Worktree


def _initial_orchestrator_rows(cfg: OrchestratorConfig) -> list[StatusRow]:
    """Build initial orchestrator status rows for each serial wave."""
    branch = cfg.feature_branch or "—"
    return [StatusRow(w, branch=branch) for w in cfg.serial_waves]


def _orchestrator_agent_enabled() -> bool:
    """Return True when headless wave-orchestrator gate dispatch is enabled (W4.4).

    Returns:
        bool: True when ``TRIPLL_ORCHESTRATOR_AGENT`` is truthy.

    Examples:
        >>> isinstance(_orchestrator_agent_enabled(), bool)
        True
    """
    return os.environ.get("TRIPLL_ORCHESTRATOR_AGENT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _configure_orchestrator(engine: Engine, graph: RunGraph, *, run_id: str) -> None:
    """Apply orchestrator-mode adapter, worktree, and status settings."""
    cfg = graph.orchestrator
    if cfg is None or not cfg.enabled:
        engine._orchestrator_mode = False
        return
    engine._orchestrator_mode = True
    from tripll.adapters import BACKENDS, build_adapter
    from tripll.adapters.claude_code import ClaudeCodeAdapter
    from tripll.adapters.cursor_local import CursorLocalAdapter
    from tripll.adapters.options import BackendOptions

    if engine.adapter.name in BACKENDS:
        opts = BackendOptions()
        if isinstance(engine.adapter, ClaudeCodeAdapter):
            opts = BackendOptions(
                model=engine.adapter.model,
                agent=engine.adapter.agent,
                verbose=engine.adapter.verbose,
            )
        elif isinstance(engine.adapter, CursorLocalAdapter):
            opts = BackendOptions(model=engine.adapter.model, agent=engine.adapter.agent)
        engine.adapter = build_adapter(engine.adapter.name, options=opts, orchestrator=cfg)
    engine._max_parallel = 1
    engine._pools, engine._default_provider = pools_from_plan(None, global_limit=1)
    engine._orchestrator_rows = _initial_orchestrator_rows(cfg)
    engine._orchestrator_turns = []
    run_dir = engine.runs_root.run_dir(run_id)
    if (run_dir / "orchestrator-status.md").is_file():
        from tripll.orchestrator_status import read_latest

        snap = read_latest(run_dir)
        engine._orchestrator_turns = list(snap.turns)
        if snap.rows:
            engine._orchestrator_rows = list(snap.rows)
    engine._wave_commit_shas = {}
    if cfg.single_branch and cfg.feature_branch:
        engine._orchestrator_single_branch = True
        if isinstance(engine.wtm, GitWorktreeManager) and not isinstance(
            engine.wtm, SingleBranchWorktreeManager
        ):
            engine.wtm = SingleBranchWorktreeManager(
                engine.repo_root,
                engine.runs_root,
                feature_branch=cfg.feature_branch,
            )
    else:
        engine._orchestrator_single_branch = False


def _orchestrator_sync(
    engine: Engine,
    run_id: str,
    graph: RunGraph,
    *,
    turn: OrchestratorTurn | None = None,
    lc: LedgerConnection | None = None,
) -> None:
    """Write ``orchestrator-status.md`` and optionally emit a ledger event."""
    sync_orchestrator_status(
        engine.runs_root.run_dir(run_id),
        graph,
        rows=list(engine._orchestrator_rows),
        turns=engine._orchestrator_turns,
        turn=turn,
        run_id=run_id,
    )
    if turn is not None:
        logger.info("orchestrator: {} — {}", turn.turn_type, turn.summary)
        _emit_orchestrator_event(engine, run_id, turn, lc=lc)


def _emit_orchestrator_event(
    engine: Engine,
    run_id: str,
    turn: OrchestratorTurn,
    *,
    lc: LedgerConnection | None = None,
) -> None:
    """Append a ledger ``phase=orchestrator`` event for terminal/SSE feed (W3).

    Args:
        run_id (str): Run identifier.
        turn (OrchestratorTurn): Orchestrator turn to record.
        lc (LedgerConnection | None): Open ledger when already inside a transaction.

    Examples:
        >>> _emit_orchestrator_event.__name__
        '_emit_orchestrator_event'
    """
    excerpt_parts = [turn.summary.strip()]
    if turn.wave_summary.strip():
        excerpt_parts.append(turn.wave_summary.strip())
    excerpt = "\n\n".join(excerpt_parts)[:500]
    one_line = " ".join(turn.summary.split())
    metadata = json.dumps({"turn_type": turn.turn_type, "excerpt": excerpt}, ensure_ascii=False)

    def _append(target: LedgerConnection) -> None:
        append_event(
            target,
            run_id=run_id,
            node_id=ORCHESTRATOR_NODE_ID,
            phase="orchestrator",
            last_action=one_line[:240],
            metadata=metadata,
        )

    if lc is not None:
        _append(lc)
        return
    ledger_path = engine.runs_root.ledger_path(run_id)
    if not ledger_path.is_file():
        return
    with open_ledger(ledger_path) as local_lc:
        _append(local_lc)


def _update_orchestrator_row(
    engine: Engine,
    wave_id: str,
    *,
    status: str,
    branch: str | None = None,
    commit: str = "—",
    evidence: str = "",
) -> None:
    """Update one row in the orchestrator status table for *wave_id*."""
    branch_val = branch or "—"
    for i, row in enumerate(engine._orchestrator_rows):
        if row.wave == wave_id:
            engine._orchestrator_rows[i] = StatusRow(
                wave=wave_id,
                status=status,
                branch=branch_val,
                commit=commit,
                evidence=evidence,
            )
            return
    engine._orchestrator_rows.append(
        StatusRow(
            wave=wave_id,
            status=status,
            branch=branch_val,
            commit=commit,
            evidence=evidence,
        )
    )


def _orchestrator_commit_subject(engine: Engine, cfg: OrchestratorConfig, wave_id: str) -> str:
    """Return the commit subject for orchestrator wave *wave_id*."""
    return cfg.commit_subjects.get(wave_id, f"feat(tripll): {wave_id}")


def _orchestrator_commit_wave(
    engine: Engine,
    run_id: str,
    graph: RunGraph,
    node: WaveNode,
    worktree: Worktree,
) -> tuple[bool, str]:
    """Commit and push orchestrator wave *node* when ``commit_per_wave`` is enabled."""
    cfg = graph.orchestrator
    if cfg is None or not cfg.commit_per_wave:
        return True, ""
    subject = _orchestrator_commit_subject(engine, cfg, node.wave_id)
    ok, result = commit_and_push_wave(
        worktree.path,
        engine.repo_root,
        message=subject,
        branch=worktree.branch,
    )
    if not ok:
        _orchestrator_sync(
            engine,
            run_id,
            graph,
            turn=OrchestratorTurn(
                "stop",
                f"Push failed after {node.wave_id}: {result[:200]}",
            ),
        )
        return False, result
    engine._wave_commit_shas[node.wave_id] = result
    return True, result


async def _handle_review_gate(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    node: WaveNode,
    cfg: OrchestratorConfig,
    *,
    branch: str,
    short_commit: str,
    summary: str,
    results: dict[str, NodeResult],
) -> RunResult | None:
    """Handle a review gate after a wave completes (extracted from serial loop).

    When the wave has a review gate configured (either via
    ``orchestrator.review_gates`` or ``node.is_review_gate``), writes the
    gate marker, optionally dispatches a headless gate agent, and either
    continues (gate approved) or pauses the run.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.
        graph (RunGraph): Execution graph.
        node (WaveNode): The wave node that just completed.
        cfg (OrchestratorConfig): Orchestrator configuration.
        branch (str): Feature branch name for status updates.
        short_commit (str): Abbreviated commit SHA for status rows.
        summary (str): Wave completion summary text.
        results (dict[str, NodeResult]): Accumulated node results (for report sync).

    Returns:
        RunResult | None: ``RunResult(state="paused")`` when stopped at the gate,
        or ``None`` when the gate was approved.

    Examples:
        >>> _handle_review_gate.__name__
        '_handle_review_gate'
    """
    from tripll.engine import RunResult

    gate_label = cfg.review_gates.get(node.wave_id)
    if not gate_label and not node.is_review_gate:
        return None

    label = gate_label or f"{node.wave_id} review gate"
    engine._write_review_gate_pause(run_id, node.wave_id, label)
    _update_orchestrator_row(
        engine,
        node.wave_id,
        status="awaiting review",
        branch=branch,
        commit=short_commit,
        evidence=f"AWAITING REVIEW ({label})",
    )
    _orchestrator_sync(
        engine,
        run_id,
        graph,
        turn=OrchestratorTurn(
            "review_gate",
            f"**AWAITING REVIEW** ({label}) — approve before next wave",
        ),
        lc=lc,
    )
    gate_proceed = False
    if _orchestrator_agent_enabled():
        from tripll.adapters import BACKENDS, build_gate_adapter
        from tripll.orchestrator_gate import dispatch_orchestrator_gate

        run_dir = engine.runs_root.run_dir(run_id)
        wt_path = engine._last_worktree_path or engine.repo_root
        gate_adapter = (
            build_gate_adapter(engine.adapter.name, cfg)
            if engine.adapter.name in BACKENDS
            else engine.adapter
        )
        gate_prompt = f"{label} complete — present summary, STOP"
        context: dict[str, object] = {
            "wave_id": node.wave_id,
            "gate_label": label,
            "wave_summary": summary,
            "worktree_path": str(wt_path),
            "branch": branch,
            "plan_path": node.plan_file,
        }
        decision = await dispatch_orchestrator_gate(
            run_dir,
            gate_prompt,
            context,
            adapter=gate_adapter,
            orchestrator=cfg,
            worktree_path=wt_path,
            timeout_s=node.wall_clock_limit_s,
        )
        gate_proceed = decision.proceed
        _orchestrator_sync(
            engine,
            run_id,
            graph,
            turn=OrchestratorTurn(
                "orchestrator_agent",
                decision.summary[:240],
            ),
            lc=lc,
        )
    if gate_proceed:
        run_dir = engine.runs_root.run_dir(run_id)
        (run_dir / _REVIEW_GATE_APPROVED).write_text(f"{node.wave_id}\n")
        (run_dir / _REVIEW_GATE_MARKER).unlink(missing_ok=True)
        logger.info(
            "orchestrator: gate agent approved {} — continuing serial run",
            node.wave_id,
        )
        return None  # continue
    async with engine._ledger_lock:
        transition_run(lc, run_id, "paused")
    engine._sync_report(run_id, graph, partial_results=results)
    return RunResult(
        run_id=run_id,
        state="paused",
        nodes=results,
        hitl_pending=True,
        hitl_gate_kind=GateKind.REVIEW_GATE.value,
    )


async def _drive_orchestrator_serial(
    engine: Engine,
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    done: set[str],
    blocked: list[str],
    results: dict[str, NodeResult],
) -> RunResult:
    """Serial orchestrator drive — one wave at a time with status turns (W2).

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.
        graph (RunGraph): Execution graph.
        done (set[str]): Completed node ids (updated in place).
        blocked (list[str]): Blocked node ids (updated in place).
        results (dict[str, NodeResult]): Per-node outcomes (updated in place).

    Returns:
        RunResult: Terminal or paused run outcome.

    Examples:
        >>> _drive_orchestrator_serial.__name__
        '_drive_orchestrator_serial'
    """
    from tripll.engine import RunResult

    cfg = graph.orchestrator
    if cfg is None:
        return RunResult(run_id=run_id, state="failed", nodes=results)

    branch = cfg.feature_branch or "—"
    _orchestrator_sync(
        engine,
        run_id,
        graph,
        turn=OrchestratorTurn(
            "bootstrap",
            f"Orchestrator serial run on `{branch}` — "
            f"{len(orchestrator_serial_nodes(graph))} waves",
        ),
        lc=lc,
    )

    for node in orchestrator_serial_nodes(graph):
        if node.node_id in done or node.node_id in blocked:
            continue

        # Pause-marker check: honour API pause before starting a new wave.
        # In-flight waves are NOT killed -- they run to completion.
        if engine._pause_requested(run_id):
            logger.info(
                "engine: {} pause-requested marker found -- pausing before {}",
                run_id,
                node.wave_id,
            )
            _orchestrator_sync(
                engine,
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "stop",
                    f"Pause requested -- stopping before {node.wave_id}",
                ),
                lc=lc,
            )
            async with engine._ledger_lock:
                transition_run(lc, run_id, "paused")
            engine._sync_report(run_id, graph, partial_results=results)
            return RunResult(run_id=run_id, state="paused", nodes=results)

        _update_orchestrator_row(engine, node.wave_id, status="in progress", branch=branch)
        _orchestrator_sync(
            engine,
            run_id,
            graph,
            turn=OrchestratorTurn(
                "wave_dispatched",
                f"Dispatching wave-runner for **{node.wave_id}** (`{node.node_id}`)",
            ),
            lc=lc,
        )
        engine._sync_report(run_id, graph, current_node_id=node.node_id, partial_results=results)

        res = await engine._execute_node(lc, run_id, graph, node)
        results[node.node_id] = res

        if res.state == "done":
            summary = extract_wave_summary(engine._last_dispatch_result_text)
            commit_sha = engine._wave_commit_shas.get(node.wave_id, "—")
            short_commit = commit_sha[:12] if commit_sha != "—" else "—"
            _update_orchestrator_row(
                engine,
                node.wave_id,
                status="done",
                branch=branch,
                commit=short_commit,
                evidence=summary[:120] if summary else "verify ok",
            )
            _orchestrator_sync(
                engine,
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "wave_complete",
                    f"**{node.wave_id}** complete",
                    wave_summary=summary,
                ),
                lc=lc,
            )
            done.add(node.node_id)

            gate_result = await _handle_review_gate(
                engine,
                lc,
                run_id,
                graph,
                node,
                cfg,
                branch=branch,
                short_commit=short_commit,
                summary=summary,
                results=results,
            )
            if gate_result is not None:
                return gate_result

        elif res.state in ("quota_paused", "cost_paused"):
            _orchestrator_sync(
                engine,
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "stop",
                    f"Paused during {node.wave_id}: {res.evidence[:200]}",
                ),
                lc=lc,
            )
            engine._sync_report(run_id, graph, partial_results=results)
            return RunResult(
                run_id=run_id,
                state="paused",
                nodes=results,
                quota_pending=res.state == "quota_paused",
                cost_pending=res.state == "cost_paused",
            )
        elif res.state == "blocked":
            evidence = res.evidence or ""
            if "push failed" in evidence.lower() or "git push" in evidence.lower():
                _orchestrator_sync(
                    engine,
                    run_id,
                    graph,
                    turn=OrchestratorTurn(
                        "stop",
                        f"Push failed during {node.wave_id}: {evidence[:200]}",
                    ),
                    lc=lc,
                )
                async with engine._ledger_lock:
                    transition_run(lc, run_id, "paused")
                engine._sync_report(run_id, graph, partial_results=results)
                return RunResult(run_id=run_id, state="paused", nodes=results)
            _update_orchestrator_row(
                engine,
                node.wave_id,
                status="failed",
                branch=branch,
                evidence=evidence[:120],
            )
            _orchestrator_sync(
                engine,
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "wave_failed",
                    f"**{node.wave_id}** blocked: {evidence[:200]}",
                ),
                lc=lc,
            )
            blocked.append(node.node_id)
            engine._sync_report(run_id, graph, partial_results=results)

    state: RunState = "failed" if blocked else "done"
    if blocked:
        engine._write_escalation(run_id, blocked, results)
    transition_run(lc, run_id, state)
    engine._sync_report(run_id, graph, partial_results=results)
    if blocked:
        engine.runs_root.fail_run(run_id)
        return RunResult(run_id=run_id, state="failed", nodes=results)
    engine.runs_root.complete_run(run_id)
    return RunResult(run_id=run_id, state="done", nodes=results)
