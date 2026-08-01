"""SQLite ledger write operations and connection open/migrate.

Exports:
    open_ledger — open (and migrate) a ledger at the given path.
    insert_run — create a new run row.
    insert_wave — create a wave row for a run.
    insert_attempt — record a new dispatch attempt.
    void_infra_attempt_count — decrement attempt_count after infra-classified dispatch.
    transition_run — atomic run state transition.
    transition_wave — atomic wave state transition (rejects terminal→non-terminal).
    delete_attempts_for_node — delete all attempt rows for one wave node.
    reset_wave_attempts — reset attempt_count and clear attempt history.
    end_attempt — set outcome + ended_at on an attempt row.
    append_event — append a per-node event row.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Literal

from loguru import logger

from tripll.ledger_schema import (
    DDL,
    TERMINAL_RUN_STATES,
    TERMINAL_WAVE_STATES,
    AttemptOutcome,
    LedgerConnection,
    RunState,
    WaveState,
    migrate_attempt_env_fingerprint,
    migrate_attempt_outcomes,
    migrate_cost_columns,
    migrate_event_attempt_n,
    migrate_event_metadata,
    migrate_quality_loop_wave_state,
    migrate_unverified_wave_state,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sum_attempt_costs(lc: LedgerConnection, run_id: str) -> float:
    """Return the sum of ``attempts.cost_usd`` for *run_id*."""
    row = lc.conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM attempts WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return float(row[0] or 0.0) if row is not None else 0.0


def _sync_run_cost_from_attempts(lc: LedgerConnection, run_id: str) -> None:
    """Refresh ``runs.cost_usd`` from the live attempt rows."""
    total = _sum_attempt_costs(lc, run_id)
    now = _now_iso()
    lc.conn.execute(
        "UPDATE runs SET cost_usd = ?, updated_at = ? WHERE run_id = ?",
        (total, now, run_id),
    )


def open_ledger(path: object) -> LedgerConnection:
    """Open (and migrate) the ledger at *path*.

    Creates the file if it does not exist; applies DDL idempotently (all tables
    use ``CREATE TABLE IF NOT EXISTS``).

    Args:
        path (Path | str): Filesystem path to the ``ledger.db`` file.
            Pass ``':memory:'`` for an in-memory ledger (tests).

    Returns:
        LedgerConnection: Open connection with schema applied.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> lc.conn.execute("SELECT count(*) FROM waves").fetchone()
        (0,)
        >>> lc.close()
    """
    conn = sqlite3.connect(str(path))
    conn.executescript(DDL)
    migrate_attempt_outcomes(conn)
    migrate_cost_columns(conn)
    migrate_event_attempt_n(conn)
    migrate_event_metadata(conn)
    migrate_unverified_wave_state(conn)
    migrate_quality_loop_wave_state(conn)
    migrate_attempt_env_fingerprint(conn)
    conn.commit()
    logger.debug("ledger: opened {}", path)
    return LedgerConnection(conn, path=None if path == ":memory:" else path)


def insert_run(
    lc: LedgerConnection,
    *,
    run_id: str,
    slug: str,
    source_mode: Literal["A", "B"],
    input_path: str,
) -> None:
    """Insert a new run row in the ``active`` state.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Unique run identifier.
        slug (str): Sanitised slug from source directory name.
        source_mode (Literal["A", "B"]): Parse mode.
        input_path (str): Absolute path to the original input directory.

    Raises:
        sqlite3.IntegrityError: If ``run_id`` already exists.

    Examples:
        >>> from tripll.ledger_query import get_run
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="test", source_mode="A", input_path="/tmp/x")
        >>> get_run(lc, "r1").state
        'active'
        >>> lc.close()
    """
    now = _now_iso()
    lc.conn.execute(
        """INSERT INTO runs (run_id, slug, source_mode, input_path, state, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'active', ?, ?)""",
        (run_id, slug, source_mode, input_path, now, now),
    )
    lc.conn.commit()
    logger.debug("ledger: inserted run {}", run_id)


def insert_wave(
    lc: LedgerConnection,
    *,
    node_id: str,
    run_id: str,
    plan_id: str,
    wave_id: str,
    lane: str,
    initial_state: WaveState = "queued",
) -> None:
    """Insert a wave row into ``waves``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        node_id (str): ``<plan_id>:<wave_id>`` composite key.
        run_id (str): Parent run.
        plan_id (str): Short plan slug.
        wave_id (str): Exact heading label (e.g. ``'W1'``).
        lane (str): Logical lane name.
        initial_state (WaveState): Starting state; defaults to ``'queued'``.

    Raises:
        sqlite3.IntegrityError: If ``(run_id, node_id)`` already exists.

    Examples:
        >>> from tripll.ledger_query import get_wave
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p1:W1", run_id="r1", plan_id="p1", wave_id="W1", lane="core")
        >>> get_wave(lc, "r1", "p1:W1").state
        'queued'
        >>> lc.close()
    """
    now = _now_iso()
    lc.conn.execute(
        """INSERT INTO waves
               (node_id, run_id, plan_id, wave_id, lane, state, attempt_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (node_id, run_id, plan_id, wave_id, lane, initial_state, now, now),
    )
    lc.conn.commit()
    logger.debug("ledger: inserted wave {}/{}", run_id, node_id)


def _maybe_sync_wave_transition(
    lc: LedgerConnection, run_id: str, node_id: str, new_state: WaveState
) -> None:
    if lc.path is None:
        return
    from pathlib import Path

    from tripll.graphstore.task_sync import TaskGraphWriter

    db_path = Path(str(lc.path)).parent / "graph.db"
    if not db_path.is_file():
        return
    writer = TaskGraphWriter(db_path)
    try:
        writer.sync_wave_transition(run_id=run_id, node_id=node_id, new_state=new_state)
    finally:
        writer.close()


def insert_attempt(
    lc: LedgerConnection,
    *,
    run_id: str,
    node_id: str,
    attempt_n: int,
    backend: str,
    brief_path: str | None = None,
    log_path: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    env_fingerprint_json: str | None = None,
    env_fingerprint_hash: str | None = None,
) -> str:
    """Record a new dispatch attempt; returns the generated ``attempt_id``.

    Also increments ``waves.attempt_count`` atomically.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.
        attempt_n (int): Attempt sequence number (1-based).
        backend (str): Backend name (e.g. ``'claude_code'``).
        brief_path (str | None): Path to the emitted dispatch brief JSON.
        log_path (str | None): Path to the attempt log file.
        model (str | None): Provider model id for task-graph sync.
        agent (str | None): Agent slug for task-graph sync.
        env_fingerprint_json (str | None): Serialised ``EnvFingerprint`` for ``RAN_IN``.
        env_fingerprint_hash (str | None): Stable fingerprint hash.

    Returns:
        str: The generated ``attempt_id`` UUID.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p1:W1", run_id="r1", plan_id="p1", wave_id="W1", lane="l")
        >>> aid = insert_attempt(lc, run_id="r1", node_id="p1:W1", attempt_n=1, backend="claude_code")
        >>> len(aid) > 0
        True
        >>> lc.close()
    """
    attempt_id = str(uuid.uuid4())
    now = _now_iso()
    with lc.conn:
        lc.conn.execute(
            """INSERT INTO attempts
                   (attempt_id, run_id, node_id, attempt_n, backend,
                    brief_path, log_path, started_at,
                    env_fingerprint_json, env_fingerprint_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                run_id,
                node_id,
                attempt_n,
                backend,
                brief_path,
                log_path,
                now,
                env_fingerprint_json,
                env_fingerprint_hash,
            ),
        )
        lc.conn.execute(
            """UPDATE waves SET attempt_count = attempt_count + 1, updated_at = ?
               WHERE run_id = ? AND node_id = ?""",
            (now, run_id, node_id),
        )
    logger.debug("ledger: inserted attempt {} for {}/{}", attempt_id, run_id, node_id)
    if lc.path is not None:
        from pathlib import Path

        from tripll.graphstore.task_sync import TaskGraphWriter

        db_path = Path(str(lc.path)).parent / "graph.db"
        if db_path.is_file():
            writer = TaskGraphWriter(db_path)
            try:
                writer.sync_attempt(
                    run_id=run_id,
                    node_id=node_id,
                    attempt_id=attempt_id,
                    attempt_n=attempt_n,
                    backend=backend,
                    model=model,
                    agent=agent,
                )
            finally:
                writer.close()
    return attempt_id


def void_infra_attempt_count(
    lc: LedgerConnection,
    *,
    run_id: str,
    node_id: str,
) -> None:
    """Decrement ``waves.attempt_count`` after an infra-classified dispatch (PROV-03).

    Infra failures must not consume a wave attempt slot. Call this after
    :func:`insert_attempt` when :func:`~tripll.adapters.failure_class.classify_dispatch`
    returns ``infra``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.
    """
    now = _now_iso()
    with lc.conn:
        lc.conn.execute(
            """UPDATE waves SET attempt_count = CASE WHEN attempt_count > 0
               THEN attempt_count - 1 ELSE 0 END, updated_at = ?
               WHERE run_id = ? AND node_id = ?""",
            (now, run_id, node_id),
        )


def transition_run(lc: LedgerConnection, run_id: str, new_state: RunState) -> None:
    """Atomically transition a run to *new_state*.

    Rejects transitions from terminal states (``done``, ``failed``) unless
    *new_state* is the same terminal state (idempotent).

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run to transition.
        new_state (RunState): Target state.

    Raises:
        ValueError: If the run is already in a different terminal state.
        KeyError: If *run_id* does not exist.

    Examples:
        >>> from tripll.ledger_query import get_run
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> transition_run(lc, "r1", "done")
        >>> get_run(lc, "r1").state
        'done'
        >>> lc.close()
    """
    from tripll.ledger_query import get_run

    row = get_run(lc, run_id)
    if row.state in TERMINAL_RUN_STATES and row.state != new_state:
        allowed_recovery = row.state == "failed" and new_state == "paused"
        if not allowed_recovery:
            raise ValueError(
                f"Cannot transition run {run_id!r} from terminal state {row.state!r} → {new_state!r}"
            )
    now = _now_iso()
    lc.conn.execute(
        "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
        (new_state, now, run_id),
    )
    lc.conn.commit()
    logger.debug("ledger: run {} → {}", run_id, new_state)


def transition_wave(lc: LedgerConnection, run_id: str, node_id: str, new_state: WaveState) -> None:
    """Atomically transition a wave to *new_state*.

    Terminal states (``done``, ``blocked``, ``deferred``) cannot be overwritten
    unless *new_state* is identical (idempotent re-entry).

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.
        new_state (WaveState): Target state.

    Raises:
        ValueError: If the wave is in a different terminal state.
        KeyError: If ``(run_id, node_id)`` does not exist.

    Examples:
        >>> from tripll.ledger_query import get_wave
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> transition_wave(lc, "r1", "p:W1", "dispatched")
        >>> transition_wave(lc, "r1", "p:W1", "running")
        >>> get_wave(lc, "r1", "p:W1").state
        'running'
        >>> lc.close()
    """
    from tripll.ledger_query import get_wave

    row = get_wave(lc, run_id, node_id)
    if row.state in TERMINAL_WAVE_STATES and row.state != new_state:
        allowed_recovery = row.state == "blocked" and new_state == "queued"
        if not allowed_recovery:
            raise ValueError(
                f"Cannot transition wave {node_id!r} in run {run_id!r} from terminal state "
                f"{row.state!r} → {new_state!r}"
            )
    now = _now_iso()
    lc.conn.execute(
        """UPDATE waves SET state = ?, updated_at = ?
           WHERE run_id = ? AND node_id = ?""",
        (new_state, now, run_id, node_id),
    )
    lc.conn.commit()
    logger.debug("ledger: wave {}/{} → {}", run_id, node_id, new_state)
    _maybe_sync_wave_transition(lc, run_id, node_id, new_state)


def delete_attempts_for_node(lc: LedgerConnection, run_id: str, node_id: str) -> int:
    """Delete all attempt rows for one wave node.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.

    Returns:
        int: Number of rows deleted.
    """
    cur = lc.conn.execute(
        "DELETE FROM attempts WHERE run_id = ? AND node_id = ?",
        (run_id, node_id),
    )
    lc.conn.commit()
    return int(cur.rowcount)


def reset_wave_attempts(lc: LedgerConnection, run_id: str, node_id: str) -> None:
    """Reset ``attempt_count`` and clear attempt history for a reactivated wave.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.
    """
    delete_attempts_for_node(lc, run_id, node_id)
    now = _now_iso()
    lc.conn.execute(
        """UPDATE waves SET attempt_count = 0, updated_at = ?
           WHERE run_id = ? AND node_id = ?""",
        (now, run_id, node_id),
    )
    _sync_run_cost_from_attempts(lc, run_id)
    lc.conn.commit()


def end_attempt(
    lc: LedgerConnection,
    attempt_id: str,
    *,
    outcome: AttemptOutcome,
    evidence: str | None = None,
    cost_usd: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Set ``outcome`` and ``ended_at`` on an attempt row.

    Args:
        lc (LedgerConnection): Open ledger connection.
        attempt_id (str): UUID of the attempt to close.
        outcome (AttemptOutcome): Final outcome.
        evidence (str | None): Optional failure message or scope-breach list.
        cost_usd (float | None): Provider-reported session cost.
        input_tokens (int | None): Input tokens when reported.
        output_tokens (int | None): Output tokens when reported.
    """
    now = _now_iso()
    row = lc.conn.execute(
        "SELECT run_id FROM attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    lc.conn.execute(
        """UPDATE attempts
           SET outcome = ?, evidence = ?, ended_at = ?,
               cost_usd = ?, input_tokens = ?, output_tokens = ?
           WHERE attempt_id = ?""",
        (outcome, evidence, now, cost_usd, input_tokens, output_tokens, attempt_id),
    )
    if row:
        _sync_run_cost_from_attempts(lc, str(row[0]))
    lc.conn.commit()
    logger.debug("ledger: attempt {} → {}", attempt_id, outcome)


def append_event(
    lc: LedgerConnection,
    *,
    run_id: str,
    node_id: str,
    phase: str,
    last_action: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    attempt_n: int | None = None,
    metadata: str | None = None,
) -> int:
    """Append one event row and return its ``event_id``.

    Events record per-node phase transitions and live action/usage updates
    emitted during streaming.  Callers should hold ``_ledger_lock`` before
    calling this from async engine code to avoid interleaving with other
    ledger-mutating sequences.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Wave node that emitted this event.
        phase (str): Node phase (``dispatched`` | ``running`` | ``verifying`` |
            ``done`` | ``failed`` | ``paused`` | ``orchestrator``).
        last_action (str | None): One-line operator summary from
            ``summarize_stream_line`` (streaming events only).
        input_tokens (int | None): Cumulative input tokens.
        output_tokens (int | None): Cumulative output tokens.
        cost_usd (float | None): Cumulative cost (USD).
        attempt_n (int | None): 1-based attempt number on ``dispatched`` events (W3).
        metadata (str | None): Optional JSON (orchestrator turn type + excerpt).

    Returns:
        int: The auto-assigned ``event_id``.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> eid = append_event(lc, run_id="r1", node_id="p:W1", phase="running")
        >>> eid >= 1
        True
        >>> lc.close()
    """
    now = _now_iso()
    cursor = lc.conn.execute(
        """INSERT INTO events
               (run_id, node_id, ts, phase, last_action, input_tokens, output_tokens,
                cost_usd, attempt_n, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            node_id,
            now,
            phase,
            last_action,
            input_tokens,
            output_tokens,
            cost_usd,
            attempt_n,
            metadata,
        ),
    )
    lc.conn.commit()
    return cursor.lastrowid or 0
