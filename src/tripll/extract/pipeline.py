"""Orchestrate deterministic extraction, fusion, and quality gate into GraphStore."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from tripll.extract.ast_python import extract_module
from tripll.extract.fuse import block_candidates, fuse_merge, should_merge
from tripll.extract.make_ci import extract_makefile
from tripll.extract.semantic import SemanticCandidate, extract_semantic_batch
from tripll.extract.specs_docs import extract_specs
from tripll.extract.tests_cov import extract_tests

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.graphstore import SqliteGraphStore

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _iter_spec_files(root: Path) -> list[Path]:
    specs: list[Path] = []
    for pattern in ("**/*.md", "**/specs/**/*.yaml"):
        for path in root.glob(pattern):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in {".md", ".yaml", ".yml"}:
                specs.append(path)
    return sorted(set(specs))


def extract_repo(
    store: SqliteGraphStore,
    repo_root: Path,
    *,
    repo: str,
    sha: str | None = None,
    run_semantic: bool = False,
    adapter: Any | None = None,
) -> dict[str, int]:
    """Run deterministic extractors; optionally batched semantic pass."""
    resolved_sha = sha or _git_sha(repo_root)
    store.close_valid_at_sha(resolved_sha)

    counts = {"nodes": 0, "edges": 0, "files": 0}
    all_nodes: list[dict[str, Any]] = []

    for path in _iter_python_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        counts["files"] += 1
        if rel.startswith(("test", "tests/")) or "/test" in rel:
            batch = extract_tests(path, repo=repo, sha=resolved_sha)
        else:
            batch = extract_module(path, repo=repo, sha=resolved_sha)
        store.upsert_nodes(batch["nodes"])
        store.upsert_edges(batch["edges"])
        all_nodes.extend(batch["nodes"])
        counts["nodes"] += len(batch["nodes"])
        counts["edges"] += len(batch["edges"])

    makefile = repo_root / "Makefile"
    if makefile.is_file():
        batch = extract_makefile(makefile, repo=repo, sha=resolved_sha)
        store.upsert_nodes(batch["nodes"])
        store.upsert_edges(batch["edges"])
        counts["nodes"] += len(batch["nodes"])
        counts["edges"] += len(batch["edges"])

    for spec_path in _iter_spec_files(repo_root):
        if "spec" not in spec_path.as_posix().lower() and spec_path.suffix != ".md":
            continue
        rel = spec_path.relative_to(repo_root).as_posix()
        if not any(tag in rel for tag in ("spec", "docs/", "about-")):
            continue
        batch = extract_specs(spec_path, repo=repo, sha=resolved_sha)
        store.upsert_nodes(batch["nodes"])
        store.upsert_edges(batch["edges"])
        counts["nodes"] += len(batch["nodes"])
        counts["edges"] += len(batch["edges"])

    if run_semantic:
        candidates = _semantic_candidates(all_nodes)
        sem = extract_semantic_batch(candidates, repo=repo, adapter=adapter)
        store.upsert_edges(sem.edges)
        counts["edges"] += len(sem.edges)
        counts["semantic_turns"] = sem.turn_count
        counts["semantic_seconds"] = int(sem.wall_seconds)

    return counts


def _semantic_candidates(nodes: list[dict[str, Any]]) -> list[SemanticCandidate]:
    symbols = [n for n in nodes if n.get("kind") == "Symbol"]
    requirements = [n for n in nodes if n.get("kind") == "Requirement"]
    candidates: list[SemanticCandidate] = []
    for sym in symbols[:50]:
        for req in requirements[:5]:
            candidates.append(
                SemanticCandidate(
                    predicate="IMPLEMENTS",
                    src_id=str(sym["node_id"]),
                    dst_id=str(req["node_id"]),
                    src_label=str(sym.get("natural_key", sym["node_id"])),
                    dst_label=str(req.get("natural_key", req["node_id"])),
                )
            )
    return candidates


def fuse_store(store: SqliteGraphStore) -> dict[str, int]:
    """Run blocking + structural merge on live Symbol nodes."""
    rows = store.conn.execute(
        """SELECT node_id, kind, natural_key, repo, props, source, confidence
           FROM nodes WHERE layer = 'code' AND kind = 'Symbol' AND valid_to IS NULL"""
    ).fetchall()
    nodes = [dict(r) for r in rows]
    neighbours: dict[str, dict[str, list[str]]] = {}
    for row in nodes:
        nid = str(row["node_id"])
        out_edges = store.neighbors(nid, predicates=["CALLS"], direction="out")
        in_edges = store.neighbors(nid, predicates=["CALLS"], direction="in")
        neighbours[nid] = {
            "callers": [e.src for e in in_edges],
            "callees": [e.dst for e in out_edges],
        }

    merged = 0
    ctx: dict[str, Any] = {"neighbours": neighbours}
    for id_a, id_b in block_candidates(nodes):
        ctx_pair = dict(ctx)
        if should_merge(id_a, id_b, context=ctx_pair):
            fuse_merge(id_a, id_b, reason="auto-fuse", store=store)
            merged += 1
    return {"candidates": len(block_candidates(nodes)), "merged": merged}


def query_store(
    store: SqliteGraphStore,
    *,
    seed: str,
    hops: int = 2,
    at_sha: str | None = None,
) -> dict[str, Any]:
    sg = store.subgraph([seed], hops=hops, at_sha=at_sha)
    return {
        "nodes": [n.node_id for n in sg.nodes],
        "edges": [(e.predicate, e.src, e.dst) for e in sg.edges],
    }
