"""Local JSONL and SQLite trace sinks (TRACE-04).

Exports:
    JsonlTraceSink — daily-rotated ``<YYYY-MM-DD>.jsonl`` writer.
    SqliteTraceSink — ``traces.db`` with WAL and retention purge.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime sink paths

from tripll.tracing.sink import TraceEvent, cap_attrs

ClockFn = Callable[[], float]


def _default_clock() -> float:
    return time.time()


class JsonlTraceSink:
    """Append-only JSONL writer under a run ``traces/`` directory."""

    def __init__(
        self,
        traces_dir: Path,
        *,
        clock: ClockFn | None = None,
    ) -> None:
        """Write daily files under *traces_dir*."""
        self._dir = traces_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock or _default_clock
        self._current_day: str | None = None
        self._handle: Path | None = None

    def _path_for_now(self) -> Path:
        day = datetime.fromtimestamp(self._clock(), tz=UTC).strftime("%Y-%m-%d")
        if day != self._current_day:
            self._current_day = day
            self._handle = self._dir / f"{day}.jsonl"
        assert self._handle is not None
        return self._handle

    def emit(self, event: TraceEvent) -> None:
        """Append one JSON line for *event*."""
        try:
            payload = {
                "kind": event.kind,
                "span_id": event.span_id,
                "parent_span_id": event.parent_span_id,
                "run_id": event.run_id,
                "node_id": event.node_id,
                "attempt_id": event.attempt_id,
                "ts_start_ns": event.ts_start_ns,
                "ts_end_ns": event.ts_end_ns,
                "status": event.status,
                "attrs": cap_attrs(event.attrs),
            }
            path = self._path_for_now()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, default=str, separators=(",", ":")) + "\n")
        except Exception:
            return

    def flush(self) -> None:
        """No buffered state."""

    def close(self) -> None:
        """No persistent handles."""


class SqliteTraceSink:
    """SQLite trace store with WAL mode and retention purge."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS trace_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        span_id TEXT NOT NULL,
        parent_span_id TEXT,
        run_id TEXT,
        node_id TEXT,
        attempt_id TEXT,
        ts_start_ns INTEGER NOT NULL,
        ts_end_ns INTEGER,
        status TEXT NOT NULL,
        attrs TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_trace_events_kind ON trace_events(kind);
    CREATE INDEX IF NOT EXISTS idx_trace_events_run ON trace_events(run_id);
    """

    def __init__(
        self,
        traces_dir: Path,
        *,
        retention_days: int = 30,
        clock: ClockFn | None = None,
    ) -> None:
        """Open ``traces.db`` under *traces_dir*."""
        traces_dir.mkdir(parents=True, exist_ok=True)
        self._path = traces_dir / "traces.db"
        self._retention_days = max(1, retention_days)
        self._clock = clock or _default_clock
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()
        self._purge_old()

    def _purge_old(self) -> None:
        try:
            cutoff_ns = int((self._clock() - self._retention_days * 86400) * 1_000_000_000)
            self._conn.execute("DELETE FROM trace_events WHERE ts_start_ns < ?", (cutoff_ns,))
            self._conn.commit()
        except Exception:
            return

    def emit(self, event: TraceEvent) -> None:
        """Insert *event* into ``trace_events``."""
        try:
            attrs_json = json.dumps(cap_attrs(event.attrs), default=str, separators=(",", ":"))
            self._conn.execute(
                """
                INSERT INTO trace_events (
                    kind, span_id, parent_span_id, run_id, node_id, attempt_id,
                    ts_start_ns, ts_end_ns, status, attrs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.kind,
                    event.span_id,
                    event.parent_span_id,
                    event.run_id,
                    event.node_id,
                    event.attempt_id,
                    event.ts_start_ns,
                    event.ts_end_ns,
                    event.status,
                    attrs_json,
                ),
            )
            self._conn.commit()
        except Exception:
            return

    def flush(self) -> None:
        """Commit any pending transaction."""
        try:
            self._conn.commit()
        except Exception:
            return

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            return
