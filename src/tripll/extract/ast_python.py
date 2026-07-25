"""Deterministic Python AST extractor — Module/Symbol, DECLARES/IMPORTS/CALLS."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from tripll.extract._common import evidence_at, make_edge, make_node, provenance
from tripll.ontology.types import validate_predicate_name

_EXTRACTOR = "tripll.extract.ast_python"


def _module_key(repo: str, rel_path: str) -> str:
    return f"{repo}#{rel_path}"


def _symbol_key(repo: str, rel_path: str, qualname: str) -> str:
    return f"{repo}#{rel_path}::{qualname}"


def _resolve_call_name(node: ast.AST, *, local_names: set[str]) -> str | None:
    if isinstance(node, ast.Name):
        return node.id if node.id in local_names else None
    if isinstance(node, ast.Attribute):
        base = _resolve_call_name(node.value, local_names=local_names)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None


def _imported_module(node: ast.stmt) -> tuple[str, int] | None:
    if isinstance(node, ast.Import):
        if node.names:
            return node.names[0].name, node.lineno
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            return node.module, node.lineno
        if node.level:
            return "." * node.level, node.lineno
    return None


def extract_module(path: Path, *, repo: str, sha: str) -> dict[str, list[dict[str, Any]]]:
    """Extract code-layer nodes and edges from a Python module."""
    rel_path = path.as_posix()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    mod_key = _module_key(repo, rel_path)
    mod_id = make_node(
        layer="code",
        kind="Module",
        natural_key=mod_key,
        repo=repo,
        props={"path": rel_path},
        sha=sha,
        **provenance(
            source=rel_path,
            evidence=evidence_at(path, 1),
            extractor=_EXTRACTOR,
        ),
    )
    nodes.append(mod_id)
    mod_nid = mod_id["node_id"]

    local_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_names.add(node.name)

    for node in tree.body:
        imported = _imported_module(node)
        if imported is not None:
            imp_name, lineno = imported
            validate_predicate_name("IMPORTS")
            imp_key = _module_key(repo, imp_name.replace(".", "/") + ".py")
            imp_nid = make_node(
                layer="code",
                kind="Module",
                natural_key=imp_key,
                repo=repo,
                props={"path": imp_name},
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, lineno),
                    extractor=_EXTRACTOR,
                ),
            )
            nodes.append(imp_nid)
            edges.append(
                make_edge(
                    predicate="IMPORTS",
                    src=mod_nid,
                    dst=imp_nid["node_id"],
                    sha=sha,
                    **provenance(
                        source=rel_path,
                        evidence=evidence_at(path, lineno),
                        extractor=_EXTRACTOR,
                    ),
                )
            )

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        sym_key = _symbol_key(repo, rel_path, node.name)
        sym_nid = make_node(
            layer="code",
            kind="Symbol",
            natural_key=sym_key,
            repo=repo,
            props={"qualname": node.name, "path": rel_path},
            sha=sha,
            **provenance(
                source=rel_path,
                evidence=evidence_at(path, node.lineno),
                extractor=_EXTRACTOR,
            ),
        )
        nodes.append(sym_nid)
        validate_predicate_name("DECLARES")
        edges.append(
            make_edge(
                predicate="DECLARES",
                src=mod_nid,
                dst=sym_nid["node_id"],
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, node.lineno),
                    extractor=_EXTRACTOR,
                ),
            )
        )

        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            callee = _resolve_call_name(sub.func, local_names=local_names)
            if callee is None or callee not in local_names:
                continue
            dst_key = _symbol_key(repo, rel_path, callee.split(".")[0])
            dst_id = make_node(
                layer="code",
                kind="Symbol",
                natural_key=dst_key,
                repo=repo,
                props={"qualname": callee.split(".")[0], "path": rel_path},
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, sub.lineno),
                    extractor=_EXTRACTOR,
                ),
            )
            nodes.append(dst_id)
            validate_predicate_name("CALLS")
            edges.append(
                make_edge(
                    predicate="CALLS",
                    src=sym_nid["node_id"],
                    dst=dst_id["node_id"],
                    sha=sha,
                    **provenance(
                        source=rel_path,
                        evidence=evidence_at(path, sub.lineno),
                        extractor=_EXTRACTOR,
                    ),
                )
            )

    return {"nodes": nodes, "edges": edges}
