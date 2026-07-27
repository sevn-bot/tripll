"""Brownfield onboarding — ``tripll init`` for existing repositories (W14).

Exports:
    BrownfieldResult — init run summary.
    run_brownfield_init — detect layout, emit docs, evaluate, init runs root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from tripll.config import TripllConfig, load_config
from tripll.extract.pipeline import extract_repo
from tripll.graphstore import SqliteGraphStore
from tripll.onboard.detect import RepoLayout, detect_repo_layout
from tripll.onboard.doctor import build_doctor_report
from tripll.onboard.emitters import EmitResult, emit_doc_skeletons, emit_tripll_toml
from tripll.onboard.evaluate import write_evaluation
from tripll.pipeline import RunsRoot
from tripll.repo_root import resolve_repo_root

__all__ = ["BrownfieldResult", "run_brownfield_init"]


@dataclass
class BrownfieldResult:
    """Outcome of a brownfield ``tripll init`` run.

    Args:
        repo_root (Path): Target repository root.
        layout (RepoLayout): Detected layout metadata.
        config (TripllConfig): Loaded configuration after init.
        runs_root (Path): Initialised runs directory.
        tripll_toml (EmitResult): ``tripll.toml`` write outcome.
        docs (EmitResult): Spec/PRD/plan emission outcomes.
        evaluation_path (Path | None): Written evaluation markdown path.
        graph_counts (dict[str, int]): Graph extract counts.
        messages (list[str]): Operator-facing status lines.
    """

    repo_root: Path
    layout: RepoLayout
    config: TripllConfig
    runs_root: Path
    tripll_toml: EmitResult = field(default_factory=EmitResult)
    docs: EmitResult = field(default_factory=EmitResult)
    evaluation_path: Path | None = None
    graph_counts: dict[str, int] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)


def _refresh_code_graph(repo_root: Path, *, repo_name: str) -> dict[str, int]:
    db_path = repo_root / ".tripll" / "graph.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteGraphStore(str(db_path))
    try:
        return extract_repo(store, repo_root, repo=repo_name, run_semantic=False)
    finally:
        store.close()


def run_brownfield_init(
    *,
    repo_root: Path | None = None,
    runs_root: Path | None = None,
    force: bool = False,
) -> BrownfieldResult:
    """Onboard an existing repository: config, docs, graph, evaluation, runs layout.

    Preserves the historical runs-root initialisation as a subset of ``init``.
    Re-running reconciles gaps without clobbering operator-edited files unless
    ``force`` is set.

    Args:
        repo_root (Path | None): Repository root (resolved from CWD when omitted).
        runs_root (Path | None): Runs root directory (default ``<repo>/runs``).
        force (bool): Overwrite existing onboarding artefacts when True.

    Returns:
        BrownfieldResult: Structured init summary for CLI reporting.

    Examples:
        >>> isinstance(run_brownfield_init, object)
        True
    """
    root = (repo_root or resolve_repo_root()).resolve()
    layout = detect_repo_layout(root)
    cfg = load_config(repo_root=root)

    env_runs = os.environ.get("TRIPLL_RUNS")
    resolved_runs = (
        Path(runs_root).resolve()
        if runs_root is not None
        else Path(env_runs).resolve()
        if env_runs
        else (root / "runs").resolve()
    )
    RunsRoot(resolved_runs).init()

    toml_result = emit_tripll_toml(root, layout, cfg.repo, force=force)
    docs_result = emit_doc_skeletons(root, cfg.repo, layout, force=force)

    graph_counts = _refresh_code_graph(root, repo_name=layout.repo_name)
    doctor = build_doctor_report()
    evaluation_path = write_evaluation(
        root,
        layout=layout,
        doctor=doctor,
        graph_counts=graph_counts,
        specs_dir=root / cfg.repo.specs_dir,
        prds_dir=root / cfg.repo.prds_dir,
        force=force,
    )

    cfg = load_config(repo_root=root)
    messages = [
        f"Repo root   : {root}",
        f"Runs root   : {resolved_runs}",
        f"Language    : {layout.language}",
        f"Test runner : {layout.test_runner or 'unknown'}",
        f"CI          : {layout.ci or 'none detected'}",
        f"Graph nodes : {graph_counts.get('nodes', 0)}",
        f"Evaluation  : {evaluation_path}",
    ]
    messages.extend(docs_result.drift)
    messages.extend(toml_result.drift)

    return BrownfieldResult(
        repo_root=root,
        layout=layout,
        config=cfg,
        runs_root=resolved_runs,
        tripll_toml=toml_result,
        docs=docs_result,
        evaluation_path=evaluation_path,
        graph_counts=graph_counts,
        messages=messages,
    )
