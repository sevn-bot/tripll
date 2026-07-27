"""Live hotfix injection for paused runs (L2-W5a).

Exports:
    HotfixTask — immutable inject spec persisted under ``injects/``.
    InjectError — validation failure with CLI exit code.
    resolve_after_node_id — map ``--after`` to a graph node id.
    validate_hotfix_inject — pause/scope/deps/cost checks.
    plan_hotfix_inject — build task + merged graph without persisting.
    apply_hotfix_inject — write audit artefact, ledger row, graph.json.
    merge_injected_hotfixes — re-apply inject artefacts after plan re-parse.
    load_hotfix_tasks — read all inject specs from a run directory.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — used at runtime throughout this module
from typing import Literal

from loguru import logger

from tripll.graph import Lane, RunGraph, WaveNode, derive_forbidden_paths
from tripll.ledger import (
    LedgerConnection,
    append_event,
    get_run_cost,
    get_wave,
    insert_wave,
    list_waves,
    open_ledger,
)
from tripll.pipeline import RunsRoot  # noqa: TC001 — parameter type used across public API

_INJECT_KIND: Literal["hotfix"] = "hotfix"
_HOTFIX_PLAN_ID = "hotfix"
_HOTFIX_LANE_ID = "hotfix"
_PAUSE_MARKER = "pause-requested.md"
_INFLIGHT_STATES = frozenset({"running", "dispatched", "verifying"})
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


class InjectError(Exception):
    """Inject validation or apply failure with a stable CLI exit code."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


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


def _assert_run_paused(run_dir: Path, lc: LedgerConnection, run_id: str) -> None:
    if not (run_dir / _PAUSE_MARKER).is_file():
        raise InjectError(
            f"run {run_id} is not paused — write pause-requested.md first (tripll pause or API)",
            exit_code=2,
        )
    inflight = [w.node_id for w in list_waves(lc, run_id) if w.state in _INFLIGHT_STATES]
    if inflight:
        raise InjectError(
            f"run {run_id} still has in-flight waves {inflight!r} — wait for drain before inject",
            exit_code=2,
        )


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
) -> str:
    """Run inject gate checks; return resolved ``after`` node id."""
    if not owned_paths:
        raise InjectError("--paths must declare at least one owned path", exit_code=1)
    _assert_run_paused(run_dir, lc, run_id)
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
    if task.node_id in graph.nodes:
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
    after_node_id = task.depends_on[0] if task.depends_on else ""
    batch_index = _batch_for_node(graph, after_node_id) if after_node_id else None
    if batch_index is not None:
        batch = graph.batches[batch_index]
        if _HOTFIX_LANE_ID not in batch.lanes:
            batch.lanes.append(_HOTFIX_LANE_ID)
    elif graph.batches:
        last = graph.batches[-1]
        if not last.is_human_gate and _HOTFIX_LANE_ID not in last.lanes:
            last.lanes.append(_HOTFIX_LANE_ID)
    if graph.orchestrator is not None and graph.orchestrator.enabled:
        cfg = graph.orchestrator
        wave_id = node.wave_id
        if wave_id not in cfg.serial_waves:
            after_node = graph.nodes.get(after_node_id) if after_node_id else None
            after_wave_id = after_node.wave_id if after_node is not None else ""
            if after_wave_id and after_wave_id in cfg.serial_waves:
                idx = cfg.serial_waves.index(after_wave_id) + 1
                cfg.serial_waves.insert(idx, wave_id)
            else:
                cfg.serial_waves.append(wave_id)
    errors = graph.validate()
    if errors:
        raise InjectError(
            "graph validation failed after hotfix merge: " + "; ".join(errors),
            exit_code=3,
        )
    return graph


def merge_injected_hotfixes(graph: RunGraph, run_dir: Path) -> RunGraph:
    """Re-merge all hotfix inject artefacts into a freshly parsed graph."""
    for task in load_hotfix_tasks(run_dir):
        if task.node_id not in graph.nodes:
            graph = merge_hotfix_task(graph, task)
    return graph


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
    repo_root: Path | None = None,
) -> tuple[HotfixTask, RunGraph]:
    """Validate and build a hotfix task + merged graph without persisting."""
    from tripll.parse import build_graph_from_dir

    run_dir = rr.run_dir(run_id)
    if not run_dir.is_dir():
        raise InjectError(f"run not found in processing/: {run_id}", exit_code=1)
    graph = build_graph_from_dir(run_dir, run_id=run_id)
    graph = merge_injected_hotfixes(graph, run_dir)
    with open_ledger(rr.ledger_path(run_id)) as lc:
        after_node_id = validate_hotfix_inject(
            graph,
            run_dir=run_dir,
            lc=lc,
            run_id=run_id,
            owned_paths=owned_paths,
            after=after,
            cost_budget_usd=cost_budget_usd,
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
        injected_by="cli",
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
    dry_run: bool = False,
    repo_root: Path | None = None,
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
        repo_root=repo_root,
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

    lock_path = run_dir / "inject.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError as exc:
        raise InjectError("inject.lock held — another inject in progress", exit_code=2) from exc

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
