"""Deterministic test coverage extractor — Test nodes and COVERS edges."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from tripll.extract._common import evidence_at, make_edge, make_node, provenance
from tripll.ontology.types import validate_predicate_name

_EXTRACTOR = "tripll.extract.tests_cov"


def _test_key(repo: str, rel_path: str, testname: str) -> str:
    return f"{repo}#{rel_path}::{testname}"


def _symbol_key(repo: str, module_path: str, qualname: str) -> str:
    return f"{repo}#{module_path}::{qualname}"


def _module_path_from_import(name: str, *, test_path: str) -> str:
    if name.endswith(".py"):
        return name
    parts = test_path.split("/")
    if len(parts) > 1:
        return f"{'/'.join(parts[:-1])}/{name}.py"
    return f"{name}.py"


def extract_tests(path: Path, *, repo: str, sha: str) -> dict[str, list[dict[str, Any]]]:
    """Extract Test nodes and COVERS edges from a Python test module."""
    rel_path = path.as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    imported_symbols: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                module_file = _module_path_from_import(mod or alias.name, test_path=rel_path)
                imported_symbols[local] = module_file
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imported_symbols[local] = _module_path_from_import(local, test_path=rel_path)

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        test_key = _test_key(repo, rel_path, node.name)
        test_nid = make_node(
            layer="code",
            kind="Test",
            natural_key=test_key,
            repo=repo,
            props={"testname": node.name, "path": rel_path},
            sha=sha,
            **provenance(
                source=rel_path,
                evidence=evidence_at(path, node.lineno),
                extractor=_EXTRACTOR,
            ),
        )
        nodes.append(test_nid)

        covered: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                covered.add(sub.func.id)
            elif isinstance(sub, ast.Name) and sub.id in imported_symbols:
                covered.add(sub.id)

        for sym in sorted(covered):
            mod_path = imported_symbols.get(sym, rel_path)
            sym_key = _symbol_key(repo, mod_path, sym)
            sym_id = make_node(
                layer="code",
                kind="Symbol",
                natural_key=sym_key,
                repo=repo,
                props={"qualname": sym, "path": mod_path},
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, node.lineno),
                    extractor=_EXTRACTOR,
                ),
            )
            nodes.append(sym_id)
            validate_predicate_name("COVERS")
            edges.append(
                make_edge(
                    predicate="COVERS",
                    src=test_nid["node_id"],
                    dst=sym_id["node_id"],
                    sha=sha,
                    **provenance(
                        source=rel_path,
                        evidence=evidence_at(path, node.lineno),
                        extractor=_EXTRACTOR,
                    ),
                )
            )

    return {"nodes": nodes, "edges": edges}
