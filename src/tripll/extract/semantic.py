"""Batched semantic extraction — IMPLEMENTS and ABOUT via CLI adapters (P6)."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from tripll.extract._common import make_edge, make_node, provenance, utc_now
from tripll.ontology.types import validate_predicate_name

if TYPE_CHECKING:
    from tripll.adapters.base import DispatchResult

_EXTRACTOR = "tripll.extract.semantic"
SEMANTIC_PREDICATES = frozenset({"IMPLEMENTS", "ABOUT"})
DEFAULT_BATCH_SIZE = int(os.environ.get("TRIPLL_SEMANTIC_BATCH_SIZE", "20"))


@dataclass
class SemanticCandidate:
    predicate: Literal["IMPLEMENTS", "ABOUT"]
    src_id: str
    dst_id: str
    src_label: str
    dst_label: str
    context: str = ""


@dataclass
class SemanticBatchResult:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    wall_seconds: float = 0.0


def _build_prompt(candidates: list[SemanticCandidate]) -> str:
    payload = [
        {
            "predicate": c.predicate,
            "src": c.src_label,
            "dst": c.dst_label,
            "context": c.context,
        }
        for c in candidates
    ]
    return (
        "Return a JSON array of semantic assertions. Each item must include "
        "predicate, src, dst, confidence (0-1), and evidence (a short quote).\n"
        f"Candidates:\n{json.dumps(payload, indent=2)}"
    )


def _parse_response(text: str, candidates: list[SemanticCandidate]) -> list[dict[str, Any]]:
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    by_key: dict[tuple[str, str, str], SemanticCandidate] = {
        (c.src_label, c.dst_label, c.predicate): c for c in candidates
    }
    edges: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pred = str(item.get("predicate", "")).upper()
        if pred not in SEMANTIC_PREDICATES:
            continue
        validate_predicate_name(pred)
        key = (str(item.get("src", "")), str(item.get("dst", "")), pred)
        cand = by_key.get(key)
        if cand is None:
            continue
        conf = float(item.get("confidence", 0.8))
        evidence = str(item.get("evidence", cand.context or "semantic"))
        edges.append(
            make_edge(
                predicate=pred,
                src=cand.src_id,
                dst=cand.dst_id,
                sha=None,
                **provenance(
                    source="semantic",
                    evidence=evidence,
                    extractor=_EXTRACTOR,
                    confidence=conf,
                ),
            )
        )
    return edges


def extract_semantic_batch(
    candidates: list[SemanticCandidate],
    *,
    repo: str,
    adapter: Any | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> SemanticBatchResult:
    """Run one or more batched CLI turns for semantic predicates."""
    import time

    if not candidates:
        return SemanticBatchResult()

    result = SemanticBatchResult()
    start = time.monotonic()
    batches = [candidates[i : i + batch_size] for i in range(0, len(candidates), batch_size)]

    for batch in batches:
        prompt = _build_prompt(batch)
        response_text = _run_adapter(prompt, adapter=adapter)
        result.turn_count += 1
        result.edges.extend(_parse_response(response_text, batch))

    result.wall_seconds = time.monotonic() - start
    return result


def _run_adapter(prompt: str, *, adapter: Any | None) -> str:
    """Dispatch a single batched turn via CLI adapter or offline stub."""
    stub = os.environ.get("TRIPLL_SEMANTIC_STUB")
    if stub:
        return stub
    if adapter is None:
        return "[]"
    import asyncio
    from pathlib import Path
    from typing import cast

    log_path = Path(os.environ.get("TRIPLL_SEMANTIC_LOG", "/tmp/tripll-semantic.log"))

    async def _dispatch() -> DispatchResult:
        raw = await adapter.dispatch(
            prompt=prompt,
            log_path=log_path,
            timeout_seconds=int(os.environ.get("TRIPLL_SEMANTIC_TIMEOUT", "300")),
        )
        return cast("DispatchResult", raw)

    outcome = asyncio.run(_dispatch())
    text = outcome.result_text
    if text:
        return text
    if log_path.is_file():
        return log_path.read_text(encoding="utf-8", errors="replace")
    return "[]"


def record_candidate_relation(
    store: Any,
    *,
    predicate: str,
    src_kind: str,
    dst_kind: str,
    evidence: str,
    count: int = 1,
) -> None:
    """Accumulate an unmodelled relation in the candidate_relations side table."""
    if hasattr(store, "record_candidate_relation"):
        store.record_candidate_relation(
            predicate=predicate,
            src_kind=src_kind,
            dst_kind=dst_kind,
            evidence=evidence,
            count=count,
        )


def make_verdict_node(
    *,
    run_id: str,
    predicate: str,
    precision: float,
    passed: bool,
    sample_size: int,
) -> dict[str, Any]:
    verdict_id = str(uuid.uuid4())
    return make_node(
        layer="finding",
        kind="Verdict",
        natural_key=f"{run_id}#{verdict_id}",
        repo=None,
        props={
            "predicate": predicate,
            "precision": precision,
            "passed": passed,
            "sample_size": sample_size,
        },
        **provenance(
            source="quality_gate",
            evidence=f"sample={sample_size},precision={precision}",
            extractor="tripll.extract.quality_gate",
            confidence=precision,
            extracted_at=utc_now(),
        ),
    )
