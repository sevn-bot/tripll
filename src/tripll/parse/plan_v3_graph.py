"""Build a :class:`~tripll.graph.RunGraph` from a v3 TOML wave plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.graph import Batch, Lane, RunGraph, batch_cw_seams, derive_forbidden_paths
from tripll.parse.orchestrator_prompt import attach_orchestrator_config
from tripll.parse.plan_files import _slug, collect_pre0_gates_from_plans, parse_plan_file
from tripll.parse.plan_v3 import read_plan_file
from tripll.parse.wave_plan_v1 import BatchSpec, WaveSpec, _infer_batches_from_waves
from tripll.plan.providers import wave_node_from_v3

if TYPE_CHECKING:
    from pathlib import Path


def _wave_specs_from_v3(waves: list[dict[str, object]]) -> list[WaveSpec]:
    """Adapt v3 waves to the batch-inference shape used by v1 plans."""
    specs: list[WaveSpec] = []
    for wave in waves:
        wid = str(wave.get("id", ""))
        if not wid:
            continue
        depends_raw = wave.get("depends_on")
        depends_on: list[dict[str, object]] = (
            [d for d in depends_raw if isinstance(d, dict)] if isinstance(depends_raw, list) else []
        )
        depends = [str(dep.get("wave", "")) for dep in depends_on]
        verify_raw = wave.get("verify")
        verify_targets = (
            [str(v) for v in verify_raw] if isinstance(verify_raw, list) else ["make ci-affected"]
        )
        specs.append(
            WaveSpec(
                wave_id=wid,
                title=str(wave.get("title") or wid),
                depends_on=[d for d in depends if d],
                review_gate=bool(wave.get("human")),
                effort=str(wave.get("effort") or "M").split()[0],
                verify_targets=verify_targets or ["make ci-affected"],
                model=str(wave.get("model")).strip() if wave.get("model") else None,
                role=str(wave.get("role") or "impl"),
            )
        )
    return specs


def build_graph_from_v3_plan(path: Path, *, run_id: str) -> RunGraph:
    """Build a :class:`RunGraph` from one v3 TOML wave-plan file.

    Args:
        path (Path): ``*-wave-plan.md`` containing ``waveorch_format = 3``.
        run_id (str): Run identifier.

    Returns:
        RunGraph: Graph with per-wave provider routing fields populated.
    """
    text = path.read_text(encoding="utf-8")
    plan, _warnings = read_plan_file(path)
    plan_id = _slug(path)
    title = str(plan.get("title") or plan_id)
    waves = [w for w in (plan.get("waves") or []) if isinstance(w, dict)]
    owned_paths: list[str] = []
    for wave in waves:
        owned_paths.extend(str(t) for t in (wave.get("targets") or []))
    owned_paths = sorted(set(owned_paths))

    graph = RunGraph(run_id=run_id, source_mode="B")
    lane = Lane(lane_id=plan_id, owned_paths=owned_paths, plans=[plan_id])
    graph.lanes[plan_id] = lane

    node_id_map: dict[str, str] = {
        str(w["id"]): f"{plan_id}:{w['id']}" for w in waves if w.get("id")
    }

    for wave in waves:
        node = wave_node_from_v3(
            wave,
            plan_id=plan_id,
            plan_file=path.name,
            lane=title,
            owned_paths=owned_paths,
            node_id_map=node_id_map,
        )
        graph.nodes[node.node_id] = node
        lane.waves.append(node)

    for node in graph.nodes.values():
        node.forbidden_paths = derive_forbidden_paths(plan_id, graph.lanes, node=node)

    specs = _wave_specs_from_v3(waves)
    batch_specs: list[BatchSpec] = _infer_batches_from_waves(specs)
    for bs in batch_specs:
        cw = batch_cw_seams(bs.batch_id)
        label = bs.batch_id
        if bs.wave_ids:
            label = f"{bs.batch_id} — {', '.join(bs.wave_ids)}"
        if bs.human_gate:
            label = "HUMAN GATE — operator decisions"
        graph.batches.append(
            Batch(
                batch_id=bs.batch_id,
                label=label,
                lanes=[plan_id] if bs.wave_ids else [],
                is_human_gate=bs.human_gate,
                gate_commands=["make ci-resume"] if bs.batch_id == "Final" else [],
                cw_seams=cw,
                merge_order=[plan_id] if bs.wave_ids else [],
                wave_ids=list(bs.wave_ids),
            )
        )

    plan_meta = [parse_plan_file(path)]
    graph.pre0_gates = collect_pre0_gates_from_plans(plan_meta)
    if not graph.pre0_gates:
        graph.pre0_gates = [
            f"{w.wave_id}: review gate" for w in graph.nodes.values() if w.is_review_gate
        ]

    return attach_orchestrator_config(
        graph,
        path.parent,
        slug=plan_id,
        wave_plan_text=text,
    )


def is_v3_plan_file(path: Path) -> bool:
    """Return True when *path* contains a v3 ``waveorch_format`` TOML block."""
    head = path.read_text(encoding="utf-8")[:800]
    return "waveorch_format = 3" in head or "waveorch_format=3" in head
