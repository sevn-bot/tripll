"""Deterministic spec/requirement extractor from markdown docs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from tripll.extract._common import evidence_at, make_edge, make_node, provenance
from tripll.ontology.types import validate_predicate_name

_EXTRACTOR = "tripll.extract.specs_docs"

_FR_ID = re.compile(r"^(FR-\d+|NFR-\d+)\s*[:\-]", re.MULTILINE)
_OWNS = re.compile(r"owns?\s*:\s*`([^`]+)`", re.IGNORECASE)


def extract_specs(path: Path, *, repo: str, sha: str) -> dict[str, list[dict[str, Any]]]:
    """Extract Spec, Requirement nodes and SPECIFIES/OWNS edges from a markdown spec."""
    rel_path = path.as_posix()
    text = path.read_text(encoding="utf-8")
    spec_key = f"{repo}#{rel_path}"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    spec_nid = make_node(
        layer="code",
        kind="Spec",
        natural_key=spec_key,
        repo=repo,
        props={"path": rel_path},
        sha=sha,
        **provenance(
            source=rel_path,
            evidence=evidence_at(path, 1),
            extractor=_EXTRACTOR,
        ),
    )
    nodes.append(spec_nid)

    for match in _FR_ID.finditer(text):
        fr_id = match.group(1)
        line = text[: match.start()].count("\n") + 1
        req_key = f"{repo}#{rel_path}::{fr_id}"
        req_nid = make_node(
            layer="code",
            kind="Requirement",
            natural_key=req_key,
            repo=repo,
            props={"fr_id": fr_id, "spec": rel_path},
            sha=sha,
            **provenance(
                source=rel_path,
                evidence=evidence_at(path, line),
                extractor=_EXTRACTOR,
            ),
        )
        nodes.append(req_nid)
        validate_predicate_name("SPECIFIES")
        edges.append(
            make_edge(
                predicate="SPECIFIES",
                src=spec_nid["node_id"],
                dst=req_nid["node_id"],
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, line),
                    extractor=_EXTRACTOR,
                ),
            )
        )

    for match in _OWNS.finditer(text):
        module_path = match.group(1)
        line = text[: match.start()].count("\n") + 1
        mod_key = f"{repo}#{module_path}"
        mod_nid = make_node(
            layer="code",
            kind="Module",
            natural_key=mod_key,
            repo=repo,
            props={"path": module_path},
            sha=sha,
            **provenance(
                source=rel_path,
                evidence=evidence_at(path, line),
                extractor=_EXTRACTOR,
            ),
        )
        nodes.append(mod_nid)
        validate_predicate_name("OWNS")
        edges.append(
            make_edge(
                predicate="OWNS",
                src=spec_nid["node_id"],
                dst=mod_nid["node_id"],
                sha=sha,
                **provenance(
                    source=rel_path,
                    evidence=evidence_at(path, line),
                    extractor=_EXTRACTOR,
                ),
            )
        )

    return {"nodes": nodes, "edges": edges}
