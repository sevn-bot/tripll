"""tripll.ledger — SQLite state ledger for wave-orchestrator runs.

Mirrors the atomic state-machine pattern from ``sevn.self_improve.jobs.store``.
Tables: ``runs``, ``waves``, ``attempts``, ``events``.  All transitions are
atomic (``BEGIN IMMEDIATE``) and idempotent on terminal states.

Wave state machine (from design-note.md §3)::

    queued → dispatched → running → verifying → done | failed | blocked | deferred
    gate_pending (is_review_gate=True; paused until tripll approve)

The ``events`` table records per-node phase transitions and live action/usage
updates during streaming.  It is the single source of truth for live status
consumed by ``tripll status --watch``, the FastAPI SSE feed (W4), and the
web dashboard (W5).

Exports:
    RunState — string-literal type for run states.
    WaveState — string-literal type for wave states.
    AttemptOutcome — string-literal type for attempt outcomes.
    RunRow — hydrated ``runs`` row.
    WaveRow — hydrated ``waves`` row.
    AttemptRow — hydrated ``attempts`` row.
    EventRow — hydrated ``events`` row.
    LedgerConnection — open connection + schema helpers.
    open_ledger — open (and migrate) a ledger at the given path.
    insert_run — create a new run row.
    insert_wave — create a wave row for a run.
    insert_attempt — record a new dispatch attempt.
    void_infra_attempt_count — decrement attempt_count after infra dispatch.
    transition_run — atomic run state transition.
    transition_wave — atomic wave state transition (rejects terminal→non-terminal).
    delete_attempts_for_node — delete all attempt rows for one wave node.
    reset_wave_attempts — reset attempt_count and clear attempt history.
    end_attempt — set outcome + ended_at on an attempt row.
    append_event — append a per-node event row.
    list_events — fetch events for a run, ordered by event_id (optionally paged).
    list_fired_exit_ids — distinct exit ids recorded via ``exit_fired`` events.
    latest_events_by_node — collapse events to one row per node_id (D2 hydration).
    ORCHESTRATOR_NODE_ID — synthetic node_id for orchestrator phase events.
    get_run — fetch one run row.
    get_run_cost — cumulative attempt cost (USD) for a run.
    get_run_cost_by_provider — per-backend cost rollup for a run.
    get_wave — fetch one wave row.
    list_waves — all wave rows for a run.
    list_attempts — all attempt rows for a (run_id, node_id) pair.
"""

from __future__ import annotations

from tripll.ledger_query import (
    get_run,
    get_run_cost,
    get_run_cost_by_provider,
    get_wave,
    latest_events_by_node,
    list_attempts,
    list_events,
    list_fired_exit_ids,
    list_waves,
)
from tripll.ledger_schema import (
    ORCHESTRATOR_NODE_ID,
    AttemptOutcome,
    AttemptRow,
    EventRow,
    LedgerConnection,
    RunRow,
    RunState,
    WaveRow,
    WaveState,
)
from tripll.ledger_store import (
    append_event,
    delete_attempts_for_node,
    end_attempt,
    insert_attempt,
    insert_run,
    insert_wave,
    open_ledger,
    reset_wave_attempts,
    transition_run,
    transition_wave,
    void_infra_attempt_count,
)

__all__ = [
    "ORCHESTRATOR_NODE_ID",
    "AttemptOutcome",
    "AttemptRow",
    "EventRow",
    "LedgerConnection",
    "RunRow",
    "RunState",
    "WaveRow",
    "WaveState",
    "append_event",
    "delete_attempts_for_node",
    "end_attempt",
    "get_run",
    "get_run_cost",
    "get_run_cost_by_provider",
    "get_wave",
    "insert_attempt",
    "insert_run",
    "insert_wave",
    "latest_events_by_node",
    "list_attempts",
    "list_events",
    "list_fired_exit_ids",
    "list_waves",
    "open_ledger",
    "reset_wave_attempts",
    "transition_run",
    "transition_wave",
    "void_infra_attempt_count",
]
