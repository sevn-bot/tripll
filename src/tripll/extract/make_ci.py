"""Deterministic Makefile / CI extractor — MakeTarget, CIcheck, VERIFIES, RUNS."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from tripll.extract._common import evidence_at, make_edge, make_node, provenance
from tripll.ontology.types import validate_predicate_name

_EXTRACTOR = "tripll.extract.make_ci"

_TARGET = re.compile(r"^([a-zA-Z0-9_.-]+)\s*:", re.MULTILINE)
_CHECK = re.compile(r"^check\s*:\s*(.+)$", re.MULTILINE)


def extract_makefile(path: Path, *, repo: str, sha: str) -> dict[str, list[dict[str, Any]]]:
    """Extract MakeTarget and CIcheck nodes with VERIFIES/RUNS edges from a Makefile."""
    rel_path = path.as_posix()
    text = path.read_text(encoding="utf-8")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    targets: dict[str, str] = {}

    for match in _TARGET.finditer(text):
        name = match.group(1)
        if name.startswith("."):
            continue
        line = text[: match.start()].count("\n") + 1
        key = f"{repo}#make:{name}"
        nid = make_node(
            layer="code",
            kind="MakeTarget",
            natural_key=key,
            repo=repo,
            props={"name": name, "makefile": rel_path},
            sha=sha,
            **provenance(
                source=rel_path,
                evidence=evidence_at(path, line),
                extractor=_EXTRACTOR,
            ),
        )
        nodes.append(nid)
        targets[name] = nid["node_id"]

    check_match = _CHECK.search(text)
    if check_match:
        line = text[: check_match.start()].count("\n") + 1
        check_key = f"{repo}#check:ci"
        check_nid = make_node(
            layer="code",
            kind="CIcheck",
            natural_key=check_key,
            repo=repo,
            props={"name": "ci", "makefile": rel_path},
            sha=sha,
            **provenance(
                source=rel_path,
                evidence=evidence_at(path, line),
                extractor=_EXTRACTOR,
            ),
        )
        nodes.append(check_nid)
        deps = check_match.group(1).split()
        for dep in deps:
            dep_id = targets.get(dep)
            if dep_id is None:
                continue
            validate_predicate_name("RUNS")
            edges.append(
                make_edge(
                    predicate="RUNS",
                    src=check_nid["node_id"],
                    dst=dep_id,
                    sha=sha,
                    **provenance(
                        source=rel_path,
                        evidence=evidence_at(path, line),
                        extractor=_EXTRACTOR,
                    ),
                )
            )

    test_id = targets.get("test")
    lint_id = targets.get("lint")
    if test_id and lint_id:
        validate_predicate_name("VERIFIES")
        edges.append(
            make_edge(
                predicate="VERIFIES",
                src=lint_id,
                dst=test_id,
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, 1),
                    extractor=_EXTRACTOR,
                ),
            )
        )

    return {"nodes": nodes, "edges": edges}
