"""Pure dispatch scheduling helpers extracted from :mod:`tripll.engine`.

Selects which wave nodes are ready to dispatch, whether pairs may run
concurrently (path-disjoint + late CW gates), and orchestrator serial order.

Exports:
    human_gate_node_ids — node ids in human-gate batches.
    nodes_for_batch — wave nodes belonging to one batch.
    ready_nodes — pure ready-wave selection (deps satisfied).
    can_run_concurrently — pure concurrency-gate predicate (D5/W5.2).
    select_concurrent_set — greedy maximal pairwise-disjoint selection.
    orchestrator_serial_nodes — order nodes for orchestrator serial execution.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from tripll.graph import Batch, RunGraph, WaveNode, paths_overlap

if TYPE_CHECKING:
    from collections.abc import Iterable


def _late_cw_paths() -> frozenset[str]:
    import tripll.graph as graph_mod

    hotspots = graph_mod.CW_HOTSPOTS
    return frozenset(hotspots.get("CW-4", []) + hotspots.get("CW-5", []))


def human_gate_node_ids(graph: RunGraph) -> set[str]:
    """Return node ids for waves in human-gate batches (Pre-0 / review gate only).

    Args:
        graph (RunGraph): Parsed execution graph.

    Returns:
        set[str]: Node ids that are human gates (no agent dispatch).
    """
    ids: set[str] = set()
    for batch in graph.batches:
        if not batch.is_human_gate or not batch.wave_ids:
            continue
        for lane_id in batch.lanes:
            for wave_id in batch.wave_ids:
                node_id = f"{lane_id}:{wave_id}"
                if node_id in graph.nodes:
                    ids.add(node_id)
    return ids


def nodes_for_batch(graph: RunGraph, batch: Batch) -> list[WaveNode]:
    """Return wave nodes belonging to *batch* (respects ``batch.wave_ids`` when set).

    Args:
        graph (RunGraph): Parsed execution graph.
        batch (Batch): One batch row from the graph.

    Returns:
        list[WaveNode]: Nodes in *batch* lanes (filtered by ``wave_ids`` when set).
    """
    out: list[WaveNode] = []
    for lane_id in batch.lanes:
        lane = graph.lanes.get(lane_id)
        if lane is None:
            continue
        for wave in lane.waves:
            if wave.node_id not in graph.nodes:
                continue
            if batch.wave_ids and wave.wave_id not in batch.wave_ids:
                continue
            out.append(graph.nodes[wave.node_id])
    return out


def ready_nodes(nodes: Iterable[WaveNode], done: set[str]) -> list[WaveNode]:
    """Return nodes whose dependencies are all satisfied and not yet done.

    Args:
        nodes (Iterable[WaveNode]): Candidate nodes.
        done (set[str]): node_ids already completed.

    Returns:
        list[WaveNode]: Nodes ready to dispatch.
    """
    out: list[WaveNode] = []
    for node in nodes:
        if node.node_id in done:
            continue
        if all(dep in done for dep in node.depends_on):
            out.append(node)
    return out


def _touches_late_cw(node: WaveNode) -> bool:
    for owned in node.owned_paths:
        o = owned.rstrip("/")
        for cw in _late_cw_paths():
            c = cw.rstrip("/")
            if o == c or o.startswith(c + "/") or c.startswith(o + "/"):
                return True
    return False


def can_run_concurrently(a: WaveNode, b: WaveNode) -> bool:
    """Return True when two nodes may run in parallel within a phase (W5.2).

    Args:
        a (WaveNode): First node.
        b (WaveNode): Second node.

    Returns:
        bool: True if the pair may run concurrently.
    """
    if paths_overlap(a.owned_paths, b.owned_paths):
        return False
    return not (_touches_late_cw(a) and _touches_late_cw(b))


def select_concurrent_set(candidates: list[WaveNode]) -> list[WaveNode]:
    """Greedily select a maximal pairwise-disjoint subset from *candidates*.

    Args:
        candidates (list[WaveNode]): Ready nodes to choose from.

    Returns:
        list[WaveNode]: The largest prefix-consistent concurrent set.
    """
    selected: list[WaveNode] = []
    for node in candidates:
        if all(can_run_concurrently(node, s) for s in selected):
            selected.append(node)
    return selected


def _topological_sort_nodes(graph: RunGraph) -> list[WaveNode]:
    nodes = list(graph.nodes.values())
    done: set[str] = set()
    ordered: list[WaveNode] = []
    while len(ordered) < len(nodes):
        progressed = False
        for node in nodes:
            if node.node_id in done:
                continue
            if all(dep in done for dep in node.depends_on):
                ordered.append(node)
                done.add(node.node_id)
                progressed = True
        if not progressed:
            break
    return ordered


def orchestrator_serial_nodes(graph: RunGraph) -> list[WaveNode]:
    """Order nodes for orchestrator serial execution (W2.1).

    Args:
        graph (RunGraph): Parsed execution graph.

    Returns:
        list[WaveNode]: Nodes ordered by ``orchestrator.serial_waves`` then topo sort.
    """
    cfg = graph.orchestrator
    if cfg is None:
        return _topological_sort_nodes(graph)
    by_wave: dict[str, list[WaveNode]] = {}
    for node in graph.nodes.values():
        by_wave.setdefault(node.wave_id, []).append(node)
    ordered: list[WaveNode] = []
    for wid in cfg.serial_waves:
        ordered.extend(by_wave.get(wid, []))
    seen = {n.node_id for n in ordered}
    for node in _topological_sort_nodes(graph):
        if node.node_id not in seen:
            ordered.append(node)
    return ordered


_DEFAULT_MAX_PARALLEL = 3


def max_parallel_from_env() -> int:
    """Read ``TRIPLL_MAX_PARALLEL`` from the environment (default 3).

    Returns:
        int: Maximum number of nodes to run concurrently within a batch.

    Examples:
        >>> isinstance(max_parallel_from_env(), int)
        True
    """
    try:
        v = int(os.environ.get("TRIPLL_MAX_PARALLEL", _DEFAULT_MAX_PARALLEL))
        return max(1, v)
    except (ValueError, TypeError):
        return _DEFAULT_MAX_PARALLEL
