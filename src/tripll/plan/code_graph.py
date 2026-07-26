"""Code-graph helpers — stop-rule analysis, run refresh, routing hints (P2).

Exports:
    kg_extra_available — True when the optional ``kg`` extra (networkx) is installed.
    default_graph_db_path — canonical ``.tripll/graph.db`` under a repo root.
    refresh_code_graph — extract/refresh the target-repo KG into SQLite.
    analyze_parallel_calls — build the ``code_graph`` dict for :func:`check_stop_rule`.
    routing_hints_for_wave — advisory module count and CALLS fan-out for briefs.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.adapters.pools import ProviderConfig
    from tripll.graphstore import GraphStore

_CALLS_PATH_INFINITY = 99


def kg_extra_available() -> bool:
    """Return True when ``networkx`` is importable (``kg`` extra installed).

    Returns:
        bool: Whether graph activation features should run.

    Examples:
        >>> isinstance(kg_extra_available(), bool)
        True
    """
    return importlib.util.find_spec("networkx") is not None


def default_graph_db_path(repo_root: Path) -> Path:
    """Return ``<repo_root>/.tripll/graph.db``.

    Args:
        repo_root (Path): Target repository checkout.

    Returns:
        Path: GraphStore SQLite path.
    """
    return repo_root / ".tripll" / "graph.db"


def _store_from_arg(graph_store: GraphStore | str) -> GraphStore:
    from tripll.graphstore import SqliteGraphStore

    if isinstance(graph_store, str):
        return SqliteGraphStore(graph_store)
    return graph_store


def _module_id_candidates(target: str, *, repo: str) -> list[str]:
    path = str(target).strip().rstrip("/")
    if not path:
        return []
    return [
        f"code:Module:{path}",
        f"code:Module:{repo}#{path}",
    ]


def _resolve_module_id(store: GraphStore, target: str, *, repo: str) -> str | None:
    for candidate in _module_id_candidates(target, repo=repo):
        if store.get(candidate) is not None:
            return candidate
    return None


def _symbols_for_module(store: GraphStore, module_id: str) -> list[str]:
    return [
        edge.dst for edge in store.neighbors(module_id, predicates=["DECLARES"], direction="out")
    ]


def _min_calls_path(
    store: GraphStore,
    src_module: str,
    dst_module: str,
    *,
    max_depth: int = 1,
) -> int:
    if src_module == dst_module:
        return 0
    src_symbols = _symbols_for_module(store, src_module)
    dst_symbols = _symbols_for_module(store, dst_module)
    if not src_symbols or not dst_symbols:
        return _CALLS_PATH_INFINITY
    best = _CALLS_PATH_INFINITY
    for src in src_symbols:
        for dst in dst_symbols:
            for result in store.paths(src, dst, max_depth=max_depth, predicates=["CALLS"]):
                best = min(best, result.depth)
            for result in store.paths(dst, src, max_depth=max_depth, predicates=["CALLS"]):
                best = min(best, result.depth)
    return best


def _wave_targets(wave: dict[str, Any]) -> list[str]:
    targets = wave.get("targets") or []
    return [str(t) for t in targets if str(t).strip()]


def _parallel_groups(waves: list[dict[str, Any]]) -> list[set[str]]:
    from tripll.plan.shape_checks import _parallel_groups as shape_parallel_groups

    return shape_parallel_groups(waves)


def analyze_parallel_calls(
    waves: list[dict[str, Any]],
    *,
    graph_store: GraphStore | str,
    repo: str = "tripll",
) -> dict[str, Any] | None:
    """Derive the ``code_graph`` payload for :func:`~tripll.plan.shape_checks.check_stop_rule`.

    Args:
        waves (list[dict[str, Any]]): Cleaned plan waves.
        graph_store (GraphStore | str): SQLite path or store handle.
        repo (str): Repository slug used during extraction.

    Returns:
        dict[str, Any] | None: ``parallel`` + ``calls_path_len`` when the kg extra is installed;
        ``None`` when graph activation is unavailable.
    """
    if not kg_extra_available():
        return None
    store = _store_from_arg(graph_store)
    wave_by_id = {str(w.get("id", "")): w for w in waves if w.get("id")}
    best_len = _CALLS_PATH_INFINITY
    saw_parallel = False
    for group in _parallel_groups(waves):
        if len(group) < 2:
            continue
        saw_parallel = True
        group_waves = [wave_by_id[wid] for wid in group if wid in wave_by_id]
        for i, left in enumerate(group_waves):
            left_targets = _wave_targets(left)
            left_modules = [
                mid
                for t in left_targets
                if (mid := _resolve_module_id(store, t, repo=repo)) is not None
            ]
            for right in group_waves[i + 1 :]:
                right_targets = _wave_targets(right)
                right_modules = [
                    mid
                    for t in right_targets
                    if (mid := _resolve_module_id(store, t, repo=repo)) is not None
                ]
                for src_mod in left_modules:
                    for dst_mod in right_modules:
                        best_len = min(best_len, _min_calls_path(store, src_mod, dst_mod))
    if not saw_parallel:
        return {"parallel": False, "calls_path_len": _CALLS_PATH_INFINITY}
    return {"parallel": True, "calls_path_len": best_len}


def refresh_code_graph(
    db_path: Path | str,
    repo_root: Path,
    *,
    repo: str | None = None,
) -> bool:
    """Build or refresh the code graph for *repo_root* when the kg extra is present.

    Args:
        db_path (Path | str): Destination GraphStore SQLite path.
        repo_root (Path): Target repository checkout to extract.
        repo (str | None): Repository slug (defaults to *repo_root* name).

    Returns:
        bool: ``True`` when extraction ran; ``False`` when skipped (kg extra absent).
    """
    if not kg_extra_available():
        return False
    from tripll.extract.pipeline import extract_repo
    from tripll.graphstore import SqliteGraphStore

    slug = repo or repo_root.name
    store = SqliteGraphStore(str(db_path))
    try:
        extract_repo(store, repo_root, repo=slug, sha=None, run_semantic=False)
    finally:
        store.close()
    return True


def _calls_fanout(store: GraphStore, module_id: str) -> int:
    symbols = _symbols_for_module(store, module_id)
    if not symbols:
        return 0
    callees: set[str] = set()
    for sym in symbols:
        for edge in store.neighbors(sym, predicates=["CALLS"], direction="out"):
            callees.add(edge.dst)
    return len(callees)


def routing_hints_for_wave(
    *,
    targets: list[str],
    graph_store: GraphStore | str,
    provider: str | None = None,
    provider_config: ProviderConfig | None = None,
    repo: str = "tripll",
) -> dict[str, Any]:
    """Return advisory routing metadata for a wave brief (R16 — no auto-selection).

    Args:
        targets (list[str]): Wave owned paths / targets.
        graph_store (GraphStore | str): GraphStore path or handle.
        provider (str | None): Declared provider id from the wave row.
        provider_config (ProviderConfig | None): Parsed ``[providers.*]`` entry for *provider*.
        repo (str): Repository slug used during extraction.

    Returns:
        dict[str, Any]: ``module_count``, ``calls_fanout``, and provider context.
    """
    store = _store_from_arg(graph_store)
    module_ids = [
        mid
        for target in targets
        if (mid := _resolve_module_id(store, target, repo=repo)) is not None
    ]
    fanouts = [_calls_fanout(store, module_id) for module_id in module_ids]
    hints: dict[str, Any] = {
        "module_count": len([t for t in targets if str(t).strip()]),
        "calls_fanout": max(fanouts) if fanouts else 0,
        "advisory": True,
    }
    if provider:
        hints["provider"] = provider
    if provider_config is not None:
        hints["provider_max_parallel"] = provider_config.max_parallel
        if provider_config.default_model:
            hints["provider_default_model"] = provider_config.default_model
    return hints
