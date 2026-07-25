"""Idempotent GitHub PR actions (§7.9.5, D11, D14/D15).

Every external mutation is a ``commit``-class node: the idempotency key is
written **before** the side effect. ``merge`` is destructive, human-gated, and
refuses retry (``retries: disabled``).

Set ``TRIPLL_PR_DRY_RUN=1`` to skip ``gh``/``git push`` side effects during
tests or local dry runs — the result includes ``dry_run: true`` and a warning
is logged. Without that flag, actions invoke ``gh``/``git`` and raise on failure.

Exports:
    SUPPORTED_ACTIONS — push, open_pr, comment, resolve_thread, merge.
    run_pr_action — unified entry for commit nodes (replay-safe).
    push, open_pr, comment, resolve_thread, merge — action helpers.
    get_idempotency_store — per-run SQLite store beside the ledger.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

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


def _pr_dry_run() -> bool:
    return os.environ.get("TRIPLL_PR_DRY_RUN", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _action_spec(action: str) -> dict[str, Any]:
    destructive = action in _DESTRUCTIVE_ACTIONS
    return {
        "action": action,
        "node_kind": "commit",
        "destructive": destructive,
        "retries": "disabled" if destructive else "default",
    }


def _repo_cwd(context: dict[str, Any]) -> str | None:
    for key in ("repo_root", "cwd", "worktree_path"):
        raw = context.get(key)
        if raw:
            return str(raw)
    return None


def _gh_json(args: list[str], *, cwd: str | None = None) -> Any:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh failed")
    return json.loads(proc.stdout or "null")


def _git(args: list[str], *, cwd: str | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git failed")
    return proc.stdout.strip()


def _perform_dry_run(action: str, context: dict[str, Any]) -> dict[str, Any]:
    logger.warning(
        "TRIPLL_PR_DRY_RUN=1 — skipping external PR action {!r} (no gh/git side effects)",
        action,
    )
    return {
        "action": action,
        "ok": True,
        "dry_run": True,
        **{k: v for k, v in context.items() if k != "ledger"},
    }


def _perform_push(context: dict[str, Any]) -> dict[str, Any]:
    cwd = _repo_cwd(context)
    remote = str(context.get("remote") or "origin")
    branch = str(context.get("branch") or "HEAD")
    _git(["push", remote, branch], cwd=cwd)
    return {"action": "push", "ok": True, "remote": remote, "branch": branch}


def _perform_open_pr(context: dict[str, Any]) -> dict[str, Any]:
    cwd = _repo_cwd(context)
    title = str(context.get("title") or "tripll wave delivery")
    body = str(context.get("body") or "")
    base = str(context.get("base") or "main")
    head = str(context.get("head") or context.get("branch") or "")
    args = ["pr", "create", "--title", title, "--body", body, "--base", base]
    if head:
        args.extend(["--head", head])
    data = _gh_json(args, cwd=cwd)
    pr_number = data.get("number") if isinstance(data, dict) else None
    return {
        "action": "open_pr",
        "ok": True,
        "pr_number": pr_number,
        "url": data.get("url") if isinstance(data, dict) else None,
    }


def _perform_comment(context: dict[str, Any]) -> dict[str, Any]:
    cwd = _repo_cwd(context)
    pr_number = context.get("pr_number")
    if pr_number is None:
        msg = "comment requires pr_number in context"
        raise ValueError(msg)
    body = str(context.get("body") or context.get("comment") or "")
    _gh_json(
        ["pr", "comment", str(pr_number), "--body", body],
        cwd=cwd,
    )
    return {"action": "comment", "ok": True, "pr_number": pr_number}


def _perform_resolve_thread(context: dict[str, Any]) -> dict[str, Any]:
    cwd = _repo_cwd(context)
    thread_id = context.get("thread_id")
    if thread_id is None:
        msg = "resolve_thread requires thread_id in context"
        raise ValueError(msg)
    owner = str(context.get("owner") or "")
    repo = str(context.get("repo") or "")
    if not owner or not repo:
        msg = "resolve_thread requires owner and repo in context"
        raise ValueError(msg)
    mutation = """
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { isResolved }
      }
    }
    """
    _gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={mutation}",
            "-f",
            f"threadId={thread_id}",
        ],
        cwd=cwd,
    )
    return {"action": "resolve_thread", "ok": True, "thread_id": thread_id}


def _perform_merge(context: dict[str, Any]) -> dict[str, Any]:
    cwd = _repo_cwd(context)
    pr_number = context.get("pr_number")
    if pr_number is None:
        msg = "merge requires pr_number in context"
        raise ValueError(msg)
    _gh_json(["pr", "merge", str(pr_number), "--merge"], cwd=cwd)
    return {"action": "merge", "ok": True, "pr_number": pr_number}


def _perform_action(action: str, context: dict[str, Any]) -> dict[str, Any]:
    """Execute *action* via ``gh``/``git``, or return an explicit dry-run payload."""
    if _pr_dry_run():
        return _perform_dry_run(action, context)
    performers = {
        "push": _perform_push,
        "open_pr": _perform_open_pr,
        "comment": _perform_comment,
        "resolve_thread": _perform_resolve_thread,
        "merge": _perform_merge,
    }
    return performers[action](context)


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
        RuntimeError: ``gh``/``git`` subprocess failed (when not in dry-run mode).
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

    payload: dict[str, Any] = {}

    def _do() -> None:
        nonlocal payload
        payload = _perform_action(action, ctx)

    executed = run_commit_node(store, key=idempotency_key, action=action, perform=_do)
    return {
        **spec,
        "executed": executed,
        "replayed": not executed,
        "idempotency_key": idempotency_key,
        "result": payload if executed else None,
        "dry_run": bool(payload.get("dry_run")) if executed else False,
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
