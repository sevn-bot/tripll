"""tripll.api._inject — hotfix inject helpers for API and dashboard (L2-W5c)."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from tripll.inject import (
    HotfixTask,
    InjectError,
    ReconcileResult,
    apply_hotfix_inject,
    load_hotfix_tasks,
    reconcile_run_graph,
)
from tripll.ledger import list_events, open_ledger
from tripll.repo_root import resolve_repo_root

if TYPE_CHECKING:
    from tripll.pipeline import RunsRoot

_INJECT_LOCK = "inject.lock"

INJECT_EVENT_PHASES = frozenset(
    {
        "inject_requested",
        "inject_applied",
        "inject_rejected",
        "reconcile_inserted",
        "graph_reconciled",
    }
)


def inject_error_to_status(exc: InjectError) -> int:
    """Map InjectError exit codes to HTTP status codes."""
    if exc.exit_code in (2, 3):
        return 409
    return 400


def parse_owned_paths(raw: list[str] | str) -> list[str]:
    """Normalize owned paths from JSON list or comma/newline-separated text."""
    if isinstance(raw, list):
        parts = raw
    else:
        parts = []
        for line in str(raw).replace(",", "\n").splitlines():
            parts.append(line.strip())
    seen: dict[str, None] = {}
    for part in parts:
        p = part.strip()
        if p:
            seen[p] = None
    return list(seen)


def run_hotfix_inject(
    rr: RunsRoot,
    run_id: str,
    *,
    brief: str,
    owned_paths: list[str],
    after: str,
    verify_target: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    dry_run: bool = False,
    injected_by: str = "api",
    cost_budget_usd: float = 0.0,
    force_after_drain: bool = False,
) -> HotfixTask:
    """Apply a hotfix inject using the same core path as tripll run inject."""
    _ = injected_by
    verify_targets = [verify_target or "make ci-affected"]
    return apply_hotfix_inject(
        rr,
        run_id,
        brief=brief,
        owned_paths=owned_paths,
        after=after,
        verify_targets=verify_targets,
        provider=provider,
        model=model,
        agent=agent,
        cost_budget_usd=cost_budget_usd,
        force_after_drain=force_after_drain,
        dry_run=dry_run,
        repo_root=resolve_repo_root(),
    )


def run_reconcile_graph(
    rr: RunsRoot,
    run_id: str,
    *,
    dry_run: bool = False,
    force_after_drain: bool = False,
) -> ReconcileResult:
    """Reconcile parsed plan files with ledger waves (same path as CLI reconcile)."""
    with open_ledger(rr.ledger_path(run_id)) as lc:
        return reconcile_run_graph(
            rr,
            run_id,
            lc=lc,
            dry_run=dry_run,
            require_pause=True,
            force_after_drain=force_after_drain,
            source="api",
        )


def list_run_injects(rr: RunsRoot, run_id: str) -> dict[str, Any]:
    """List inject artefacts and related ledger events for run_id."""
    run_dir = rr.find_run_dir(run_id)
    artefacts: list[dict[str, Any]] = []
    if run_dir is not None:
        artefacts = [asdict(task) for task in load_hotfix_tasks(run_dir)]

    events: list[dict[str, Any]] = []
    if run_dir is not None:
        ledger_path = rr.ledger_path(run_id)
        if ledger_path.is_file():
            with open_ledger(ledger_path) as lc:
                for row in list_events(lc, run_id):
                    if row.phase not in INJECT_EVENT_PHASES:
                        continue
                    meta: object | None = None
                    if row.metadata:
                        try:
                            meta = json.loads(row.metadata)
                        except json.JSONDecodeError:
                            meta = row.metadata
                    events.append(
                        {
                            "event_id": row.event_id,
                            "node_id": row.node_id,
                            "ts": row.ts,
                            "phase": row.phase,
                            "metadata": meta,
                        }
                    )

    lock_held = run_dir is not None and (run_dir / _INJECT_LOCK).is_file()
    return {
        "run_id": run_id,
        "artefacts": artefacts,
        "events": events,
        "lock_held": lock_held,
    }
