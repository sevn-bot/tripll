"""Sync layer ``task`` nodes alongside the authoritative ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tripll.graphstore import EdgeInput, GraphStore, NodeInput, SqliteGraphStore

if TYPE_CHECKING:
    from tripll.graph import RunGraph

_EXTRACTOR = "tripll.task_sync"
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


def content_hash(text: str) -> str:
    """Return a hex digest for agent/prompt definition content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _agent_def_path(agent_slug: str, repo_root: Path) -> Path | None:
    skw_path = repo_root / "src" / "tripll" / "skw" / "agents" / f"{agent_slug}.md"
    if skw_path.is_file():
        return skw_path
    return None


def hash_agent_def(agent_slug: str, repo_root: Path) -> tuple[str, str, str] | None:
    """Return ``(node_id, natural_key, digest)`` when the agent file exists."""
    path = _agent_def_path(agent_slug, repo_root)
    if path is None:
        return None
    digest = content_hash(path.read_text(encoding="utf-8"))
    natural_key = f"{agent_slug}#{digest[:16]}"
    node_id = f"task:AgentDef:{natural_key}"
    return node_id, natural_key, digest


def hash_prompt_def(prompt_path: Path) -> tuple[str, str, str]:
    """Return ``(node_id, natural_key, digest)`` for a prompt file."""
    digest = content_hash(prompt_path.read_text(encoding="utf-8"))
    rel = prompt_path.as_posix()
    natural_key = f"{rel}#{digest[:16]}"
    node_id = f"task:PromptDef:{natural_key}"
    return node_id, natural_key, digest


class TaskGraphWriter:
    """Write task-layer nodes alongside ledger mutations."""

    def __init__(self, db_path: Path) -> None:
        self._store = SqliteGraphStore(str(db_path))
        self._repo_root = Path.cwd()

    @property
    def store(self) -> SqliteGraphStore:
        return self._store

    def close(self) -> None:
        self._store.close()

    def sync_run_start(
        self,
        *,
        run_id: str,
        graph: RunGraph,
        backend: str,
        model: str | None,
        agent: str | None,
    ) -> None:
        plan_ids = {node.plan_id for node in graph.nodes.values()}
        nodes: list[NodeInput] = []
        edges: list[EdgeInput] = []
        for plan_id in plan_ids:
            plan_key = f"{run_id}#{plan_id}"
            plan_nid = f"task:Plan:{plan_key}"
            base = _prov(source="ledger", evidence=f"run:{run_id}")
            nodes.append(
                NodeInput(
                    node_id=plan_nid,
                    layer="task",
                    kind="Plan",
                    natural_key=plan_key,
                    repo=None,
                    props=json.dumps({"run_id": run_id, "plan_id": plan_id}),
                    **base,
                )
            )
        for wave in graph.nodes.values():
            wave_key = f"{run_id}#{wave.node_id}"
            wave_nid = f"task:Wave:{wave_key}"
            base = _prov(source="ledger", evidence=f"wave:{wave.node_id}")
            nodes.append(
                NodeInput(
                    node_id=wave_nid,
                    layer="task",
                    kind="Wave",
                    natural_key=wave_key,
                    repo=None,
                    props=json.dumps(
                        {
                            "run_id": run_id,
                            "node_id": wave.node_id,
                            "wave_id": wave.wave_id,
                            "lane": wave.lane,
                            "state": "queued",
                        }
                    ),
                    **base,
                )
            )
            plan_nid = f"task:Plan:{run_id}#{wave.plan_id}"
            edges.append(
                EdgeInput(
                    edge_id=f"part_of:{wave_nid}",
                    predicate="PART_OF",
                    src=wave_nid,
                    dst=plan_nid,
                    **_prov(source="ledger", evidence=f"wave:{wave.node_id}"),
                )
            )
            for dep in wave.depends_on:
                dep_nid = f"task:Wave:{run_id}#{dep}"
                edges.append(
                    EdgeInput(
                        edge_id=f"depends:{wave_nid}:{dep_nid}",
                        predicate="DEPENDS_ON",
                        src=wave_nid,
                        dst=dep_nid,
                        reason="artifact",
                        **_prov(source="ledger", evidence=f"wave:{wave.node_id}"),
                    )
                )
        if model:
            model_key = f"{backend}#{model}"
            model_nid = f"task:ModelRef:{model_key}"
            nodes.append(
                NodeInput(
                    node_id=model_nid,
                    layer="task",
                    kind="ModelRef",
                    natural_key=model_key,
                    repo=None,
                    props=json.dumps({"backend": backend, "model": model}),
                    **_prov(source="dispatch-config", evidence=f"run:{run_id}"),
                )
            )
        if agent:
            agent_info = hash_agent_def(agent, self._repo_root)
            if agent_info:
                agent_nid, agent_key, digest = agent_info
                agent_path = _agent_def_path(agent, self._repo_root)
                nodes.append(
                    NodeInput(
                        node_id=agent_nid,
                        layer="task",
                        kind="AgentDef",
                        natural_key=agent_key,
                        repo=None,
                        props=json.dumps(
                            {"agent_slug": agent, "content_hash": digest, "path": agent}
                        ),
                        **_prov(
                            source="agent-def",
                            evidence=agent_path.as_posix() if agent_path else f"agents/{agent}.md",
                        ),
                    )
                )
        if nodes:
            self._store.upsert_nodes(nodes)
        if edges:
            self._store.upsert_edges(edges)

    def sync_wave_transition(
        self,
        *,
        run_id: str,
        node_id: str,
        new_state: str,
    ) -> None:
        wave_key = f"{run_id}#{node_id}"
        wave_nid = f"task:Wave:{wave_key}"
        existing = self._store.get(wave_nid)
        props: dict[str, Any] = {}
        if existing is not None:
            props = json.loads(existing.props)
        props["state"] = new_state
        self._store.upsert_nodes(
            [
                NodeInput(
                    node_id=wave_nid,
                    layer="task",
                    kind="Wave",
                    natural_key=wave_key,
                    repo=None,
                    props=json.dumps(props),
                    **_prov(source="ledger", evidence=f"transition:{node_id}:{new_state}"),
                )
            ]
        )

    def sync_attempt(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt_id: str,
        attempt_n: int,
        backend: str,
        model: str | None = None,
        agent: str | None = None,
    ) -> None:
        attempt_key = f"{run_id}#{attempt_id}"
        attempt_nid = f"task:Attempt:{attempt_key}"
        wave_nid = f"task:Wave:{run_id}#{node_id}"
        nodes: list[NodeInput] = [
            NodeInput(
                node_id=attempt_nid,
                layer="task",
                kind="Attempt",
                natural_key=attempt_key,
                repo=None,
                props=json.dumps(
                    {
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "attempt_n": attempt_n,
                        "backend": backend,
                    }
                ),
                **_prov(source="ledger", evidence=f"attempt:{attempt_id}"),
            )
        ]
        edges: list[EdgeInput] = [
            EdgeInput(
                edge_id=f"attempt_of:{attempt_nid}",
                predicate="ATTEMPT_OF",
                src=attempt_nid,
                dst=wave_nid,
                **_prov(source="ledger", evidence=f"attempt:{attempt_id}"),
            )
        ]
        if model:
            model_key = f"{backend}#{model}"
            model_nid = f"task:ModelRef:{model_key}"
            nodes.append(
                NodeInput(
                    node_id=model_nid,
                    layer="task",
                    kind="ModelRef",
                    natural_key=model_key,
                    repo=None,
                    props=json.dumps({"backend": backend, "model": model}),
                    **_prov(source="ledger", evidence=f"attempt:{attempt_id}"),
                )
            )
            edges.append(
                EdgeInput(
                    edge_id=f"used_model:{attempt_nid}:{model_nid}",
                    predicate="USED_MODEL",
                    src=attempt_nid,
                    dst=model_nid,
                    **_prov(source="ledger", evidence=f"attempt:{attempt_id}"),
                )
            )
        if agent:
            agent_info = hash_agent_def(agent, self._repo_root)
            if agent_info:
                agent_nid, agent_key, digest = agent_info
                agent_path = _agent_def_path(agent, self._repo_root)
                nodes.append(
                    NodeInput(
                        node_id=agent_nid,
                        layer="task",
                        kind="AgentDef",
                        natural_key=agent_key,
                        repo=None,
                        props=json.dumps({"agent_slug": agent, "content_hash": digest}),
                        **_prov(
                            source="agent-def",
                            evidence=agent_path.as_posix() if agent_path else f"agents/{agent}.md",
                        ),
                    )
                )
                edges.append(
                    EdgeInput(
                        edge_id=f"ran_agent:{attempt_nid}:{agent_nid}",
                        predicate="RAN_AGENT",
                        src=attempt_nid,
                        dst=agent_nid,
                        **_prov(source="ledger", evidence=f"attempt:{attempt_id}"),
                    )
                )
        self._store.upsert_nodes(nodes)
        self._store.upsert_edges(edges)


def sync_rule_to_store(
    rule: Any,
    *,
    store: GraphStore | str,
    repo: str,
    finding: dict[str, Any] | None = None,
) -> str:
    """Upsert a repo-scoped Rule node and optional Finding edges (W3.1, R26).

    Args:
        rule: :class:`tripll.rules.model.Rule` instance.
        store (GraphStore | str): Graph store or SQLite path.
        repo (str): Repository slug for natural key ``{repo}#{rule_id}``.
        finding (dict[str, Any] | None): Source finding for ``PROMOTED_FROM`` / ``PREVENTS``.

    Returns:
        str: Graph node id ``finding:Rule:{repo}#{rule_id}``.
    """
    from tripll.rules.model import Rule

    if not isinstance(rule, Rule):
        msg = f"sync_rule_to_store expected Rule, got {type(rule).__name__}"
        raise TypeError(msg)

    graph = store if isinstance(store, SqliteGraphStore) else SqliteGraphStore(str(store))
    natural_key = f"{repo}#{rule.rule_id}"
    node_id = f"finding:Rule:{natural_key}"
    base = _prov(source="rules.promote", evidence=f"rule:{rule.rule_id}")
    props = {
        "rule_id": rule.rule_id,
        "state": rule.state,
        "origin": rule.origin,
        "scope": rule.scope,
        "executable": rule.executable,
        "severity": rule.severity,
    }
    graph.upsert_nodes(
        [
            NodeInput(
                node_id=node_id,
                layer="finding",
                kind="Rule",
                natural_key=natural_key,
                repo=repo,
                props=json.dumps(props),
                **base,
            )
        ]
    )

    if finding is not None:
        run_id = str(finding.get("run_id") or "local")
        finding_id = str(finding.get("finding_id") or "")
        if finding_id:
            finding_nid = f"finding:Finding:{run_id}#{finding_id}"
            edges: list[EdgeInput] = []
            for predicate in ("PREVENTS", "PROMOTED_FROM"):
                edges.append(
                    EdgeInput(
                        edge_id=f"{predicate.lower()}:{node_id}:{finding_nid}",
                        predicate=predicate,
                        src=node_id,
                        dst=finding_nid,
                        **base,
                    )
                )
            graph.upsert_edges(edges)

    return node_id
