"""SQLite ledger schema: state types, row models, DDL, and migrations.

Exports:
    RunState — string-literal type for run states.
    WaveState — string-literal type for wave states.
    AttemptOutcome — string-literal type for attempt outcomes.
    ORCHESTRATOR_NODE_ID — synthetic node_id for orchestrator phase events.
    RunRow — hydrated ``runs`` row.
    WaveRow — hydrated ``waves`` row.
    AttemptRow — hydrated ``attempts`` row.
    EventRow — hydrated ``events`` row.
    LedgerConnection — open connection + schema helpers.
    DDL — idempotent schema script applied by :func:`tripll.ledger_store.open_ledger`.
    migrate_attempt_outcomes — rebuild ``attempts`` when outcome CHECK is stale.
    migrate_cost_columns — add cost/token columns when missing.
    migrate_event_attempt_n — add ``attempt_n`` to ``events``.
    migrate_event_metadata — add ``metadata`` JSON to ``events``.
    migrate_unverified_wave_state — rebuild ``waves`` for ``unverified`` state.
    migrate_quality_loop_wave_state — rebuild ``waves`` for ``quality_loop`` state.
    migrate_attempt_env_fingerprint — add env fingerprint columns to ``attempts``.
    TERMINAL_WAVE_STATES — terminal wave states for transition guards.
    TERMINAL_RUN_STATES — terminal run states for transition guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import sqlite3

RunState = Literal["active", "done", "failed", "paused"]
WaveState = Literal[
    "queued",
    "gate_pending",
    "dispatched",
    "running",
    "quality_loop",
    "verifying",
    "unverified",
    "done",
    "failed",
    "blocked",
    "deferred",
]
AttemptOutcome = Literal["done", "failed", "timed_out", "scope_breach", "quota_exhausted"]

ORCHESTRATOR_NODE_ID = "__orchestrator__"

TERMINAL_WAVE_STATES: frozenset[str] = frozenset({"done", "blocked", "deferred"})
TERMINAL_RUN_STATES: frozenset[str] = frozenset({"done", "failed"})


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
        env_fingerprint_json (str | None): Serialised 13-field ``EnvFingerprint``.
        env_fingerprint_hash (str | None): Stable hash for graph ``RAN_IN`` edge.
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
    env_fingerprint_json: str | None = None
    env_fingerprint_hash: str | None = None


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


DDL = """
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
                          'running', 'quality_loop', 'verifying', 'unverified',
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


class LedgerConnection:
    """Thin wrapper around a :class:`sqlite3.Connection` for this ledger schema.

    Prefer :func:`tripll.ledger_store.open_ledger` to construct.

    Args:
        conn (sqlite3.Connection): Already-open connection with schema applied.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from tripll.ledger_store import open_ledger
        >>> with tempfile.NamedTemporaryFile(suffix=".db") as f:
        ...     lc = open_ledger(Path(f.name))
        ...     lc.conn.execute("SELECT count(*) FROM runs").fetchone()
        (0,)
    """

    def __init__(self, conn: sqlite3.Connection, *, path: object | None = None) -> None:
        self.conn = conn
        self.path = path

    def close(self) -> None:
        """Close the underlying connection."""
        self.conn.close()

    def __enter__(self) -> LedgerConnection:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def migrate_attempt_outcomes(conn: sqlite3.Connection) -> None:
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


def migrate_cost_columns(conn: sqlite3.Connection) -> None:
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


def migrate_event_attempt_n(conn: sqlite3.Connection) -> None:
    """Add optional ``attempt_n`` to ``events`` for W3 SSE dispatch hints."""
    evt_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "attempt_n" not in evt_cols:
        conn.execute("ALTER TABLE events ADD COLUMN attempt_n INTEGER")


def migrate_event_metadata(conn: sqlite3.Connection) -> None:
    """Add optional ``metadata`` JSON text to ``events`` for orchestrator turns (W3)."""
    evt_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "metadata" not in evt_cols:
        conn.execute("ALTER TABLE events ADD COLUMN metadata TEXT")


def migrate_quality_loop_wave_state(conn: sqlite3.Connection) -> None:
    """Rebuild ``waves`` when the state CHECK lacks ``quality_loop``."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='waves'"
    ).fetchone()
    if not row or not row[0] or "quality_loop" in row[0]:
        return
    conn.executescript(
        """
        CREATE TABLE waves_new (
            node_id       TEXT NOT NULL,
            run_id        TEXT NOT NULL REFERENCES runs(run_id),
            plan_id       TEXT NOT NULL,
            wave_id       TEXT NOT NULL,
            lane          TEXT NOT NULL,
            state         TEXT NOT NULL DEFAULT 'queued'
                              CHECK (state IN (
                                  'queued', 'gate_pending', 'dispatched',
                                  'running', 'quality_loop', 'verifying', 'unverified',
                                  'done', 'failed', 'blocked', 'deferred'
                              )),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (run_id, node_id)
        );
        INSERT INTO waves_new SELECT * FROM waves;
        DROP TABLE waves;
        ALTER TABLE waves_new RENAME TO waves;
        CREATE INDEX IF NOT EXISTS idx_waves_run_state ON waves (run_id, state);
        """
    )


def migrate_unverified_wave_state(conn: sqlite3.Connection) -> None:
    """Rebuild ``waves`` when the state CHECK lacks ``unverified`` (W7)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='waves'"
    ).fetchone()
    if not row or not row[0] or "unverified" in row[0]:
        return
    conn.executescript(
        """
        CREATE TABLE waves_new (
            node_id       TEXT NOT NULL,
            run_id        TEXT NOT NULL REFERENCES runs(run_id),
            plan_id       TEXT NOT NULL,
            wave_id       TEXT NOT NULL,
            lane          TEXT NOT NULL,
            state         TEXT NOT NULL DEFAULT 'queued'
                              CHECK (state IN (
                                  'queued', 'gate_pending', 'dispatched',
                                  'running', 'quality_loop', 'verifying', 'unverified',
                                  'done', 'failed', 'blocked', 'deferred'
                              )),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (run_id, node_id)
        );
        INSERT INTO waves_new SELECT * FROM waves;
        DROP TABLE waves;
        ALTER TABLE waves_new RENAME TO waves;
        CREATE INDEX IF NOT EXISTS idx_waves_run_state ON waves (run_id, state);
        """
    )


def migrate_attempt_env_fingerprint(conn: sqlite3.Connection) -> None:
    """Add ``EnvFingerprint`` columns to ``attempts`` (§7.9.2)."""
    att_cols = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
    if "env_fingerprint_json" not in att_cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN env_fingerprint_json TEXT")
    if "env_fingerprint_hash" not in att_cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN env_fingerprint_hash TEXT")
