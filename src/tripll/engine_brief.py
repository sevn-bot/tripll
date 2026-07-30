"""Dispatch brief builders extracted from :class:`~tripll.engine.Engine`.

Exports:
    append_external_upload_dirs — merge external plan upload dirs into workspace scope.
    brief_for — build JSON dispatch brief for one wave node.
    safe_node_id — filename-safe form of a node id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.brief import (
    enrich_brief_with_graph_pack,
    enrich_brief_with_rules_pack,
    render_json_brief,
)
from tripll.worktrees import Worktree, staged_wave_plan_path

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.adapters.pools import ProviderPoolRegistry
    from tripll.graph import RunGraph, WaveNode
    from tripll.pipeline import RunsRoot


def safe_node_id(node_id: str) -> str:
    """Return a filename-safe form of *node_id*.

    Args:
        node_id (str): Raw node id.

    Returns:
        str: Sanitised id.

    Examples:
        >>> safe_node_id("telemetry:W0->Final")
        'telemetry_W0-Final'
    """
    return node_id.replace(":", "_").replace("/", "_").replace(">", "")


def append_external_upload_dirs(
    brief: dict[str, object],
    worktree_path: Path,
) -> dict[str, object]:
    """Append external upload parent dirs to ``workspace_scope`` (D3).

    Args:
        brief (dict[str, object]): Dispatch brief from :func:`render_json_brief`.
        worktree_path (Path): Lane worktree root.

    Returns:
        dict[str, object]: *brief* with external dirs merged into ``workspace_scope``.

    Examples:
        >>> from pathlib import Path
        >>> b = append_external_upload_dirs({"workspace_scope": ["src/"]}, Path("/wt"))
        >>> "workspace_scope" in b
        True
    """
    from tripll.plan_paths import normalize_plan_refs

    repo_root = worktree_path.resolve()
    staged_dir = repo_root / "plan" / "tripll"
    external_dirs: list[str] = []
    if staged_dir.is_dir():
        for path in sorted(staged_dir.glob("*.md")):
            _, dirs = normalize_plan_refs(path.read_text(encoding="utf-8"), repo_root)
            external_dirs.extend(dirs)
    if not external_dirs:
        return brief
    scope_raw = brief.get("workspace_scope")
    scope = [str(x) for x in scope_raw] if isinstance(scope_raw, list) else []
    seen = set(scope)
    for directory in external_dirs:
        if directory not in seen:
            seen.add(directory)
            scope.append(directory)
    brief["workspace_scope"] = scope
    return brief


def brief_for(
    *,
    run_id: str,
    graph: RunGraph,
    node: WaveNode,
    worktree: Worktree,
    prior_failures: list[str],
    repo_root: Path,
    runs_root: RunsRoot,
    role_dispatch_effective: bool,
    grep_brief: bool,
    wave_commit_shas: dict[str, str],
    pools: ProviderPoolRegistry | None,
    default_provider: str,
    last_checkpoint_sha: str,
    attempt: int = 1,
) -> dict[str, object]:
    """Build the JSON dispatch brief for *node*, including retry directives.

    Args:
        run_id (str): Run identifier.
        graph (RunGraph): Parsed execution graph.
        node (WaveNode): Wave node to dispatch.
        worktree (Worktree): Lane worktree handle.
        prior_failures (list[str]): Evidence from prior failed attempts.
        repo_root (Path): Main repository checkout.
        runs_root: Configured runs root (``RunsRoot``).
        role_dispatch_effective (bool): Whether role dispatch is active.
        grep_brief (bool): Whether to use grep-based graph pack enrichment.
        wave_commit_shas (dict[str, str]): Prior wave commit SHAs (orchestrator).
        pools (ProviderPoolRegistry | None): Provider pool registry.
        default_provider (str): Default adapter provider id.
        last_checkpoint_sha (str): Latest checkpoint SHA for the wave.
        attempt (int): Current attempt number (1-based).

    Returns:
        dict[str, object]: Rendered JSON dispatch brief.
    """
    plan_worktree_path = str(staged_wave_plan_path(worktree.path, node.plan_file, node.wave_id))
    brief = render_json_brief(
        node,
        run_id=run_id,
        branch=worktree.branch,
        worktree_path=str(worktree.path),
        plan_worktree_path=plan_worktree_path,
        model=node.model,
        orchestrator=graph.orchestrator,
        role_dispatch=role_dispatch_effective,
        outcome_contract=node.outcome_contract,
    )
    if node.reasoning_effort:
        brief["reasoning_effort"] = node.reasoning_effort
    if node.max_budget_usd is not None:
        brief["max_budget_usd"] = node.max_budget_usd
    if node.provider:
        brief["provider"] = node.provider
    brief = append_external_upload_dirs(brief, worktree.path)
    orch_cfg = graph.orchestrator
    if orch_cfg and orch_cfg.enabled and wave_commit_shas:
        brief["prior_wave_commits"] = dict(wave_commit_shas)
    if prior_failures:
        directives = brief["agent_directives"]
        if isinstance(directives, list):
            directives.append(
                "Prior attempt failures — correct these: " + " | ".join(prior_failures)
            )
            directives.append(
                f"Prior work is checkpointed on branch `{worktree.branch}`; "
                "continue from the current checkout — do not reset or delete "
                "unrelated files."
            )
            brief["agent_directives"] = directives
    elif attempt > 1:
        directives = brief["agent_directives"]
        if isinstance(directives, list):
            directives.append(
                f"Continue from checkpointed work on branch `{worktree.branch}`; "
                "do not reset or delete unrelated files."
            )
            brief["agent_directives"] = directives
    graph_db = runs_root.graph_db_path(run_id)
    if not graph_db.is_file():
        graph_db = repo_root / ".tripll" / "graph.db"
    at_sha = last_checkpoint_sha or "HEAD"
    targets = list(node.owned_paths)
    brief = enrich_brief_with_graph_pack(
        brief,
        wave_targets=targets,
        graph_store=str(graph_db),
        at_sha=at_sha,
        grep_brief=grep_brief,
        run_dir=worktree.path.parent.parent / "brief-spill",
    )
    brief = enrich_brief_with_rules_pack(
        brief,
        repo_root=repo_root,
        wave_targets=targets,
    )
    from tripll.plan.code_graph import kg_extra_available, routing_hints_for_wave

    if kg_extra_available() and graph_db.is_file():
        provider = node.provider or default_provider
        provider_cfg = pools.configs.get(provider) if pools else None
        brief["routing_hints"] = routing_hints_for_wave(
            targets=targets,
            graph_store=str(graph_db),
            provider=provider,
            provider_config=provider_cfg,
            repo=repo_root.name,
        )
    return brief
