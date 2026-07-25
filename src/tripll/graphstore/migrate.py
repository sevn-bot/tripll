"""Versioned schema migrations for the graph store."""

from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

SCHEMA_VERSION = 2


def _schema_sql() -> str:
    return files("tripll.graphstore").joinpath("schema.sql").read_text(encoding="utf-8")


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL
           )"""
    )


def current_version(conn: sqlite3.Connection) -> int:
    """Return the applied schema version, or 0 when uninitialised."""
    _ensure_meta(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the schema version after migration."""
    _ensure_meta(conn)
    version = current_version(conn)
    if version >= SCHEMA_VERSION:
        return version
    if version == 0:
        conn.executescript(_schema_sql())
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        return SCHEMA_VERSION
    if version == 1:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidate_relations (
              relation_id   TEXT PRIMARY KEY,
              predicate     TEXT NOT NULL,
              src_kind      TEXT NOT NULL,
              dst_kind      TEXT NOT NULL,
              count         INTEGER NOT NULL DEFAULT 1,
              evidence      TEXT,
              first_seen    TEXT NOT NULL,
              last_seen     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS candidate_relations_pred
              ON candidate_relations(predicate);
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        return SCHEMA_VERSION
    raise RuntimeError(f"unsupported schema version {version}; max supported is {SCHEMA_VERSION}")


def migrate_path(db_path: str | Path) -> sqlite3.Connection:
    """Open *db_path*, migrate, and return the connection."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn
