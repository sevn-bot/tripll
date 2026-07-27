"""L1 loop dispatch bridge — adapter invocation seam (W9).

Translates loop-node dispatch metadata into real
:class:`~tripll.adapters.base.AgentAdapter` calls, following the Engine
worktree → brief → dispatch path without duplicating ``Engine`` itself.

Exports:
    LoopDispatchResult — outcome of one loop agent dispatch.
    build_loop_brief — JSON brief for a loop agent slug.
    resolve_loop_adapter — adapter from run dispatch config + agent slug.
    invoke_loop_dispatches — sync entry for LangGraph PR-loop nodes.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tripll.adapters.base import AgentAdapter
    from tripll.loops.state import L1OuterState

_DEFAULT_TIMEOUT_S = 600

__all__ = [
    "LoopDispatchResult",
    "build_loop_brief",
    "invoke_loop_dispatches",
    "resolve_loop_adapter",
]


@dataclass(frozen=True, slots=True)
class LoopDispatchResult:
    """Outcome of one L1 loop adapter dispatch.

    Args:
        agent (str): Agent slug (``ci-investigator``, ``check-fixer``, …).
        action (str): Loop action (``investigate``, ``fix``, …).
        outcome (str): Adapter dispatch outcome.
        finding_id (str | None): Finding identifier when present.
        result_text (str): Truncated agent result text.
    """

    agent: str
    action: str
    outcome: str
    finding_id: str | None = None
    result_text: str = ""


def _state_run_dir(state: L1OuterState) -> Path | None:
    raw = state.get("run_dir")
    if isinstance(raw, Path):
        return raw
    if isinstance(raw, str) and raw.strip():
        return Path(raw)
    return None


def _loop_worktree_path(*, run_id: str, run_dir: Path | None) -> Path:
    if run_dir is not None:
        wt = run_dir / "loop-worktree"
        wt.mkdir(parents=True, exist_ok=True)
        return wt
    from tripll.repo_root import resolve_repo_root

    wt = resolve_repo_root() / ".tripll" / "loop-worktree" / run_id
    wt.mkdir(parents=True, exist_ok=True)
    return wt


def build_loop_brief(
    *,
    run_id: str,
    agent: str,
    action: str,
    finding_id: str | None,
    kind: str,
    worktree_path: Path,
    branch: str,
) -> dict[str, object]:
    """Build a JSON dispatch brief for an L1 PR-loop agent.

    Args:
        run_id (str): Parent run identifier.
        agent (str): Agent slug to dispatch.
        action (str): Loop action name.
        finding_id (str | None): Open finding id, if any.
        kind (str): Finding kind (``ci_check``, …).
        worktree_path (Path): Checkout directory for the adapter CLI.
        branch (str): Git branch label for the brief.

    Returns:
        dict[str, object]: Brief dict consumed by :meth:`AgentAdapter.dispatch`.
    """
    fid = finding_id or "none"
    node_id = f"l1-pr:{action}:{fid}"
    return {
        "node_id": node_id,
        "wave_id": "L1-PR",
        "plan_file": "l1-pr-loop",
        "plan_worktree_path": "",
        "branch": branch,
        "worktree_path": str(worktree_path),
        "owned_paths": [],
        "forbidden_paths": [],
        "verify_targets": [],
        "prerequisite_waves": [],
        "locked_decisions": [],
        "manual_smoke_deferred": [],
        "agent_directives": [
            f"L1 PR loop — {action} finding {finding_id!r} ({kind}).",
            "Leave changes staged; do not commit.",
        ],
        "workspace_scope": [],
        "agent": agent,
        "finding_id": finding_id,
        "finding_kind": kind,
        "loop_action": action,
        "run_id": run_id,
    }


def resolve_loop_adapter(
    run_dir: Path | None,
    agent: str,
    *,
    adapter: AgentAdapter | None = None,
) -> AgentAdapter:
    """Resolve the adapter for a loop dispatch (run config → backend + agent slug).

    Args:
        run_dir (Path | None): Run directory with optional ``dispatch-config.json``.
        agent (str): Agent slug for this loop step.
        adapter (AgentAdapter | None): Explicit override (tests / injection).

    Returns:
        AgentAdapter: Backend configured for *agent*.
    """
    if adapter is not None:
        return adapter
    from tripll.adapters import build_adapter
    from tripll.adapters.options import BackendOptions
    from tripll.run_dispatch import read_dispatch_config

    backend = "cursor_local"
    model: str | None = None
    if run_dir is not None:
        cfg = read_dispatch_config(run_dir)
        if cfg is not None:
            backend = cfg.backend
            model = cfg.model
    return build_adapter(backend, options=BackendOptions(model=model, agent=agent))


async def _dispatch_one(
    meta: dict[str, Any],
    *,
    run_id: str,
    run_dir: Path | None,
    worktree_path: Path,
    adapter_override: AgentAdapter | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> LoopDispatchResult:
    agent = str(meta.get("agent") or "")
    action = str(meta.get("action") or "")
    raw_fid = meta.get("finding_id")
    finding_id = str(raw_fid) if raw_fid is not None else None
    kind = str(meta.get("kind") or "ci_check")
    branch = f"l1-pr/{run_id}"

    loop_adapter = resolve_loop_adapter(run_dir, agent, adapter=adapter_override)
    brief = build_loop_brief(
        run_id=run_id,
        agent=agent,
        action=action,
        finding_id=finding_id,
        kind=kind,
        worktree_path=worktree_path,
        branch=branch,
    )

    log_root = run_dir if run_dir is not None else worktree_path
    log_dir = log_root / "logs" / "l1-pr"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_fid = (finding_id or "none").replace("/", "_")
    log_path = log_dir / f"{action}-{safe_fid}.log"

    result = await loop_adapter.dispatch(
        brief,
        worktree_path=worktree_path,
        log_path=log_path,
        timeout_s=timeout_s,
        log_header={
            "run_id": run_id,
            "node_id": str(brief["node_id"]),
            "backend": loop_adapter.name,
        },
    )
    return LoopDispatchResult(
        agent=agent,
        action=action,
        outcome=result.outcome,
        finding_id=finding_id,
        result_text=(result.result_text or "")[:4000],
    )


def invoke_loop_dispatches(
    state: L1OuterState,
    dispatch_meta: list[dict[str, Any]],
    *,
    node: str,
    adapter: AgentAdapter | None = None,
) -> list[LoopDispatchResult]:
    """Invoke adapter dispatch for each metadata dict (sync LangGraph node entry).

    Args:
        state (L1OuterState): Current PR-loop graph state.
        dispatch_meta (list[dict[str, Any]]): Per-finding dispatch descriptors.
        node (str): Calling node name (``investigate`` / ``fix``) for logging.
        adapter (AgentAdapter | None): Optional adapter override for tests.

    Returns:
        list[LoopDispatchResult]: One result per metadata entry.

    Raises:
        RuntimeError: When the ``graph`` extra is not installed.
    """
    from tripll.loops import require_graph

    require_graph(feature=f"L1 PR loop {node} dispatch")
    if not dispatch_meta:
        return []

    run_id = str(state.get("run_id") or state.get("thread_id") or "default")
    run_dir = _state_run_dir(state)
    worktree_path = _loop_worktree_path(run_id=run_id, run_dir=run_dir)

    async def _run_all() -> list[LoopDispatchResult]:
        results: list[LoopDispatchResult] = []
        for meta in dispatch_meta:
            results.append(
                await _dispatch_one(
                    meta,
                    run_id=run_id,
                    run_dir=run_dir,
                    worktree_path=worktree_path,
                    adapter_override=adapter,
                )
            )
        return results

    return asyncio.run(_run_all())


def dispatch_results_as_dicts(results: list[LoopDispatchResult]) -> list[dict[str, Any]]:
    """Serialize loop dispatch results for LangGraph state updates."""
    return [asdict(r) for r in results]
