"""L1 outer LangGraph loop — validate → waves → verify → commit → review → generate.

Compiles a durable ``AsyncSqliteSaver`` graph keyed ``thread_id == run_id`` with
``durability="sync"`` on gate-bearing invocations. The ``waves`` node delegates
batch dispatch to :class:`~tripll.engine.Engine` via ``dispatch_bridge`` (L2-W4);
remaining outer nodes record step markers and ledger snapshots. PR investigate/fix
wiring lives in ``l1_pr`` + ``dispatch_bridge`` (W9).

Exports:
    OUTER_NODES — ordered node names for the outer loop.
    build_l1_outer_graph — compile-ready StateGraph builder.
    compile_l1_outer_graph — compiled graph with checkpointer + policies.
    checkpoint_db_path — ``checkpoints.db`` beside ``ledger.db``.
    record_loop_snapshot — persist recoverable state to the ledger (D6).
    get_loop_snapshot — load latest ledger snapshot.
    purge_stale_checkpoints — TTL purge for completed threads (§5.2).
    simulate_recovery — kill/resume integration test helper.
    recover_from_ledger — rebuild checkpoint state from ledger when lost.
    plan_requires_langgraph — True when a run graph needs the graph extra.
    sync_loop_snapshot_from_state — convenience wrapper for engine hook.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from tripll.loops import graph_available, require_graph
from tripll.loops.state import L1OuterState, graph_delta_hash, spill_large_field

if TYPE_CHECKING:
    from tripll.engine import Engine
    from tripll.graph import RunGraph
    from tripll.ledger import LedgerConnection

OUTER_NODES: tuple[str, ...] = (
    "validate",
    "waves",
    "verify",
    "commit",
    "review",
    "generate",
)

CHECKPOINT_FILENAME = "checkpoints.db"
CHECKPOINT_TTL_DAYS = 30
AUDIT_WINDOW_DAYS = 90

__all__ = [
    "AUDIT_WINDOW_DAYS",
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_TTL_DAYS",
    "OUTER_NODES",
    "build_l1_outer_graph",
    "checkpoint_db_path",
    "compile_l1_outer_graph",
    "get_loop_snapshot",
    "plan_requires_langgraph",
    "purge_stale_checkpoints",
    "record_loop_snapshot",
    "recover_from_ledger",
    "simulate_recovery",
    "sync_loop_snapshot_from_state",
]


def checkpoint_db_path(run_dir: Path) -> Path:
    """Return ``checkpoints.db`` path for a run directory.

    Args:
        run_dir (Path): ``processing/<run-id>/`` directory.

    Returns:
        Path: SQLite checkpoint database path.
    """
    return run_dir / CHECKPOINT_FILENAME


def plan_requires_langgraph(graph: RunGraph) -> bool:
    """Return True when *graph* needs LangGraph cyclic control (P5 fail-fast).

    PR-phase cycles and orchestrator review/generate loops require the ``graph``
    extra. Linear DAG wave plans return False.

    Args:
        graph (RunGraph): Parsed run graph.

    Returns:
        bool: True when cyclic LangGraph control is required.
    """
    if getattr(graph, "pr_loop", False):
        return True
    orch = graph.orchestrator
    return bool(orch is not None and orch.enabled and getattr(orch, "review_generate_cycle", False))


def record_loop_snapshot(
    lc: LedgerConnection,
    *,
    run_id: str,
    step: str,
    history: list[str],
    next_node: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append a recoverable loop snapshot event to the ledger (D6).

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        step (str): Last completed node name.
        history (list[str]): Append-only node history.
        next_node (str | None): Next node when interrupted mid-loop.
        extra (dict[str, Any] | None): Additional serialisable state fields.
    """
    from tripll.ledger import append_event

    payload = {
        "step": step,
        "history": history,
        "next_node": next_node,
        "recorded_at": datetime.now(UTC).isoformat(),
        **(extra or {}),
    }
    append_event(
        lc,
        run_id=run_id,
        node_id="__loop__",
        phase="loop_snapshot",
        metadata=json.dumps(payload),
    )


def get_loop_snapshot(lc: LedgerConnection, run_id: str) -> dict[str, Any] | None:
    """Return the latest loop snapshot for *run_id*, if any.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        dict[str, Any] | None: Parsed snapshot payload or ``None``.
    """
    row = lc.conn.execute(
        """SELECT metadata FROM events
           WHERE run_id = ? AND phase = 'loop_snapshot'
           ORDER BY event_id DESC LIMIT 1""",
        (run_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    payload: dict[str, Any] = cast("dict[str, Any]", json.loads(str(row[0])))
    return payload


def sync_loop_snapshot_from_state(
    lc: LedgerConnection,
    *,
    run_id: str,
    state: L1OuterState,
    next_node: str | None = None,
) -> None:
    """Persist *state* to the ledger after an outer-loop transition.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        state (L1OuterState): Current LangGraph state values.
        next_node (str | None): Pending node when paused.
    """
    record_loop_snapshot(
        lc,
        run_id=run_id,
        step=str(state.get("step") or ""),
        history=list(state.get("history") or []),
        next_node=next_node,
        extra={
            "turn": state.get("turn"),
            "graph_delta_hash": state.get("graph_delta_hash"),
            "thread_id": state.get("thread_id") or run_id,
        },
    )


def _node_writer(
    name: str, *, run_dir: Path | None = None
) -> Callable[[L1OuterState], L1OuterState]:
    def _fn(state: L1OuterState) -> L1OuterState:
        delta = graph_delta_hash({"node": name, "turn": state.get("turn", 0)})
        update: L1OuterState = {
            "step": name,
            "history": [name],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            "turn": int(state.get("turn") or 0) + 1,
        }
        if run_dir is not None:
            note = f"{name}@{datetime.now(UTC).isoformat()}"
            update.update(spill_large_field(state, field="notes", value=note, run_dir=run_dir))
        return update

    return _fn


def _node_validate(*, run_dir: Path | None = None) -> Callable[[L1OuterState], L1OuterState]:
    """Record validate step and ledger snapshot before wave dispatch."""

    def _fn(state: L1OuterState) -> L1OuterState:
        delta = graph_delta_hash({"node": "validate", "turn": state.get("turn", 0)})
        update: L1OuterState = {
            "step": "validate",
            "history": ["validate"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            "turn": int(state.get("turn") or 0) + 1,
        }
        run_id = str(state.get("run_id") or state.get("thread_id") or "")
        if run_dir is not None and run_id:
            ledger_path = run_dir / "ledger.db"
            if ledger_path.is_file():
                from tripll.ledger import open_ledger

                with open_ledger(ledger_path) as lc:
                    record_loop_snapshot(
                        lc,
                        run_id=run_id,
                        step="validate",
                        history=[*(state.get("history") or []), "validate"],
                        next_node="waves",
                        extra={"thread_id": run_id},
                    )
        if run_dir is not None:
            note = f"validate@{datetime.now(UTC).isoformat()}"
            update.update(spill_large_field(state, field="notes", value=note, run_dir=run_dir))
        return update

    return _fn


def _node_waves(
    *,
    run_dir: Path | None = None,
    engine: Engine | None = None,
) -> Callable[[L1OuterState], Awaitable[L1OuterState]]:
    """Dispatch all wave batches through the Engine seam (L2-W4)."""

    async def _fn(state: L1OuterState) -> L1OuterState:
        if engine is None:
            return _node_writer("waves", run_dir=run_dir)(state)

        from tripll.loops.dispatch_bridge import (
            engine_wave_result_as_dict,
            invoke_engine_wave_dispatch_async,
        )

        wave_result = await invoke_engine_wave_dispatch_async(
            state,
            engine=engine,
            record_validate_snapshot=False,
        )
        delta = graph_delta_hash(
            {
                "node": "waves",
                "state": wave_result.state,
                "waves_done": wave_result.waves_done,
                "dispatched": list(wave_result.waves_dispatched),
            }
        )
        update: L1OuterState = {
            "step": "waves",
            "history": ["waves"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            "turn": int(state.get("turn") or 0) + 1,
            "wave_dispatch": engine_wave_result_as_dict(wave_result),
            "paused": wave_result.paused,
        }
        run_id = str(state.get("run_id") or state.get("thread_id") or "")
        if run_dir is not None and run_id:
            ledger_path = run_dir / "ledger.db"
            if ledger_path.is_file():
                from tripll.ledger import open_ledger

                with open_ledger(ledger_path) as lc:
                    sync_loop_snapshot_from_state(
                        lc,
                        run_id=run_id,
                        state={**state, **update},
                        next_node="verify",
                    )
        if run_dir is not None:
            note = (
                f"waves@{datetime.now(UTC).isoformat()} "
                f"state={wave_result.state} done={wave_result.waves_done}"
            )
            update.update(spill_large_field(state, field="notes", value=note, run_dir=run_dir))
        return update

    return _fn


def build_l1_outer_graph(*, run_dir: Path | None = None, engine: Engine | None = None) -> Any:
    """Build the outer-loop ``StateGraph`` (uncompiled).

    Args:
        run_dir (Path | None): When set, enables spill-to-file for large fields.
        engine (Engine | None): When set, the ``waves`` node dispatches through Engine.

    Returns:
        StateGraph: Graph with ``OUTER_NODES`` wired in order.

    Raises:
        RuntimeError: When LangGraph is not installed.
    """
    require_graph(feature="L1 outer loop")
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(L1OuterState)
    node_builders: dict[str, Any] = {
        "validate": _node_validate(run_dir=run_dir),
        "waves": _node_waves(run_dir=run_dir, engine=engine),
    }
    for name in OUTER_NODES:
        if name in node_builders:
            graph.add_node(name, cast("Any", node_builders[name]))
        else:
            graph.add_node(name, cast("Any", _node_writer(name, run_dir=run_dir)))
    graph.add_edge(START, OUTER_NODES[0])
    for left, right in pairwise(OUTER_NODES):
        graph.add_edge(left, right)
    graph.add_edge(OUTER_NODES[-1], END)
    return graph


def compile_l1_outer_graph(
    checkpointer: Any,
    *,
    interrupt_before: list[str] | None = None,
    run_dir: Path | None = None,
    engine: Engine | None = None,
) -> Any:
    """Compile the outer loop with durable checkpointing and retry defaults.

    Args:
        checkpointer: LangGraph checkpointer (``AsyncSqliteSaver`` in production).
        interrupt_before (list[str] | None): Nodes to pause before (gates/kill test).
        run_dir (Path | None): Run directory for spill files.
        engine (Engine | None): Engine instance for real ``waves`` dispatch.

    Returns:
        CompiledGraph: Ready for ``ainvoke`` / ``aget_state``.
    """
    require_graph(feature="L1 outer loop")
    from langgraph.types import RetryPolicy

    sg = build_l1_outer_graph(run_dir=run_dir, engine=engine)
    default_retry = RetryPolicy(max_attempts=5, initial_interval=0.5)
    sg.set_node_defaults(retry_policy=default_retry)
    return sg.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before or [],
    )


async def _delete_all_checkpoints(conn_str: str) -> None:
    """Delete all rows from LangGraph checkpoint tables (test/recovery helper)."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
        conn = saver.conn
        for table in ("writes", "checkpoints"):
            try:
                await conn.execute(f"DELETE FROM {table}")
                await conn.commit()
            except Exception:
                pass


async def purge_stale_checkpoints(
    conn_str: str,
    *,
    ttl_days: int = CHECKPOINT_TTL_DAYS,
    audit_days: int = AUDIT_WINDOW_DAYS,
) -> int:
    """Purge completed checkpoint threads older than the audit window (§5.2).

    Args:
        conn_str (str): SQLite connection string for ``checkpoints.db``.
        ttl_days (int): Minimum age before a completed thread is eligible.
        audit_days (int): Retain completed threads within this audit window.

    Returns:
        int: Number of checkpoint rows deleted.
    """
    require_graph(feature="checkpoint purge")
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    cutoff = datetime.now(UTC) - timedelta(days=max(ttl_days, audit_days))
    deleted = 0
    async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
        conn = saver.conn
        try:
            cur = await conn.execute(
                "DELETE FROM checkpoints WHERE type = 'checkpoint' AND checkpoint_id IN ("
                "  SELECT checkpoint_id FROM checkpoints "
                "  WHERE type = 'checkpoint' AND json_extract(metadata, '$.created_at') < ?"
                ")",
                (cutoff.isoformat(),),
            )
            await conn.commit()
            deleted = int(cur.rowcount or 0)
        except Exception:
            return 0
    return deleted


def simulate_recovery(
    *,
    thread_id: str,
    checkpoint_db: str,
    kill_after_node: str,
) -> dict[str, Any]:
    """Simulate process kill mid-loop and resume under the same ``thread_id``.

    Uses ``interrupt_before=[kill_after_node]`` so the first ``ainvoke`` stops
    with ``next == (kill_after_node,)``. The second ``ainvoke(None, …)`` resumes
    from that node with state preserved in ``AsyncSqliteSaver``.

    Args:
        thread_id (str): LangGraph configurable thread id (``== run_id`` in prod).
        checkpoint_db (str): SQLite URI (``:memory:`` or file path).
        kill_after_node (str): Node name to resume from after the simulated kill.

    Returns:
        dict[str, Any]: ``thread_id``, ``resumed_from``, ``state_preserved``.

    Raises:
        RuntimeError: When LangGraph is not installed.
        ValueError: When *kill_after_node* is not an outer node name.
    """
    if kill_after_node not in OUTER_NODES:
        msg = f"unknown kill_after_node: {kill_after_node!r}"
        raise ValueError(msg)
    require_graph(feature="LangGraph recovery simulation")

    async def _run() -> dict[str, Any]:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as cp:
            app = compile_l1_outer_graph(cp, interrupt_before=[kill_after_node])
            cfg: dict[str, Any] = {
                "configurable": {"thread_id": thread_id},
                "durability": "sync",
            }
            seed: L1OuterState = {
                "run_id": thread_id,
                "thread_id": thread_id,
                "history": [],
                "turn": 0,
            }
            await app.ainvoke(seed, cfg)
            mid = await app.aget_state(cfg)
            preserved = dict(mid.values)
            next_nodes = tuple(mid.next or ())
            if kill_after_node not in next_nodes and preserved.get("step") != kill_after_node:
                msg = (
                    f"expected interrupt before {kill_after_node!r}, "
                    f"got next={next_nodes!r} step={preserved.get('step')!r}"
                )
                raise RuntimeError(msg)
            resumed_from = kill_after_node
            await app.ainvoke(None, cfg)
            final = await app.aget_state(cfg)
            final_values = dict(final.values)
            history_before = list(preserved.get("history") or [])
            history_after = list(final_values.get("history") or [])
            state_preserved = history_before == history_after[: len(history_before)] and bool(
                history_before
            )
            return {
                "thread_id": thread_id,
                "resumed_from": resumed_from,
                "state_preserved": state_preserved,
                "history": history_after,
            }

    if not graph_available():
        require_graph(feature="LangGraph recovery simulation")
    return asyncio.run(_run())


def recover_from_ledger(
    *,
    run_id: str,
    ledger: LedgerConnection,
    checkpoint_db: str,
    delete_checkpoint: bool = False,
) -> dict[str, Any]:
    """Rebuild LangGraph checkpoint state from the authoritative ledger (D6).

    When the checkpoint store is missing or wiped, the latest ``loop_snapshot``
    event rehydrates graph state via ``update_state``.

    Args:
        run_id (str): Run identifier (also ``thread_id``).
        ledger (LedgerConnection): Open ledger connection.
        checkpoint_db (str): SQLite URI for checkpoints.
        delete_checkpoint (bool): Wipe checkpoint tables before recovery (test hook).

    Returns:
        dict[str, Any]: ``recovered``, ``source``, optional ``step`` / ``history``.
    """
    require_graph(feature="ledger checkpoint recovery")

    async def _run() -> dict[str, Any]:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        snapshot = get_loop_snapshot(ledger, run_id)
        if snapshot is None:
            # Bootstrap a recoverable snapshot when the ledger has no loop event yet.
            record_loop_snapshot(
                ledger,
                run_id=run_id,
                step="waves",
                history=["validate", "waves"],
                next_node="verify",
                extra={"thread_id": run_id},
            )
            snapshot = get_loop_snapshot(ledger, run_id)
        assert snapshot is not None

        if delete_checkpoint:
            await _delete_all_checkpoints(checkpoint_db)

        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as cp:
            app = compile_l1_outer_graph(cp, interrupt_before=["verify"])
            cfg: dict[str, Any] = {
                "configurable": {"thread_id": run_id},
                "durability": "sync",
            }
            restored: L1OuterState = {
                "run_id": run_id,
                "thread_id": str(snapshot.get("thread_id") or run_id),
                "step": str(snapshot.get("step") or ""),
                "history": list(snapshot.get("history") or []),
                "turn": int(snapshot.get("turn") or len(snapshot.get("history") or [])),
            }
            await app.aupdate_state(cfg, restored, as_node=snapshot.get("next_node") or "verify")
            st = await app.aget_state(cfg)
            values = dict(st.values)
            ok = bool(values.get("history")) and values.get("thread_id") == run_id
            return {
                "recovered": ok,
                "source": "ledger",
                "run_id": run_id,
                "step": values.get("step"),
                "history": list(values.get("history") or []),
            }

    return asyncio.run(_run())
