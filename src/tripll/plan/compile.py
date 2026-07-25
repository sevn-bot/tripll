"""Compile a v3 plan into layer-``task`` graph nodes and edges."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from tripll.plan.shape_checks import compile_plan

if TYPE_CHECKING:
    from tripll.graphstore import EdgeInput, NodeInput

_EXTRACTOR = "tripll.plan.compile"
_EXTRACTOR_VERSION = "0.1.0"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _prov(*, source: str, evidence: str) -> dict[str, Any]:
    return {
        "source": source,
        "evidence": evidence,
        "extractor": _EXTRACTOR,
        "extractor_version": _EXTRACTOR_VERSION,
        "confidence": 1.0,
        "extracted_at": _now_iso(),
    }


def _node_id(layer: str, kind: str, natural_key: str) -> str:
    return f"{layer}:{kind}:{natural_key}"


def compile_plan_to_task_graph(
    plan: dict[str, Any],
    *,
    repo: str | None = None,
    source: str = "plan.compile",
    evidence: str | None = None,
) -> tuple[list[NodeInput], list[EdgeInput]]:
    """Compile a validated v3 plan into task-layer nodes/edges plus TARGETS joins."""
    cleaned = compile_plan(plan)
    slug = str(cleaned.get("slug") or "plan")
    plan_key = slug
    evidence_ref = evidence or f"plan:{slug}"
    prov = _prov(source=source, evidence=evidence_ref)
    nodes: list[NodeInput] = []
    edges: list[EdgeInput] = []

    plan_node_id = _node_id("task", "Plan", plan_key)
    nodes.append(
        {
            "node_id": plan_node_id,
            "layer": "task",
            "kind": "Plan",
            "natural_key": plan_key,
            "repo": repo,
            "props": json.dumps(
                {
                    "title": cleaned.get("title"),
                    "target_repo": cleaned.get("target_repo"),
                    "pipeline": cleaned.get("pipeline"),
                }
            ),
            **prov,
        }
    )

    module_nodes: dict[str, str] = {}
    for wave in cleaned.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        wave_id = str(wave.get("id", ""))
        if not wave_id:
            continue
        wave_key = f"{plan_key}#{wave_id}"
        wave_node_id = _node_id("task", "Wave", wave_key)
        nodes.append(
            {
                "node_id": wave_node_id,
                "layer": "task",
                "kind": "Wave",
                "natural_key": wave_key,
                "repo": repo,
                "props": json.dumps(
                    {
                        "title": wave.get("title"),
                        "role": wave.get("role"),
                        "effort": wave.get("effort"),
                        "verify": wave.get("verify"),
                        "outcome": wave.get("outcome"),
                    }
                ),
                **prov,
            }
        )
        edges.append(
            {
                "edge_id": str(uuid.uuid4()),
                "predicate": "PART_OF",
                "src": wave_node_id,
                "dst": plan_node_id,
                "props": "{}",
                "reason": None,
                **prov,
            }
        )
        for dep in wave.get("depends_on") or []:
            if not isinstance(dep, dict):
                continue
            parent_id = str(dep.get("wave", ""))
            if not parent_id:
                continue
            parent_key = f"{plan_key}#{parent_id}"
            parent_node_id = _node_id("task", "Wave", parent_key)
            edges.append(
                {
                    "edge_id": str(uuid.uuid4()),
                    "predicate": "DEPENDS_ON",
                    "src": wave_node_id,
                    "dst": parent_node_id,
                    "props": json.dumps({"detail": dep.get("detail")}),
                    "reason": str(dep.get("reason")),
                    **prov,
                }
            )
        for target in wave.get("targets") or []:
            target_path = str(target)
            module_key = target_path
            module_node_id = module_nodes.get(module_key)
            if module_node_id is None:
                module_node_id = _node_id("code", "Module", module_key)
                module_nodes[module_key] = module_node_id
                nodes.append(
                    {
                        "node_id": module_node_id,
                        "layer": "code",
                        "kind": "Module",
                        "natural_key": module_key,
                        "repo": repo,
                        "props": json.dumps({"path": target_path}),
                        **prov,
                    }
                )
            edges.append(
                {
                    "edge_id": str(uuid.uuid4()),
                    "predicate": "TARGETS",
                    "src": wave_node_id,
                    "dst": module_node_id,
                    "props": "{}",
                    "reason": None,
                    **prov,
                }
            )
    return nodes, edges
