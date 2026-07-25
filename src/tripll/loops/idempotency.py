"""Idempotency keys and decide/commit split (§7.9.5, D14)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

__all__ = ["IdempotencyStore", "may_retry", "run_commit_node", "run_decide_node"]


@dataclass(frozen=True, slots=True)
class DecideReceipt:
    """Output of a decide node — intended mutation as data, no side effects."""

    kind: str
    intended: dict[str, Any]
    side_effects: list[str]


class IdempotencyStore:
    """SQLite-backed idempotency key store (``:memory:`` for tests)."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.commit()

    def record_commit(self, key: str, *, action: str) -> bool:
        """Record *key* before performing *action*; return False when already seen."""
        try:
            self._conn.execute(
                "INSERT INTO idempotency_keys (key, action) VALUES (?, ?)",
                (key, action),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def has_key(self, key: str) -> bool:
        """Return True when *key* was already recorded."""
        row = self._conn.execute(
            "SELECT 1 FROM idempotency_keys WHERE key = ?",
            (key,),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


def run_decide_node(node: dict[str, Any]) -> dict[str, Any]:
    """Run a decide node — compute intended mutation without side effects."""
    inputs = node.get("inputs") or {}
    return {
        "kind": str(node.get("kind") or "decide"),
        "intended": dict(inputs),
        "side_effects": [],
    }


def run_commit_node(
    store: IdempotencyStore,
    *,
    key: str,
    action: str,
    perform: Any | None = None,
) -> bool:
    """Run a commit node — record key first, then perform side effect once."""
    if not store.record_commit(key, action=action):
        return False
    if perform is not None:
        perform()
    return True


def may_retry(node: dict[str, Any]) -> bool:
    """Return False for destructive actions with retries disabled (D15)."""
    return not (node.get("destructive") and node.get("retries") == "disabled")
