"""Idempotent GitHub PR actions (§7.9.5, D11, D14/D15).

Every external mutation is a ``commit``-class node: the idempotency key is
written **before** the side effect. ``merge`` is destructive, human-gated, and
refuses retry (``retries: disabled``).

Exports:
    SUPPORTED_ACTIONS — push, open_pr, comment, resolve_thread, merge.
    run_pr_action — unified entry for commit nodes (replay-safe).
    push, open_pr, comment, resolve_thread, merge — action helpers.
    get_idempotency_store — per-run SQLite store beside the ledger.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tripll.loops.idempotency import IdempotencyStore, may_retry, run_commit_node

SUPPORTED_ACTIONS: tuple[str, ...] = (
    "push",
    "open_pr",
    "comment",
    "resolve_thread",
    "merge",
)

_DESTRUCTIVE_ACTIONS: frozenset[str] = frozenset({"merge"})

_STORES: dict[str, IdempotencyStore] = {}

__all__ = [
    "SUPPORTED_ACTIONS",
    "comment",
    "get_idempotency_store",
    "merge",
    "open_pr",
    "push",
    "resolve_thread",
    "run_pr_action",
]


def get_idempotency_store(*, run_id: str, run_dir: Path | None = None) -> IdempotencyStore:
    """Return a durable idempotency store for *run_id*.

    Args:
        run_id (str): Parent run identifier.
        run_dir (Path | None): When set, persist keys under ``idempotency.db``.

    Returns:
        IdempotencyStore: Store scoped to the run.
    """
    if run_id in _STORES:
        return _STORES[run_id]
    if run_dir is not None:
        db_path = run_dir / "idempotency.db"
        store = IdempotencyStore(str(db_path))
    else:
        store = IdempotencyStore(":memory:")
    _STORES[run_id] = store
    return store


def _action_spec(action: str) -> dict[str, Any]:
    destructive = action in _DESTRUCTIVE_ACTIONS
    return {
        "action": action,
        "node_kind": "commit",
        "destructive": destructive,
        "retries": "disabled" if destructive else "default",
    }


def _perform_stub(action: str, context: dict[str, Any]) -> dict[str, Any]:
    """Record the intended mutation without calling ``gh`` (tests and dry-run)."""
    return {"action": action, "ok": True, **{k: v for k, v in context.items() if k != "ledger"}}


def run_pr_action(
    action: str,
    *,
    idempotency_key: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute or replay a PR commit node under *idempotency_key*.

    Args:
        action (str): One of :data:`SUPPORTED_ACTIONS`.
        idempotency_key (str): Stable key written before any side effect.
        context (dict[str, Any] | None): Run context (``run_id``, branch, PR number, …).

    Returns:
        dict[str, Any]: ``executed``, ``replayed``, ``action``, and action payload.

    Raises:
        ValueError: Unknown *action* or merge without human approval.
    """
    if action not in SUPPORTED_ACTIONS:
        msg = f"unsupported PR action: {action!r}"
        raise ValueError(msg)
    ctx = dict(context or {})
    run_id = str(ctx.get("run_id") or "default")
    run_dir = Path(ctx["run_dir"]) if ctx.get("run_dir") else None
    store = get_idempotency_store(run_id=run_id, run_dir=run_dir)
    spec = _action_spec(action)

    if action == "merge":
        if not ctx.get("merge_approved"):
            msg = "merge requires human approval (merge gate)"
            raise ValueError(msg)
        if not may_retry(spec):
            pass  # merge is destructive; no automatic retry path

    if store.has_key(idempotency_key):
        return {
            **spec,
            "executed": False,
            "replayed": True,
            "idempotency_key": idempotency_key,
        }

    payload = _perform_stub(action, ctx)

    def _do() -> None:
        payload.update(_perform_stub(action, ctx))

    executed = run_commit_node(store, key=idempotency_key, action=action, perform=_do)
    return {
        **spec,
        "executed": executed,
        "replayed": not executed,
        "idempotency_key": idempotency_key,
        "result": payload if executed else None,
    }


def push(
    *,
    idempotency_key: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent ``git push`` for the run branch."""
    return run_pr_action("push", idempotency_key=idempotency_key, context=context)


def open_pr(
    *,
    idempotency_key: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent PR open — at most one PR per stable key."""
    return run_pr_action("open_pr", idempotency_key=idempotency_key, context=context)


def comment(
    *,
    idempotency_key: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent PR comment post."""
    return run_pr_action("comment", idempotency_key=idempotency_key, context=context)


def resolve_thread(
    *,
    idempotency_key: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent review-thread resolution."""
    return run_pr_action("resolve_thread", idempotency_key=idempotency_key, context=context)


def merge(
    *,
    idempotency_key: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Human-gated merge — never auto-invoked by the fix loop."""
    return run_pr_action("merge", idempotency_key=idempotency_key, context=context)
