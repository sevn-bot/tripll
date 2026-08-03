"""Inject plan/apply/reconcile paths extracted from :mod:`tripll.inject_dispatch`.

Internal module (#62 W5); public API remains on ``tripll.inject``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from tripll.graph import RunGraph, WaveNode, derive_forbidden_paths
from tripll.inject_dispatch import (
    _BATCH_PLACEMENT,
    _DEFAULT_AGENT,
    _DEFAULT_VERIFY,
    _HOTFIX_LANE_ID,
    _HOTFIX_PLAN_ID,
    _PROTECTED_LEDGER_STATES,
    _WAVE_ADD_KIND,
    HotfixTask,
    InjectError,
    ReconcileResult,
    WaveAddTask,
    _acquire_inject_lock,
    _assert_reconcile_gate,
    _next_hotfix_wave_id,
    _now_iso,
    _resolve_wave_add_batch_index,
    _slug_lane_id,
    injects_dir,
    load_hotfix_tasks,
    load_wave_add_tasks,
    merge_hotfix_task,
    merge_wave_add_task,
    validate_hotfix_inject,
    validate_wave_add_inject,
)
from tripll.ledger import (
    LedgerConnection,
    append_event,
    get_wave,
    insert_wave,
    list_waves,
    open_ledger,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.pipeline import RunsRoot


def plan_wave_add(
    rr: RunsRoot,
    run_id: str,
    *,
    lane: str,
    wave_id: str,
    brief: str,
    owned_paths: list[str],
    depends_on: list[str] | None = None,
    after: str | None = None,
    batch_placement: _BATCH_PLACEMENT = "current",
    plan_id: str | None = None,
    verify_targets: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    cost_budget_usd: float = 0.0,
    injected_by: str = "cli",
) -> tuple[WaveAddTask, RunGraph]:
    """Validate and build a wave-add task + merged graph without persisting."""
    from tripll.parse import build_graph_from_dir

    run_dir = rr.run_dir(run_id)
    if not run_dir.is_dir():
        raise InjectError(f"run not found in processing/: {run_id}", exit_code=1)
    graph = build_graph_from_dir(run_dir, run_id=run_id)
    graph = merge_injected_artefacts(graph, run_dir)
    with open_ledger(rr.ledger_path(run_id)) as lc:
        resolved_deps, anchor_node_id = validate_wave_add_inject(
            graph,
            run_dir=run_dir,
            lc=lc,
            run_id=run_id,
            owned_paths=owned_paths,
            depends_on=depends_on or [],
            after=after,
            cost_budget_usd=cost_budget_usd,
        )
        batch_index = _resolve_wave_add_batch_index(
            graph,
            lc,
            run_id,
            anchor_node_id=anchor_node_id,
            placement=batch_placement,
        )

    lane_id = _slug_lane_id(lane)
    plan_slug = plan_id or lane_id
    node_id = f"{plan_slug}:{wave_id}"
    if node_id in graph.nodes:
        raise InjectError(f"wave node {node_id!r} already exists", exit_code=1)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    task_id = f"wave-add-{ts}-{uuid.uuid4().hex[:4]}"
    verify = verify_targets or [_DEFAULT_VERIFY]
    forbidden = derive_forbidden_paths(
        lane_id,
        graph.lanes,
        node=WaveNode(
            node_id,
            plan_slug,
            task_id,
            wave_id,
            lane_id,
            owned_paths=owned_paths,
            role="impl",
        ),
    )
    batch_id = graph.batches[batch_index].batch_id
    task = WaveAddTask(
        task_id=task_id,
        node_id=node_id,
        run_id=run_id,
        plan_id=plan_slug,
        wave_id=wave_id,
        lane_id=lane_id,
        brief=brief,
        owned_paths=list(owned_paths),
        forbidden_paths=forbidden,
        depends_on=resolved_deps,
        after=after or "",
        batch_placement=batch_placement,
        batch_id=batch_id,
        provider=provider,
        model=model,
        agent=agent or _DEFAULT_AGENT,
        verify_targets=verify,
        injected_at=_now_iso(),
        injected_by=injected_by,
    )
    merged = merge_wave_add_task(graph, task)
    return task, merged


def apply_wave_add(
    rr: RunsRoot,
    run_id: str,
    *,
    lane: str,
    wave_id: str,
    brief: str,
    owned_paths: list[str],
    depends_on: list[str] | None = None,
    after: str | None = None,
    batch_placement: _BATCH_PLACEMENT = "current",
    plan_id: str | None = None,
    verify_targets: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    cost_budget_usd: float = 0.0,
    dry_run: bool = False,
    injected_by: str = "cli",
) -> WaveAddTask:
    """Validate, persist wave-add artefact, ledger row, and updated ``graph.json``."""
    task, graph = plan_wave_add(
        rr,
        run_id,
        lane=lane,
        wave_id=wave_id,
        brief=brief,
        owned_paths=owned_paths,
        depends_on=depends_on or [],
        after=after,
        batch_placement=batch_placement,
        plan_id=plan_id,
        verify_targets=verify_targets,
        provider=provider,
        model=model,
        agent=agent,
        cost_budget_usd=cost_budget_usd,
        injected_by=injected_by,
    )
    run_dir = rr.run_dir(run_id)
    inject_root = injects_dir(run_dir)
    inject_root.mkdir(parents=True, exist_ok=True)
    plan_path = inject_root / f"{task.task_id}.plan.json"
    plan_path.write_text(
        json.dumps({**asdict(task), "dry_run": dry_run}, indent=2),
        encoding="utf-8",
    )
    if dry_run:
        logger.info("wave-add: dry-run plan written {}", plan_path)
        return WaveAddTask(**{**asdict(task), "dry_run": True})

    lock_path = _acquire_inject_lock(run_dir)
    try:
        artefact = inject_root / f"{task.task_id}.json"
        payload = asdict(task)
        artefact.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        wave_md = inject_root / f"{task.task_id}-wave.md"
        wave_md.write_text(
            f"# Wave add {task.node_id}\n\n{task.brief}\n\n"
            f"## Files in scope\n\n" + "\n".join(f"- `{p}`" for p in task.owned_paths) + "\n",
            encoding="utf-8",
        )
        meta = json.dumps(
            {
                "task_id": task.task_id,
                "node_id": task.node_id,
                "lane_id": task.lane_id,
                "batch_id": task.batch_id,
                "paths": task.owned_paths,
                "depends_on": task.depends_on,
                "after": task.after,
                "inject_kind": _WAVE_ADD_KIND,
            }
        )
        with open_ledger(rr.ledger_path(run_id)) as lc:
            append_event(
                lc,
                run_id=run_id,
                node_id=task.node_id,
                phase="inject_requested",
                metadata=meta,
            )
            insert_wave(
                lc,
                node_id=task.node_id,
                run_id=run_id,
                plan_id=task.plan_id,
                wave_id=task.wave_id,
                lane=task.lane_id,
                initial_state="queued",
            )
            append_event(
                lc,
                run_id=run_id,
                node_id=task.node_id,
                phase="inject_applied",
                metadata=meta,
            )
        _write_graph_json(rr, run_id, graph)
        _sync_task_graph(rr, run_id, graph)
        briefs = rr.briefs_dir(run_id)
        briefs.mkdir(parents=True, exist_ok=True)
        brief_path = briefs / f"{task.node_id}.json"
        brief_path.write_text(
            json.dumps(
                {
                    "node_id": task.node_id,
                    "brief": task.brief,
                    "owned_paths": task.owned_paths,
                    "verify_targets": task.verify_targets,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("wave-add: applied {} → {}", task.task_id, task.node_id)
        return task
    finally:
        lock_path.unlink(missing_ok=True)


def merge_injected_artefacts(graph: RunGraph, run_dir: Path) -> RunGraph:
    """Re-merge all inject artefacts (hotfix + wave-add) into a freshly parsed graph."""
    for hotfix_task in load_hotfix_tasks(run_dir):
        graph = merge_hotfix_task(graph, hotfix_task)
    for wave_task in load_wave_add_tasks(run_dir):
        graph = merge_wave_add_task(graph, wave_task)
    return graph


def merge_injected_hotfixes(graph: RunGraph, run_dir: Path) -> RunGraph:
    """Re-merge hotfix inject artefacts into a freshly parsed graph."""
    for task in load_hotfix_tasks(run_dir):
        graph = merge_hotfix_task(graph, task)
    return graph


def _plan_reconcile_diff(
    graph: RunGraph,
    lc: LedgerConnection,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(insert_ids, orphan_ids)`` without mutating stores."""
    ledger_rows = list_waves(lc, run_id)
    ledger_by_id = {row.node_id: row for row in ledger_rows}
    graph_ids = set(graph.nodes)

    for row in ledger_rows:
        if row.state in _PROTECTED_LEDGER_STATES and row.node_id not in graph_ids:
            raise InjectError(
                "plan edit removes or renames wave "
                f"{row.node_id!r} (ledger state={row.state!r}) — reconcile refused",
                exit_code=1,
            )

    inserted = tuple(sorted(nid for nid in graph_ids if nid not in ledger_by_id))
    orphans = tuple(
        sorted(
            row.node_id
            for row in ledger_rows
            if row.node_id not in graph_ids and row.state not in _PROTECTED_LEDGER_STATES
        )
    )
    return inserted, orphans


def reconcile_run_graph(
    rr: RunsRoot,
    run_id: str,
    *,
    lc: LedgerConnection,
    expected_graph: RunGraph | None = None,
    dry_run: bool = False,
    require_pause: bool = True,
    force_after_drain: bool = False,
    source: str = "cli",
) -> ReconcileResult:
    """Diff parsed graph vs ledger waves and apply safe mutations.

    Inserts ``queued`` ledger rows for new graph nodes, refuses plan edits that
    remove or rename ``done``/``blocked`` waves, logs orphan ledger rows without
    deleting them, and rewrites ``graph.json`` plus the task graph layer.

    Args:
        rr (RunsRoot): Run directory layout.
        run_id (str): Processing run identifier.
        lc (LedgerConnection): Open ledger for the run.
        expected_graph (RunGraph | None): Pre-parsed graph; when ``None``,
            parse from the run directory.
        dry_run (bool): Validate only — no ledger or graph writes.
        require_pause (bool): When ``True``, require ``pause-requested.md``
            (CLI reconcile). Resume passes ``False``.
        source (str): Audit label (``cli``, ``resume``, …).

    Returns:
        ReconcileResult: Inserted and orphan node ids plus the reconciled graph.

    Raises:
        InjectError: Validation, overlap, or lock failures (see ``exit_code``).

    Examples:
        >>> reconcile_run_graph.__name__
        'reconcile_run_graph'
    """
    from tripll.parse import build_graph_from_dir

    run_dir = rr.run_dir(run_id)
    if not run_dir.is_dir():
        raise InjectError(f"run not found in processing/: {run_id}", exit_code=1)

    _assert_reconcile_gate(
        run_dir,
        lc,
        run_id,
        require_pause=require_pause,
        force_after_drain=force_after_drain,
    )

    graph = (
        expected_graph
        if expected_graph is not None
        else build_graph_from_dir(run_dir, run_id=run_id)
    )
    graph = merge_injected_artefacts(graph, run_dir)
    errors = graph.validate()
    if errors:
        raise InjectError(
            "graph validation failed before reconcile: " + "; ".join(errors),
            exit_code=3,
        )

    inserted, orphans = _plan_reconcile_diff(graph, lc, run_id)
    for node_id in orphans:
        row = get_wave(lc, run_id, node_id)
        logger.warning(
            "reconcile: orphan ledger row {} (state={}) — not in plan, kept",
            node_id,
            row.state,
        )

    if dry_run:
        logger.info(
            "reconcile: dry-run {} — would insert {} orphan {}",
            run_id,
            list(inserted),
            list(orphans),
        )
        return ReconcileResult(graph=graph, inserted=inserted, orphans=orphans, dry_run=True)

    lock_path = _acquire_inject_lock(run_dir)
    try:
        meta_base = json.dumps(
            {"source": source, "inserted": list(inserted), "orphans": list(orphans)}
        )
        for node_id in inserted:
            node = graph.nodes[node_id]
            insert_wave(
                lc,
                node_id=node_id,
                run_id=run_id,
                plan_id=node.plan_id,
                wave_id=node.wave_id,
                lane=node.lane,
                initial_state="queued",
            )
            append_event(
                lc,
                run_id=run_id,
                node_id=node_id,
                phase="reconcile_inserted",
                metadata=meta_base,
            )
        if inserted or orphans:
            append_event(
                lc,
                run_id=run_id,
                node_id=inserted[0] if inserted else orphans[0],
                phase="graph_reconciled",
                metadata=meta_base,
            )
        _write_graph_json(rr, run_id, graph)
        _sync_task_graph(rr, run_id, graph)
        logger.info(
            "reconcile: applied {} — inserted {} orphan {}",
            run_id,
            list(inserted),
            list(orphans),
        )
        return ReconcileResult(graph=graph, inserted=inserted, orphans=orphans, dry_run=False)
    finally:
        lock_path.unlink(missing_ok=True)


def plan_hotfix_inject(
    rr: RunsRoot,
    run_id: str,
    *,
    brief: str,
    owned_paths: list[str],
    after: str,
    verify_targets: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    cost_budget_usd: float = 0.0,
    force_after_drain: bool = False,
    repo_root: Path | None = None,
    injected_by: str = "cli",
) -> tuple[HotfixTask, RunGraph]:
    """Validate and build a hotfix task + merged graph without persisting."""
    from tripll.parse import build_graph_from_dir

    run_dir = rr.run_dir(run_id)
    if not run_dir.is_dir():
        raise InjectError(f"run not found in processing/: {run_id}", exit_code=1)
    graph = build_graph_from_dir(run_dir, run_id=run_id)
    graph = merge_injected_artefacts(graph, run_dir)
    with open_ledger(rr.ledger_path(run_id)) as lc:
        after_node_id = validate_hotfix_inject(
            graph,
            run_dir=run_dir,
            lc=lc,
            run_id=run_id,
            owned_paths=owned_paths,
            after=after,
            cost_budget_usd=cost_budget_usd,
            force_after_drain=force_after_drain,
        )
        if get_wave(lc, run_id, after_node_id).state != "done":
            raise InjectError(
                f"--after node {after_node_id!r} must be done before inject",
                exit_code=1,
            )
    wave_id = _next_hotfix_wave_id(run_dir)
    node_id = f"{_HOTFIX_PLAN_ID}:{wave_id}"
    if node_id in graph.nodes:
        raise InjectError(f"hotfix node {node_id!r} already exists", exit_code=1)
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    task_id = f"hotfix-{ts}-{uuid.uuid4().hex[:4]}"
    verify = verify_targets or [_DEFAULT_VERIFY]
    forbidden = derive_forbidden_paths(
        _HOTFIX_LANE_ID,
        graph.lanes,
        node=WaveNode(
            node_id,
            _HOTFIX_PLAN_ID,
            task_id,
            wave_id,
            _HOTFIX_LANE_ID,
            owned_paths=owned_paths,
            role="impl",
        ),
    )
    task = HotfixTask(
        task_id=task_id,
        node_id=node_id,
        run_id=run_id,
        brief=brief,
        owned_paths=list(owned_paths),
        forbidden_paths=forbidden,
        depends_on=[after_node_id],
        after=after,
        provider=provider,
        model=model,
        agent=agent or _DEFAULT_AGENT,
        verify_targets=verify,
        injected_at=_now_iso(),
        injected_by=injected_by,
    )
    merged = merge_hotfix_task(graph, task)
    _ = repo_root  # reserved for future brief pack paths
    return task, merged


def _write_graph_json(rr: RunsRoot, run_id: str, graph: RunGraph) -> None:
    rr.graph_path(run_id).write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")


def _sync_task_graph(rr: RunsRoot, run_id: str, graph: RunGraph) -> None:
    db_path = rr.graph_db_path(run_id)
    if not db_path.is_file():
        return
    from tripll.graphstore.task_sync import TaskGraphWriter

    writer = TaskGraphWriter(db_path)
    try:
        writer.sync_run_start(run_id=run_id, graph=graph, backend="inject", model=None, agent=None)
    finally:
        writer.close()


def apply_hotfix_inject(
    rr: RunsRoot,
    run_id: str,
    *,
    brief: str,
    owned_paths: list[str],
    after: str,
    verify_targets: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    cost_budget_usd: float = 0.0,
    force_after_drain: bool = False,
    dry_run: bool = False,
    repo_root: Path | None = None,
    injected_by: str = "cli",
) -> HotfixTask:
    """Validate, persist inject artefact, ledger row, and updated ``graph.json``."""
    task, graph = plan_hotfix_inject(
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
        repo_root=repo_root,
        injected_by=injected_by,
    )
    run_dir = rr.run_dir(run_id)
    inject_root = injects_dir(run_dir)
    inject_root.mkdir(parents=True, exist_ok=True)
    plan_path = inject_root / f"{task.task_id}.plan.json"
    plan_path.write_text(
        json.dumps({**asdict(task), "dry_run": dry_run}, indent=2),
        encoding="utf-8",
    )
    if dry_run:
        logger.info("inject: dry-run plan written {}", plan_path)
        return HotfixTask(**{**asdict(task), "dry_run": True})

    lock_path = _acquire_inject_lock(run_dir)
    try:
        artefact = inject_root / f"{task.task_id}.json"
        payload = asdict(task)
        artefact.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        wave_md = inject_root / f"{task.task_id}-wave.md"
        wave_md.write_text(
            f"# Hotfix {task.node_id}\n\n{task.brief}\n\n"
            f"## Files in scope\n\n" + "\n".join(f"- `{p}`" for p in task.owned_paths) + "\n",
            encoding="utf-8",
        )
        meta = json.dumps(
            {
                "task_id": task.task_id,
                "node_id": task.node_id,
                "paths": task.owned_paths,
                "depends_on": task.depends_on,
                "after": task.after,
            }
        )
        with open_ledger(rr.ledger_path(run_id)) as lc:
            append_event(
                lc,
                run_id=run_id,
                node_id=task.node_id,
                phase="inject_requested",
                metadata=meta,
            )
            insert_wave(
                lc,
                node_id=task.node_id,
                run_id=run_id,
                plan_id=_HOTFIX_PLAN_ID,
                wave_id=task.node_id.rsplit(":", 1)[-1],
                lane=_HOTFIX_LANE_ID,
                initial_state="queued",
            )
            append_event(
                lc,
                run_id=run_id,
                node_id=task.node_id,
                phase="inject_applied",
                metadata=meta,
            )
        _write_graph_json(rr, run_id, graph)
        _sync_task_graph(rr, run_id, graph)
        briefs = rr.briefs_dir(run_id)
        briefs.mkdir(parents=True, exist_ok=True)
        brief_path = briefs / f"{task.node_id}.json"
        brief_path.write_text(
            json.dumps(
                {
                    "node_id": task.node_id,
                    "brief": task.brief,
                    "owned_paths": task.owned_paths,
                    "verify_targets": task.verify_targets,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("inject: applied {} → {}", task.task_id, task.node_id)
        return task
    finally:
        lock_path.unlink(missing_ok=True)
