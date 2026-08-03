"""Inject dispatch implementation — hotfix, wave-add, and graph↔ledger reconciliation.

Implementation module extracted from :mod:`tripll.inject` per ADR 013 (#62). Callers
import the public API from ``tripll.inject`` (façade re-exports).

Exports:
    HotfixTask — immutable hotfix inject spec persisted under ``injects/``.
    WaveAddTask — structured parallel-lane wave inject spec.
    ReconcileResult — outcome of :func:`reconcile_run_graph`.
    InjectError — validation failure with CLI exit code.
    resolve_after_node_id — map ``--after`` to a graph node id.
    validate_hotfix_inject — pause/scope/deps/cost checks.
    validate_wave_add_inject — wave-add validation.
    load_hotfix_tasks — read hotfix inject specs from a run directory.
    load_wave_add_tasks — read wave-add inject specs from a run directory.

Plan/apply/reconcile implementations live in :mod:`tripll.inject_apply`; the
:mod:`tripll.inject` façade re-exports them.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — used at runtime throughout this module
from typing import Literal

from loguru import logger

from tripll.graph import (
    Batch,
    Lane,
    RunGraph,
    WaveNode,
    derive_forbidden_paths,
    insert_orchestrator_serial_after,
)
from tripll.ledger import (
    LedgerConnection,
    get_run_cost,
    get_wave,
    list_waves,
)

_INJECT_KIND: Literal["hotfix"] = "hotfix"
_WAVE_ADD_KIND: Literal["wave_add"] = "wave_add"
_HOTFIX_PLAN_ID = "hotfix"
_HOTFIX_LANE_ID = "hotfix"
_BATCH_PLACEMENT = Literal["current", "next"]
_PAUSE_MARKER = "pause-requested.md"
_INJECT_LOCK = "inject.lock"
_INFLIGHT_STATES = frozenset({"running", "dispatched", "quality_loop", "verifying"})
_PROTECTED_LEDGER_STATES = frozenset({"done", "blocked"})
_DEFAULT_VERIFY = "make ci-affected"
_DEFAULT_AGENT = "wave-runner"


@dataclass(frozen=True, slots=True)
class HotfixTask:
    """One-shot hotfix dispatch unit tied to an existing run."""

    task_id: str
    node_id: str
    run_id: str
    brief: str
    owned_paths: list[str]
    forbidden_paths: list[str]
    depends_on: list[str]
    after: str
    provider: str | None = None
    model: str | None = None
    agent: str | None = None
    verify_targets: list[str] = field(default_factory=lambda: [_DEFAULT_VERIFY])
    max_attempts: int = 3
    inject_kind: Literal["hotfix"] = _INJECT_KIND
    injected_at: str = ""
    injected_by: str = "cli"
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class WaveAddTask:
    """Structured parallel-lane wave inject unit tied to an existing run."""

    task_id: str
    node_id: str
    run_id: str
    plan_id: str
    wave_id: str
    lane_id: str
    brief: str
    owned_paths: list[str]
    forbidden_paths: list[str]
    depends_on: list[str]
    after: str
    batch_placement: _BATCH_PLACEMENT
    batch_id: str
    provider: str | None = None
    model: str | None = None
    agent: str | None = None
    verify_targets: list[str] = field(default_factory=lambda: [_DEFAULT_VERIFY])
    max_attempts: int = 3
    inject_kind: Literal["wave_add"] = _WAVE_ADD_KIND
    injected_at: str = ""
    injected_by: str = "cli"
    dry_run: bool = False


class InjectError(Exception):
    """Inject validation or apply failure with a stable CLI exit code."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of :func:`reconcile_run_graph`."""

    graph: RunGraph
    inserted: tuple[str, ...]
    orphans: tuple[str, ...]
    dry_run: bool


def injects_dir(run_dir: Path) -> Path:
    """Return ``processing/<run-id>/injects/``."""
    return run_dir / "injects"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _next_hotfix_wave_id(run_dir: Path) -> str:
    existing = load_hotfix_tasks(run_dir)
    max_n = 0
    for task in existing:
        if task.node_id.startswith(f"{_HOTFIX_PLAN_ID}:HF-"):
            suffix = task.node_id.rsplit(":", 1)[-1]
            if suffix.startswith("HF-"):
                try:
                    max_n = max(max_n, int(suffix.removeprefix("HF-")))
                except ValueError:
                    continue
    return f"HF-{max_n + 1}"


def load_hotfix_tasks(run_dir: Path) -> list[HotfixTask]:
    """Load all persisted hotfix inject specs (sorted by ``task_id``)."""
    root = injects_dir(run_dir)
    if not root.is_dir():
        return []
    out: list[HotfixTask] = []
    for path in sorted(root.glob("*.json")):
        if path.name.endswith(".plan.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("inject: skipping invalid JSON {}", path)
            continue
        if not isinstance(data, dict) or data.get("inject_kind") != _INJECT_KIND:
            continue
        out.append(_task_from_dict(data))
    return out


def load_wave_add_tasks(run_dir: Path) -> list[WaveAddTask]:
    """Load all persisted wave-add inject specs (sorted by ``task_id``)."""
    root = injects_dir(run_dir)
    if not root.is_dir():
        return []
    out: list[WaveAddTask] = []
    for path in sorted(root.glob("*.json")):
        if path.name.endswith(".plan.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("inject: skipping invalid JSON {}", path)
            continue
        if not isinstance(data, dict) or data.get("inject_kind") != _WAVE_ADD_KIND:
            continue
        out.append(_wave_add_from_dict(data))
    return out


def _wave_add_from_dict(data: dict[str, object]) -> WaveAddTask:
    verify_raw = data.get("verify_targets")
    verify = [str(v) for v in verify_raw] if isinstance(verify_raw, list) else [_DEFAULT_VERIFY]
    owned_raw = data.get("owned_paths")
    owned = [str(p) for p in owned_raw] if isinstance(owned_raw, list) else []
    forbidden_raw = data.get("forbidden_paths")
    forbidden = [str(p) for p in forbidden_raw] if isinstance(forbidden_raw, list) else []
    deps_raw = data.get("depends_on")
    depends_on = [str(d) for d in deps_raw] if isinstance(deps_raw, list) else []
    placement_raw = str(data.get("batch_placement") or "current")
    placement: _BATCH_PLACEMENT = "next" if placement_raw == "next" else "current"
    return WaveAddTask(
        task_id=str(data.get("task_id") or ""),
        node_id=str(data.get("node_id") or ""),
        run_id=str(data.get("run_id") or ""),
        plan_id=str(data.get("plan_id") or ""),
        wave_id=str(data.get("wave_id") or ""),
        lane_id=str(data.get("lane_id") or ""),
        brief=str(data.get("brief") or ""),
        owned_paths=owned,
        forbidden_paths=forbidden,
        depends_on=depends_on,
        after=str(data.get("after") or ""),
        batch_placement=placement,
        batch_id=str(data.get("batch_id") or ""),
        provider=(str(data["provider"]) if data.get("provider") else None),
        model=(str(data["model"]) if data.get("model") else None),
        agent=(str(data["agent"]) if data.get("agent") else None),
        verify_targets=verify or [_DEFAULT_VERIFY],
        max_attempts=int(str(data.get("max_attempts") or "3")),
        inject_kind=_WAVE_ADD_KIND,
        injected_at=str(data.get("injected_at") or ""),
        injected_by=str(data.get("injected_by") or "cli"),
        dry_run=bool(data.get("dry_run")),
    )


def _task_from_dict(data: dict[str, object]) -> HotfixTask:
    verify_raw = data.get("verify_targets")
    verify = [str(v) for v in verify_raw] if isinstance(verify_raw, list) else [_DEFAULT_VERIFY]
    owned_raw = data.get("owned_paths")
    owned = [str(p) for p in owned_raw] if isinstance(owned_raw, list) else []
    forbidden_raw = data.get("forbidden_paths")
    forbidden = [str(p) for p in forbidden_raw] if isinstance(forbidden_raw, list) else []
    deps_raw = data.get("depends_on")
    depends_on = [str(d) for d in deps_raw] if isinstance(deps_raw, list) else []
    return HotfixTask(
        task_id=str(data.get("task_id") or ""),
        node_id=str(data.get("node_id") or ""),
        run_id=str(data.get("run_id") or ""),
        brief=str(data.get("brief") or ""),
        owned_paths=owned,
        forbidden_paths=forbidden,
        depends_on=depends_on,
        after=str(data.get("after") or ""),
        provider=(str(data["provider"]) if data.get("provider") else None),
        model=(str(data["model"]) if data.get("model") else None),
        agent=(str(data["agent"]) if data.get("agent") else None),
        verify_targets=verify or [_DEFAULT_VERIFY],
        max_attempts=int(str(data.get("max_attempts") or "3")),
        inject_kind=_INJECT_KIND,
        injected_at=str(data.get("injected_at") or ""),
        injected_by=str(data.get("injected_by") or "cli"),
        dry_run=bool(data.get("dry_run")),
    )


def _slug_lane_id(lane: str) -> str:
    slug = lane.lower().replace("/", " ").strip()
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-") or "lane"


def resolve_dep_node_ids(graph: RunGraph, depends_on: list[str]) -> list[str]:
    """Resolve dependency labels to concrete node ids present in *graph*."""
    resolved: list[str] = []
    for dep in depends_on:
        needle = dep.strip()
        if not needle:
            continue
        if needle in graph.nodes:
            resolved.append(needle)
            continue
        matches = [nid for nid in graph.nodes if nid.endswith(f":{needle}") or nid == needle]
        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) > 1:
            raise InjectError(
                f"dependency {dep!r} is ambiguous — matches {matches!r}",
                exit_code=1,
            )
        else:
            raise InjectError(
                f"dependency {dep!r} does not match any node in the run graph",
                exit_code=1,
            )
    if not resolved:
        raise InjectError(
            "at least one --depends-on or --after dependency is required", exit_code=1
        )
    return resolved


def _batch_has_dispatchable_nodes(graph: RunGraph, batch_index: int) -> bool:
    from tripll.engine import nodes_for_batch

    return bool(nodes_for_batch(graph, graph.batches[batch_index]))


def _batch_fully_done(
    graph: RunGraph,
    lc: LedgerConnection,
    run_id: str,
    batch_index: int,
) -> bool:
    from tripll.engine import nodes_for_batch

    batch = graph.batches[batch_index]
    nodes = nodes_for_batch(graph, batch)
    if not nodes:
        return False
    for node in nodes:
        try:
            row = get_wave(lc, run_id, node.node_id)
        except KeyError:
            return False
        if row.state != "done":
            return False
    return True


def _resolve_wave_add_batch_index(
    graph: RunGraph,
    lc: LedgerConnection,
    run_id: str,
    *,
    anchor_node_id: str,
    placement: _BATCH_PLACEMENT,
) -> int:
    """Return the batch index where a wave-add node should be placed."""
    anchor_batch = _batch_for_node(graph, anchor_node_id)
    if anchor_batch is None:
        raise InjectError(
            f"anchor node {anchor_node_id!r} is not assigned to any batch",
            exit_code=1,
        )
    if placement == "current":
        if _batch_fully_done(graph, lc, run_id, anchor_batch):
            raise InjectError(
                f"batch {graph.batches[anchor_batch].batch_id!r} already completed — "
                "use --batch next",
                exit_code=1,
            )
        return anchor_batch

    for idx in range(anchor_batch + 1, len(graph.batches)):
        batch = graph.batches[idx]
        if batch.is_human_gate:
            continue
        if not _batch_has_dispatchable_nodes(graph, idx):
            continue
        if not _batch_fully_done(graph, lc, run_id, idx):
            return idx

    final_idx = next(
        (idx for idx, batch in enumerate(graph.batches) if batch.batch_id == "Final"),
        len(graph.batches),
    )
    inject_n = sum(1 for batch in graph.batches if batch.batch_id.startswith("Inject-")) + 1
    new_batch = Batch(
        batch_id=f"Inject-{inject_n}",
        label=f"Injected lane batch {inject_n}",
        lanes=[],
    )
    graph.batches.insert(final_idx, new_batch)
    return final_idx


def wave_add_plan_file(task: WaveAddTask) -> str:
    """Return run-dir-relative staged plan path for a wave-add task."""
    return f"injects/{task.task_id}-wave.md"


def resolve_after_node_id(graph: RunGraph, after: str) -> str:
    """Resolve ``--after`` to a concrete ``node_id`` present in *graph*."""
    needle = after.strip()
    if not needle:
        raise InjectError("--after is required", exit_code=1)
    if needle in graph.nodes:
        return needle
    matches = [nid for nid in graph.nodes if nid.endswith(f":{needle}") or nid == needle]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise InjectError(
            f"--after {after!r} is ambiguous — matches {matches!r}",
            exit_code=1,
        )
    raise InjectError(f"--after {after!r} does not match any node in the run graph", exit_code=1)


def _batch_for_node(graph: RunGraph, node_id: str) -> int | None:
    from tripll.engine import nodes_for_batch

    if node_id not in graph.nodes:
        return None
    for index, batch in enumerate(graph.batches):
        if batch.is_human_gate:
            continue
        if node_id in {n.node_id for n in nodes_for_batch(graph, batch)}:
            return index
    return None


def _assert_inject_lock_free(run_dir: Path) -> None:
    if (run_dir / _INJECT_LOCK).is_file():
        raise InjectError("inject.lock held — another inject/reconcile in progress", exit_code=2)


def _assert_no_inflight_waves(lc: LedgerConnection, run_id: str) -> None:
    inflight = [w.node_id for w in list_waves(lc, run_id) if w.state in _INFLIGHT_STATES]
    if inflight:
        raise InjectError(
            f"run {run_id} still has in-flight waves {inflight!r} — wait for drain",
            exit_code=2,
        )


def _assert_run_paused(
    run_dir: Path,
    lc: LedgerConnection,
    run_id: str,
    *,
    force_after_drain: bool = False,
) -> None:
    if not (run_dir / _PAUSE_MARKER).is_file():
        raise InjectError(
            f"run {run_id} is not paused — write pause-requested.md first (tripll pause or API)",
            exit_code=2,
        )
    if not force_after_drain:
        _assert_no_inflight_waves(lc, run_id)


def _assert_reconcile_gate(
    run_dir: Path,
    lc: LedgerConnection,
    run_id: str,
    *,
    require_pause: bool,
    force_after_drain: bool = False,
) -> None:
    """Validate it is safe to mutate graph/ledger (pause + lock + drain)."""
    _assert_inject_lock_free(run_dir)
    if require_pause:
        _assert_run_paused(run_dir, lc, run_id, force_after_drain=force_after_drain)


def _acquire_inject_lock(run_dir: Path) -> Path:
    lock_path = run_dir / _INJECT_LOCK
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError as exc:
        raise InjectError(
            "inject.lock held — another inject/reconcile in progress", exit_code=2
        ) from exc
    return lock_path


def _assert_cost_headroom(lc: LedgerConnection, run_id: str, *, budget_usd: float) -> None:
    if budget_usd <= 0:
        return
    spent = get_run_cost(lc, run_id)
    if spent >= budget_usd:
        raise InjectError(
            f"cost budget exhausted (${spent:.4f} spent of ${budget_usd:.2f}) — inject blocked",
            exit_code=1,
        )


def validate_hotfix_inject(
    graph: RunGraph,
    *,
    run_dir: Path,
    lc: LedgerConnection,
    run_id: str,
    owned_paths: list[str],
    after: str,
    cost_budget_usd: float = 0.0,
    force_after_drain: bool = False,
) -> str:
    """Run inject gate checks; return resolved ``after`` node id."""
    if not owned_paths:
        raise InjectError("--paths must declare at least one owned path", exit_code=1)
    _assert_run_paused(run_dir, lc, run_id, force_after_drain=force_after_drain)
    _assert_cost_headroom(lc, run_id, budget_usd=cost_budget_usd)
    after_node_id = resolve_after_node_id(graph, after)
    after_wave = get_wave(lc, run_id, after_node_id)
    if after_wave.state != "done":
        raise InjectError(
            f"--after node {after_node_id!r} is {after_wave.state!r}, must be done",
            exit_code=1,
        )
    return after_node_id


def hotfix_plan_file(task: HotfixTask) -> str:
    """Return run-dir-relative staged plan path for a hotfix task."""
    return f"injects/{task.task_id}-wave.md"


def build_hotfix_wave_node(task: HotfixTask) -> WaveNode:
    """Map a :class:`HotfixTask` to a synthetic :class:`WaveNode`."""
    return WaveNode(
        node_id=task.node_id,
        plan_id=_HOTFIX_PLAN_ID,
        plan_file=hotfix_plan_file(task),
        wave_id=task.node_id.rsplit(":", 1)[-1],
        lane=_HOTFIX_LANE_ID,
        owned_paths=list(task.owned_paths),
        forbidden_paths=list(task.forbidden_paths),
        depends_on=list(task.depends_on),
        verify_targets=list(task.verify_targets),
        provider=task.provider,
        model=task.model,
        agent=task.agent or _DEFAULT_AGENT,
    )


def merge_hotfix_task(graph: RunGraph, task: HotfixTask) -> RunGraph:
    """Return a copy of *graph* with *task* merged (idempotent per ``node_id``)."""
    after_node_id = task.depends_on[0] if task.depends_on else ""
    if task.node_id in graph.nodes:
        insert_orchestrator_serial_after(graph, task.node_id.rsplit(":", 1)[-1], after_node_id)
        return graph
    node = build_hotfix_wave_node(task)
    node = WaveNode(
        **{
            **vars(node),
            "forbidden_paths": derive_forbidden_paths(
                _HOTFIX_LANE_ID,
                graph.lanes,
                node=node,
            ),
        }
    )
    graph.nodes[task.node_id] = node
    lane = graph.lanes.get(_HOTFIX_LANE_ID)
    if lane is None:
        lane = Lane(
            lane_id=_HOTFIX_LANE_ID,
            plans=[_HOTFIX_PLAN_ID],
            owned_paths=list(task.owned_paths),
            waves=[node],
        )
        graph.lanes[_HOTFIX_LANE_ID] = lane
    else:
        lane.waves.append(node)
        lane.owned_paths = list(dict.fromkeys([*lane.owned_paths, *task.owned_paths]))
    batch_index = _batch_for_node(graph, after_node_id) if after_node_id else None
    if batch_index is not None:
        batch = graph.batches[batch_index]
        if _HOTFIX_LANE_ID not in batch.lanes:
            batch.lanes.append(_HOTFIX_LANE_ID)
    elif graph.batches:
        last = graph.batches[-1]
        if not last.is_human_gate and _HOTFIX_LANE_ID not in last.lanes:
            last.lanes.append(_HOTFIX_LANE_ID)
    insert_orchestrator_serial_after(graph, node.wave_id, after_node_id)
    errors = graph.validate()
    if errors:
        raise InjectError(
            "graph validation failed after hotfix merge: " + "; ".join(errors),
            exit_code=3,
        )
    return graph


def build_wave_add_wave_node(task: WaveAddTask) -> WaveNode:
    """Map a :class:`WaveAddTask` to a :class:`WaveNode`."""
    return WaveNode(
        node_id=task.node_id,
        plan_id=task.plan_id,
        plan_file=wave_add_plan_file(task),
        wave_id=task.wave_id,
        lane=task.lane_id,
        owned_paths=list(task.owned_paths),
        forbidden_paths=list(task.forbidden_paths),
        depends_on=list(task.depends_on),
        verify_targets=list(task.verify_targets),
        provider=task.provider,
        model=task.model,
        agent=task.agent or _DEFAULT_AGENT,
    )


def merge_wave_add_task(graph: RunGraph, task: WaveAddTask) -> RunGraph:
    """Return a copy of *graph* with wave-add *task* merged (idempotent per ``node_id``)."""
    after_node_id = task.depends_on[0] if task.depends_on else ""
    if task.node_id in graph.nodes:
        insert_orchestrator_serial_after(graph, task.wave_id, after_node_id)
        return graph
    node = build_wave_add_wave_node(task)
    node = WaveNode(
        **{
            **vars(node),
            "forbidden_paths": derive_forbidden_paths(
                task.lane_id,
                graph.lanes,
                node=node,
            ),
        }
    )
    graph.nodes[task.node_id] = node
    lane = graph.lanes.get(task.lane_id)
    if lane is None:
        lane = Lane(
            lane_id=task.lane_id,
            plans=[task.plan_id],
            owned_paths=list(task.owned_paths),
            waves=[node],
        )
        graph.lanes[task.lane_id] = lane
    else:
        if set(lane.owned_paths) != set(task.owned_paths):
            raise InjectError(
                f"lane {task.lane_id!r} already exists with different owned_paths",
                exit_code=3,
            )
        lane.waves.append(node)
        if task.plan_id not in lane.plans:
            lane.plans.append(task.plan_id)

    batch_index = next(
        (idx for idx, batch in enumerate(graph.batches) if batch.batch_id == task.batch_id),
        None,
    )
    if batch_index is None:
        raise InjectError(
            f"batch {task.batch_id!r} from wave-add artefact not found in graph",
            exit_code=1,
        )
    batch = graph.batches[batch_index]
    if task.lane_id not in batch.lanes:
        batch.lanes.append(task.lane_id)
    if batch.wave_ids and task.wave_id not in batch.wave_ids:
        batch.wave_ids.append(task.wave_id)

    insert_orchestrator_serial_after(graph, task.wave_id, after_node_id)
    errors = graph.validate()
    if errors:
        raise InjectError(
            "graph validation failed after wave-add merge: " + "; ".join(errors),
            exit_code=3,
        )
    return graph


def validate_wave_add_inject(
    graph: RunGraph,
    *,
    run_dir: Path,
    lc: LedgerConnection,
    run_id: str,
    owned_paths: list[str],
    depends_on: list[str] | None = None,
    after: str | None,
    cost_budget_usd: float = 0.0,
) -> tuple[list[str], str]:
    """Run wave-add gate checks; return resolved deps and anchor node id."""
    if not owned_paths:
        raise InjectError("--paths must declare at least one owned path", exit_code=1)
    _assert_run_paused(run_dir, lc, run_id)
    _assert_cost_headroom(lc, run_id, budget_usd=cost_budget_usd)

    dep_labels = list(depends_on or [])
    if after and after.strip():
        dep_labels = [after, *[label for label in dep_labels if label.strip() != after.strip()]]
    resolved = resolve_dep_node_ids(graph, dep_labels)
    anchor_node_id = resolved[0]
    if after and after.strip():
        after_node_id = resolve_after_node_id(graph, after)
        after_wave = get_wave(lc, run_id, after_node_id)
        if after_wave.state != "done":
            raise InjectError(
                f"--after node {after_node_id!r} is {after_wave.state!r}, must be done",
                exit_code=1,
            )
        anchor_node_id = after_node_id
    return resolved, anchor_node_id


__all__ = [
    "HotfixTask",
    "InjectError",
    "ReconcileResult",
    "WaveAddTask",
    "load_hotfix_tasks",
    "load_wave_add_tasks",
    "merge_hotfix_task",
    "merge_wave_add_task",
    "resolve_after_node_id",
    "validate_hotfix_inject",
    "validate_wave_add_inject",
]
