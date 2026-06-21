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
    EventRow — hydrated ``events`` row.
    LedgerConnection — open connection + schema helpers.
    open_ledger — open (and migrate) a ledger at the given path.
    insert_run — create a new run row.
    insert_wave — create a wave row for a run.
    insert_attempt — record a new dispatch attempt.
    transition_run — atomic run state transition.
    transition_wave — atomic wave state transition (rejects terminal→non-terminal).
    end_attempt — set outcome + ended_at on an attempt row.
    append_event — append a per-node event row.
    list_events — fetch events for a run, ordered by event_id (optionally paged).
    latest_events_by_node — collapse events to one row per node_id (D2 hydration).
    ORCHESTRATOR_NODE_ID — synthetic node_id for orchestrator phase events.
    get_run — fetch one run row.
    get_wave — fetch one wave row.
    list_waves — all wave rows for a run.
    list_attempts — all attempt rows for a (run_id, node_id) pair.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from loguru import logger

# ---------------------------------------------------------------------------
# State types
# ---------------------------------------------------------------------------

RunState = Literal["active", "done", "failed", "paused"]
WaveState = Literal[
    "queued",
    "gate_pending",
    "dispatched",
    "running",
    "verifying",
    "done",
    "failed",
    "blocked",
    "deferred",
]
AttemptOutcome = Literal["done", "failed", "timed_out", "scope_breach", "quota_exhausted"]

# Synthetic node_id for orchestrator-mode turn events (phase=orchestrator, W3).
ORCHESTRATOR_NODE_ID = "__orchestrator__"

_TERMINAL_WAVE_STATES: frozenset[str] = frozenset({"done", "blocked", "deferred"})
_TERMINAL_RUN_STATES: frozenset[str] = frozenset({"done", "failed"})

# ---------------------------------------------------------------------------
# Row dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRow:
    """Hydrated ``runs`` row.

    Args:
        run_id (str): Primary key.
        slug (str): Sanitised slug from source directory name.
        source_mode (str): ``'A'`` or ``'B'``.
        input_path (str): Original input directory path.
        state (str): One of :data:`RunState`.
        created_at (str): ISO-8601 UTC timestamp.
        updated_at (str): ISO-8601 UTC timestamp.
        cost_usd (float): Cumulative provider cost in USD for the run.
        graph_json (str | None): Serialised ``RunGraph`` JSON, or ``None``.
    """

    run_id: str
    slug: str
    source_mode: str
    input_path: str
    state: str
    created_at: str
    updated_at: str
    graph_json: str | None = None
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class WaveRow:
    """Hydrated ``waves`` row.

    Args:
        node_id (str): ``<plan_id>:<wave_id>`` composite key.
        run_id (str): Parent run.
        plan_id (str): Short plan slug.
        wave_id (str): Exact heading label (e.g. ``'W1'``).
        lane (str): Logical lane name.
        state (str): One of :data:`WaveState`.
        attempt_count (int): Number of dispatch attempts made.
        created_at (str): ISO-8601 UTC timestamp.
        updated_at (str): ISO-8601 UTC timestamp.
    """

    node_id: str
    run_id: str
    plan_id: str
    wave_id: str
    lane: str
    state: str
    attempt_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AttemptRow:
    """Hydrated ``attempts`` row.

    Args:
        attempt_id (str): UUID primary key.
        run_id (str): Parent run.
        node_id (str): Parent wave node.
        attempt_n (int): Attempt sequence number (1-based).
        backend (str): ``'claude_code'`` | ``'cursor_local'`` | ``'cursor_cloud'``.
        brief_path (str | None): Path to the emitted dispatch brief JSON.
        log_path (str | None): Path to the attempt log file.
        started_at (str): ISO-8601 UTC timestamp.
        ended_at (str | None): ISO-8601 UTC timestamp when complete.
        outcome (str | None): One of :data:`AttemptOutcome`, or ``None`` if still running.
        evidence (str | None): Failure message or scope-breach file list.
        cost_usd (float | None): Provider-reported session cost when available.
        input_tokens (int | None): Input tokens when reported.
        output_tokens (int | None): Output tokens when reported.
    """

    attempt_id: str
    run_id: str
    node_id: str
    attempt_n: int
    backend: str
    brief_path: str | None
    log_path: str | None
    started_at: str
    ended_at: str | None
    outcome: str | None
    evidence: str | None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class EventRow:
    """Hydrated ``events`` row.

    Each row records a per-node phase transition or a live action/usage update
    during streaming.  The ``events`` table is the single source of truth for
    live status consumed by ``tripll status --watch``, the FastAPI SSE feed
    (W4), and the web dashboard (W5).

    Args:
        event_id (int): Auto-increment primary key; monotonically increasing.
        run_id (str): Parent run.
        node_id (str): Wave node that emitted this event.
        ts (str): ISO-8601 UTC timestamp.
        phase (str): Node phase at event time (``dispatched`` | ``running`` |
            ``verifying`` | ``done`` | ``failed`` | ``paused``).
        last_action (str | None): One-line operator summary from
            ``summarize_stream_line`` (only set on streaming events).
        input_tokens (int | None): Cumulative input tokens at event time.
        output_tokens (int | None): Cumulative output tokens at event time.
        cost_usd (float | None): Cumulative cost (USD) at event time.
        attempt_n (int | None): Dispatch attempt number when ``phase=dispatched``
            (W3 SSE hint; optional on other phases).
        metadata (str | None): Optional JSON payload (orchestrator turn type +
            markdown excerpt ≤500 chars for SSE; W3).
    """

    event_id: int
    run_id: str
    node_id: str
    ts: str
    phase: str
    last_action: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    attempt_n: int | None = None
    metadata: str | None = None


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    slug         TEXT NOT NULL,
    source_mode  TEXT NOT NULL CHECK (source_mode IN ('A', 'B')),
    input_path   TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'active'
                     CHECK (state IN ('active', 'done', 'failed', 'paused')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    graph_json   TEXT
);

CREATE TABLE IF NOT EXISTS waves (
    node_id       TEXT NOT NULL,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    plan_id       TEXT NOT NULL,
    wave_id       TEXT NOT NULL,
    lane          TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'queued'
                      CHECK (state IN (
                          'queued', 'gate_pending', 'dispatched',
                          'running', 'verifying',
                          'done', 'failed', 'blocked', 'deferred'
                      )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (run_id, node_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    node_id    TEXT NOT NULL,
    attempt_n  INTEGER NOT NULL,
    backend    TEXT NOT NULL,
    brief_path TEXT,
    log_path   TEXT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    outcome    TEXT CHECK (outcome IN ('done', 'failed', 'timed_out', 'scope_breach', 'quota_exhausted')),
    evidence   TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    node_id       TEXT NOT NULL,
    ts            TEXT NOT NULL,
    phase         TEXT NOT NULL,
    last_action   TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL
);

CREATE INDEX IF NOT EXISTS idx_waves_run_state ON waves (run_id, state);
CREATE INDEX IF NOT EXISTS idx_attempts_run_node ON attempts (run_id, node_id);
CREATE INDEX IF NOT EXISTS idx_events_run_ts ON events (run_id, ts);
"""


# ---------------------------------------------------------------------------
# Connection wrapper
# ---------------------------------------------------------------------------


class LedgerConnection:
    """Thin wrapper around a :class:`sqlite3.Connection` for this ledger schema.

    Prefer :func:`open_ledger` to construct.

    Args:
        conn (sqlite3.Connection): Already-open connection with schema applied.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.NamedTemporaryFile(suffix=".db") as f:
        ...     lc = open_ledger(Path(f.name))
        ...     lc.conn.execute("SELECT count(*) FROM runs").fetchone()
        (0,)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def close(self) -> None:
        """Close the underlying connection."""
        self.conn.close()

    def __enter__(self) -> LedgerConnection:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Open / migrate
# ---------------------------------------------------------------------------


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
    conn.executescript(_DDL)
    _migrate_attempt_outcomes(conn)
    _migrate_cost_columns(conn)
    _migrate_event_attempt_n(conn)
    _migrate_event_metadata(conn)
    conn.commit()
    logger.debug("ledger: opened {}", path)
    return LedgerConnection(conn)


def _migrate_attempt_outcomes(conn: sqlite3.Connection) -> None:
    """Rebuild ``attempts`` when the outcome CHECK lacks ``quota_exhausted``."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='attempts'"
    ).fetchone()
    if not row or not row[0] or "quota_exhausted" in row[0]:
        return
    conn.executescript(
        """
        CREATE TABLE attempts_new (
            attempt_id TEXT PRIMARY KEY,
            run_id     TEXT NOT NULL REFERENCES runs(run_id),
            node_id    TEXT NOT NULL,
            attempt_n  INTEGER NOT NULL,
            backend    TEXT NOT NULL,
            brief_path TEXT,
            log_path   TEXT,
            started_at TEXT NOT NULL,
            ended_at   TEXT,
            outcome    TEXT CHECK (outcome IN (
                'done', 'failed', 'timed_out', 'scope_breach', 'quota_exhausted'
            )),
            evidence   TEXT
        );
        INSERT INTO attempts_new SELECT * FROM attempts;
        DROP TABLE attempts;
        ALTER TABLE attempts_new RENAME TO attempts;
        CREATE INDEX IF NOT EXISTS idx_attempts_run_node ON attempts (run_id, node_id);
        """
    )


def _migrate_cost_columns(conn: sqlite3.Connection) -> None:
    """Add cost/token columns to ``runs`` and ``attempts`` when missing."""
    run_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if "cost_usd" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0")
    att_cols = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
    if "cost_usd" not in att_cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN cost_usd REAL")
    if "input_tokens" not in att_cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN input_tokens INTEGER")
    if "output_tokens" not in att_cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN output_tokens INTEGER")


def _migrate_event_attempt_n(conn: sqlite3.Connection) -> None:
    """Add optional ``attempt_n`` to ``events`` for W3 SSE dispatch hints."""
    evt_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "attempt_n" not in evt_cols:
        conn.execute("ALTER TABLE events ADD COLUMN attempt_n INTEGER")


def _migrate_event_metadata(conn: sqlite3.Connection) -> None:
    """Add optional ``metadata`` JSON text to ``events`` for orchestrator turns (W3)."""
    evt_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "metadata" not in evt_cols:
        conn.execute("ALTER TABLE events ADD COLUMN metadata TEXT")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


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


def insert_attempt(
    lc: LedgerConnection,
    *,
    run_id: str,
    node_id: str,
    attempt_n: int,
    backend: str,
    brief_path: str | None = None,
    log_path: str | None = None,
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
                    brief_path, log_path, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (attempt_id, run_id, node_id, attempt_n, backend, brief_path, log_path, now),
        )
        lc.conn.execute(
            """UPDATE waves SET attempt_count = attempt_count + 1, updated_at = ?
               WHERE run_id = ? AND node_id = ?""",
            (now, run_id, node_id),
        )
    logger.debug("ledger: inserted attempt {} for {}/{}", attempt_id, run_id, node_id)
    return attempt_id


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
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> transition_run(lc, "r1", "done")
        >>> get_run(lc, "r1").state
        'done'
        >>> lc.close()
    """
    row = get_run(lc, run_id)
    if row.state in _TERMINAL_RUN_STATES and row.state != new_state:
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
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> transition_wave(lc, "r1", "p:W1", "dispatched")
        >>> transition_wave(lc, "r1", "p:W1", "running")
        >>> get_wave(lc, "r1", "p:W1").state
        'running'
        >>> lc.close()
    """
    row = get_wave(lc, run_id, node_id)
    if row.state in _TERMINAL_WAVE_STATES and row.state != new_state:
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
    if row and cost_usd and cost_usd > 0:
        lc.conn.execute(
            "UPDATE runs SET cost_usd = cost_usd + ?, updated_at = ? WHERE run_id = ?",
            (cost_usd, now, row[0]),
        )
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


def list_events(
    lc: LedgerConnection,
    run_id: str,
    *,
    after_event_id: int = 0,
) -> list[EventRow]:
    """Return events for *run_id* ordered by ``event_id``.

    Reads are unlocked under WAL — callers do not need to hold
    ``_ledger_lock``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        after_event_id (int): Return only events with ``event_id > after_event_id``
            (default 0 = return all).  Used by the SSE/poll layer to page from
            a ``Last-Event-ID`` cursor.

    Returns:
        list[EventRow]: Events ordered by ``event_id`` ascending.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> _ = append_event(lc, run_id="r1", node_id="p:W1", phase="running")
        >>> _ = append_event(lc, run_id="r1", node_id="p:W1", phase="done", cost_usd=0.05)
        >>> evts = list_events(lc, "r1")
        >>> [e.phase for e in evts]
        ['running', 'done']
        >>> paged = list_events(lc, "r1", after_event_id=evts[0].event_id)
        >>> len(paged)
        1
        >>> paged[0].phase
        'done'
        >>> lc.close()
    """
    rows = lc.conn.execute(
        """SELECT event_id, run_id, node_id, ts, phase,
                  last_action, input_tokens, output_tokens, cost_usd, attempt_n, metadata
           FROM events
           WHERE run_id = ? AND event_id > ?
           ORDER BY event_id""",
        (run_id, after_event_id),
    ).fetchall()
    return [
        EventRow(
            event_id=int(r[0]),
            run_id=str(r[1]),
            node_id=str(r[2]),
            ts=str(r[3]),
            phase=str(r[4]),
            last_action=str(r[5]) if r[5] is not None else None,
            input_tokens=int(r[6]) if r[6] is not None else None,
            output_tokens=int(r[7]) if r[7] is not None else None,
            cost_usd=float(r[8]) if r[8] is not None else None,
            attempt_n=int(r[9]) if r[9] is not None else None,
            metadata=str(r[10]) if r[10] is not None else None,
        )
        for r in rows
    ]


def latest_events_by_node(lc: LedgerConnection, run_id: str) -> dict[str, EventRow]:
    """Collapse append-only events to one row per ``node_id`` (D2).

    Uses the same algorithm as ``cli._status_watch``: the latest event sets
    ``phase`` and ``last_action``; cumulative ``input_tokens``, ``output_tokens``,
    and ``cost_usd`` carry forward from the last non-``None`` value per field.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        dict[str, EventRow]: Latest hydrated row keyed by ``node_id``.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> _ = append_event(
        ...     lc, run_id="r1", node_id="p:W1", phase="running",
        ...     last_action="editing foo", input_tokens=10, output_tokens=5,
        ... )
        >>> _ = append_event(
        ...     lc, run_id="r1", node_id="p:W1", phase="running",
        ...     input_tokens=20, output_tokens=15, cost_usd=0.01,
        ... )
        >>> latest = latest_events_by_node(lc, "r1")
        >>> latest["p:W1"].phase
        'running'
        >>> latest["p:W1"].input_tokens
        20
        >>> latest["p:W1"].cost_usd
        0.01
        >>> lc.close()
    """
    collapsed: dict[str, EventRow] = {}
    for e in list_events(lc, run_id):
        prev = collapsed.get(e.node_id)
        collapsed[e.node_id] = EventRow(
            event_id=e.event_id,
            run_id=run_id,
            node_id=e.node_id,
            ts=e.ts,
            phase=e.phase,
            last_action=(
                e.last_action.strip()
                if e.last_action
                else (prev.last_action if prev is not None else None)
            ),
            input_tokens=(
                e.input_tokens
                if e.input_tokens is not None
                else (prev.input_tokens if prev else None)
            ),
            output_tokens=(
                e.output_tokens
                if e.output_tokens is not None
                else (prev.output_tokens if prev else None)
            ),
            cost_usd=e.cost_usd if e.cost_usd is not None else (prev.cost_usd if prev else None),
            attempt_n=(
                e.attempt_n if e.attempt_n is not None else (prev.attempt_n if prev else None)
            ),
            metadata=(e.metadata if e.metadata is not None else (prev.metadata if prev else None)),
        )
    return collapsed


def get_run_cost(lc: LedgerConnection, run_id: str) -> float:
    """Return cumulative provider cost (USD) recorded for *run_id*.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.

    Returns:
        float: Total ``cost_usd`` for the run (0 when unset).
    """
    row = lc.conn.execute("SELECT cost_usd FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"Run not found: {run_id!r}")
    return float(row[0] or 0.0)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def get_run(lc: LedgerConnection, run_id: str) -> RunRow:
    """Fetch a single run row.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.

    Returns:
        RunRow: Hydrated row.

    Raises:
        KeyError: If *run_id* does not exist.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="s", source_mode="B", input_path="/x")
        >>> get_run(lc, "r1").slug
        's'
        >>> lc.close()
    """
    row = lc.conn.execute(
        "SELECT run_id, slug, source_mode, input_path, state, created_at, updated_at, graph_json, cost_usd "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Run not found: {run_id!r}")
    return RunRow(
        run_id=str(row[0]),
        slug=str(row[1]),
        source_mode=str(row[2]),
        input_path=str(row[3]),
        state=str(row[4]),
        created_at=str(row[5]),
        updated_at=str(row[6]),
        graph_json=str(row[7]) if row[7] is not None else None,
        cost_usd=float(row[8] or 0.0),
    )


def get_wave(lc: LedgerConnection, run_id: str, node_id: str) -> WaveRow:
    """Fetch a single wave row.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Wave node identifier.

    Returns:
        WaveRow: Hydrated row.

    Raises:
        KeyError: If ``(run_id, node_id)`` does not exist.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W0", run_id="r1", plan_id="p", wave_id="W0", lane="l")
        >>> get_wave(lc, "r1", "p:W0").wave_id
        'W0'
        >>> lc.close()
    """
    row = lc.conn.execute(
        """SELECT node_id, run_id, plan_id, wave_id, lane, state, attempt_count,
                  created_at, updated_at
           FROM waves WHERE run_id = ? AND node_id = ?""",
        (run_id, node_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"Wave not found: run={run_id!r} node={node_id!r}")
    return WaveRow(
        node_id=str(row[0]),
        run_id=str(row[1]),
        plan_id=str(row[2]),
        wave_id=str(row[3]),
        lane=str(row[4]),
        state=str(row[5]),
        attempt_count=int(str(row[6])),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def list_waves(lc: LedgerConnection, run_id: str) -> list[WaveRow]:
    """Return all wave rows for *run_id*, ordered by ``created_at``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        list[WaveRow]: All wave rows for this run.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W0", run_id="r1", plan_id="p", wave_id="W0", lane="l")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> [w.wave_id for w in list_waves(lc, "r1")]
        ['W0', 'W1']
        >>> lc.close()
    """
    rows = lc.conn.execute(
        """SELECT node_id, run_id, plan_id, wave_id, lane, state, attempt_count,
                  created_at, updated_at
           FROM waves WHERE run_id = ? ORDER BY created_at""",
        (run_id,),
    ).fetchall()
    return [
        WaveRow(
            node_id=str(r[0]),
            run_id=str(r[1]),
            plan_id=str(r[2]),
            wave_id=str(r[3]),
            lane=str(r[4]),
            state=str(r[5]),
            attempt_count=int(str(r[6])),
            created_at=str(r[7]),
            updated_at=str(r[8]),
        )
        for r in rows
    ]


def list_attempts(lc: LedgerConnection, run_id: str, node_id: str) -> list[AttemptRow]:
    """Return all attempt rows for a ``(run_id, node_id)`` pair, ordered by ``attempt_n``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.

    Returns:
        list[AttemptRow]: All attempt rows for this wave.

    Examples:
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> _ = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
        >>> _ = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=2, backend="claude_code")
        >>> len(list_attempts(lc, "r1", "p:W1"))
        2
        >>> lc.close()
    """
    rows = lc.conn.execute(
        """SELECT attempt_id, run_id, node_id, attempt_n, backend,
                  brief_path, log_path, started_at, ended_at, outcome, evidence,
                  cost_usd, input_tokens, output_tokens
           FROM attempts
           WHERE run_id = ? AND node_id = ?
           ORDER BY attempt_n""",
        (run_id, node_id),
    ).fetchall()
    return [
        AttemptRow(
            attempt_id=str(r[0]),
            run_id=str(r[1]),
            node_id=str(r[2]),
            attempt_n=int(str(r[3])),
            backend=str(r[4]),
            brief_path=str(r[5]) if r[5] is not None else None,
            log_path=str(r[6]) if r[6] is not None else None,
            started_at=str(r[7]),
            ended_at=str(r[8]) if r[8] is not None else None,
            outcome=str(r[9]) if r[9] is not None else None,
            evidence=str(r[10]) if r[10] is not None else None,
            cost_usd=float(r[11]) if r[11] is not None else None,
            input_tokens=int(r[12]) if r[12] is not None else None,
            output_tokens=int(r[13]) if r[13] is not None else None,
        )
        for r in rows
    ]
