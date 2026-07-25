"""Quality gate for semantic extractors — precision threshold with Verdict nodes."""

from __future__ import annotations

from typing import Any

from tripll.extract.semantic import SEMANTIC_PREDICATES, make_verdict_node

PRECISION_THRESHOLD = 0.90
DEFAULT_SAMPLE_SIZE = 50


def applies_to(predicate: str) -> bool:
    """Return True when the gate applies to this predicate (semantic extractors only)."""
    return predicate.upper() in SEMANTIC_PREDICATES


def run_quality_gate(
    *,
    predicate: str,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    precision: float,
    run_id: str = "local",
    store: Any | None = None,
) -> dict[str, Any]:
    """Score a semantic extractor sample; failure prescribes prompt/rule fix, never graph patch."""
    if not applies_to(predicate):
        return {
            "passed": True,
            "precision": precision,
            "sample_size": sample_size,
            "remedy": "gate does not apply to deterministic extractors",
            "skipped": True,
        }

    passed = precision >= PRECISION_THRESHOLD
    remedy = ""
    if not passed:
        remedy = (
            f"Precision {precision:.2f} below {PRECISION_THRESHOLD} on {sample_size} items — "
            "fix the semantic extractor prompt or matching rules, then re-run extraction. "
            "Never patch the graph to pass the gate."
        )

    verdict = {
        "passed": passed,
        "precision": precision,
        "sample_size": sample_size,
        "predicate": predicate,
        "remedy": remedy,
        "threshold": PRECISION_THRESHOLD,
    }

    if store is not None and hasattr(store, "upsert_nodes"):
        node = make_verdict_node(
            run_id=run_id,
            predicate=predicate,
            precision=precision,
            passed=passed,
            sample_size=sample_size,
        )
        store.upsert_nodes([node])
        verdict["verdict_node_id"] = node["node_id"]

    return verdict
