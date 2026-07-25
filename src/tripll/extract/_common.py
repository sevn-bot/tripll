"""Shared helpers for graph extractors — provenance and id builders."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

EXTRACTOR_VERSION = "0.1.0"


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def evidence_at(path: Path, line: int) -> str:
    return f"{path.as_posix()}:{line}"


def node_id(layer: str, kind: str, natural_key: str) -> str:
    return f"{layer}:{kind}:{natural_key}"


def edge_id(predicate: str, src: str, dst: str) -> str:
    digest = hashlib.sha256(f"{predicate}:{src}:{dst}".encode()).hexdigest()[:16]
    return f"{predicate.lower()}:{digest}"


def provenance(
    *,
    source: str,
    evidence: str,
    extractor: str,
    confidence: float = 1.0,
    extracted_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "evidence": evidence,
        "extractor": extractor,
        "extractor_version": EXTRACTOR_VERSION,
        "confidence": confidence,
        "extracted_at": extracted_at or utc_now(),
    }


def make_node(
    *,
    layer: str,
    kind: str,
    natural_key: str,
    repo: str | None,
    props: dict[str, Any] | None = None,
    sha: str | None = None,
    **prov: Any,
) -> dict[str, Any]:
    return {
        "node_id": node_id(layer, kind, natural_key),
        "layer": layer,
        "kind": kind,
        "natural_key": natural_key,
        "repo": repo,
        "props": json.dumps(props or {}),
        "valid_from_sha": sha,
        **prov,
    }


def make_edge(
    *,
    predicate: str,
    src: str,
    dst: str,
    props: dict[str, Any] | None = None,
    sha: str | None = None,
    **prov: Any,
) -> dict[str, Any]:
    return {
        "edge_id": edge_id(predicate, src, dst),
        "predicate": predicate,
        "src": src,
        "dst": dst,
        "props": json.dumps(props or {}),
        "valid_from_sha": sha,
        **prov,
    }
