"""Parse and normalize mergeCraft ``diff-review --json`` Finding payloads.

Exports:
    MERGECRAFT_FINDING_REQUIRED_KEYS — required keys on each mergeCraft Finding.
    MergecraftFindingsPayloadError — invalid JSON envelope or finding shape.
    load_mergecraft_findings_json — read ``{"findings": [...]}`` from disk.
    normalize_mergecraft_finding — map one mergeCraft Finding to tripll schema.
    normalize_mergecraft_findings — batch normalize with dedup.
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — CLI paths at runtime
from typing import Any

from tripll.github.findings import _EXTRACTOR_VERSION, _finding_id, _normalize_message, _now

_EXTRACTOR_JSON = "tripll.review.findings_json"

MERGECRAFT_FINDING_REQUIRED_KEYS = frozenset(
    {
        "tool",
        "rule_id",
        "category",
        "severity",
        "confidence",
        "message",
        "path",
        "start_line",
        "end_line",
        "fingerprint",
        "evidence",
        "remediation",
        "autofix",
        "introduced_by_pr",
        "source",
        "cluster_id",
    }
)

_MERGECRAFT_SEVERITY_MAP = {
    "critical": "critical",
    "major": "high",
    "minor": "medium",
    "trivial": "low",
}

_MERGECRAFT_CONFIDENCE_MAP = {
    "certain": 1.0,
    "likely": 0.75,
    "possible": 0.5,
}


class MergecraftFindingsPayloadError(ValueError):
    """Raised when mergeCraft structured findings JSON is invalid."""


def _mergecraft_rule_id(raw: dict[str, Any]) -> str:
    tool = str(raw.get("tool") or "review").strip().lower()
    rule = str(raw.get("rule_id") or "").strip()
    if tool in {"agent", "review"}:
        return "mergecraft:review"
    if rule:
        return f"mergecraft:{tool}:{rule}"
    return f"mergecraft:{tool}"


def _mergecraft_severity(raw: dict[str, Any]) -> str:
    sev = str(raw.get("severity") or "Minor").strip().lower()
    return _MERGECRAFT_SEVERITY_MAP.get(sev, "medium")


def _mergecraft_confidence(raw: dict[str, Any]) -> float:
    conf = str(raw.get("confidence") or "likely").strip().lower()
    return _MERGECRAFT_CONFIDENCE_MAP.get(conf, 0.75)


def _validate_mergecraft_finding(raw: object, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        msg = f"findings[{index}] must be an object, got {type(raw).__name__}"
        raise MergecraftFindingsPayloadError(msg)
    missing = sorted(MERGECRAFT_FINDING_REQUIRED_KEYS - raw.keys())
    if missing:
        msg = f"findings[{index}] missing required keys: {', '.join(missing)}"
        raise MergecraftFindingsPayloadError(msg)
    return raw


def load_mergecraft_findings_json(path: Path) -> list[dict[str, Any]]:
    """Load mergeCraft structured findings from a ``diff-review --json`` file.

    Args:
        path (Path): JSON file containing ``{"findings": [...]}``.

    Returns:
        list[dict[str, Any]]: Raw mergeCraft Finding dicts (validated shape).

    Raises:
        MergecraftFindingsPayloadError: Invalid envelope or finding records.
        OSError: File cannot be read.

    Examples:
        >>> import json, tempfile
        >>> from pathlib import Path
        >>> payload = {"findings": []}
        >>> with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        ...     json.dump(payload, fh)
        ...     p = Path(fh.name)
        >>> load_mergecraft_findings_json(p)
        []
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"{path}: invalid JSON: {exc}"
        raise MergecraftFindingsPayloadError(msg) from exc
    if not isinstance(data, dict):
        msg = f"{path}: expected object envelope, got {type(data).__name__}"
        raise MergecraftFindingsPayloadError(msg)
    findings_raw = data.get("findings")
    if findings_raw is None:
        msg = f"{path}: missing required key 'findings'"
        raise MergecraftFindingsPayloadError(msg)
    if not isinstance(findings_raw, list):
        msg = f"{path}: 'findings' must be an array, got {type(findings_raw).__name__}"
        raise MergecraftFindingsPayloadError(msg)
    return [_validate_mergecraft_finding(item, index=i) for i, item in enumerate(findings_raw)]


def normalize_mergecraft_finding(
    raw: dict[str, Any],
    *,
    run_id: str = "local",
    head_sha: str = "",
) -> dict[str, Any]:
    """Map one mergeCraft Finding into tripll's normalized Finding schema.

    Args:
        raw (dict[str, Any]): Validated mergeCraft Finding record.
        run_id (str): Run id stamped on the normalized finding.
        head_sha (str): Optional git head SHA for staleness tracking.

    Returns:
        dict[str, Any]: tripll Finding dict compatible with graph ingestion.

    Examples:
        >>> sample = {
        ...     "tool": "agent",
        ...     "rule_id": "MC-001",
        ...     "category": "Functional Correctness",
        ...     "severity": "Major",
        ...     "confidence": "likely",
        ...     "message": "Possible null deref",
        ...     "path": "src/demo.py",
        ...     "start_line": 10,
        ...     "end_line": 12,
        ...     "fingerprint": "abc123",
        ...     "evidence": ["hunk context"],
        ...     "remediation": "Add guard",
        ...     "autofix": None,
        ...     "introduced_by_pr": "true",
        ...     "source": "agent",
        ...     "cluster_id": None,
        ... }
        >>> out = normalize_mergecraft_finding(sample)
        >>> out["rule_id"]
        'mergecraft:review'
        >>> out["line_range"]
        [10, 12]
    """
    path = str(raw.get("path") or "")
    message = str(raw.get("message") or "")
    message_norm = _normalize_message(message)
    rule_id = _mergecraft_rule_id(raw)
    dedup = (rule_id, path, str(raw.get("fingerprint") or ""), message_norm)
    evidence_items = raw.get("evidence")
    evidence_text = (
        "\n".join(str(item) for item in evidence_items)
        if isinstance(evidence_items, list)
        else str(evidence_items or "")
    )
    start = int(raw.get("start_line") or 1)
    end = int(raw.get("end_line") or start)
    autofix = raw.get("autofix")
    remediation = raw.get("remediation")
    suggestion = str(autofix) if autofix else (str(remediation) if remediation else None)
    return {
        "finding_id": _finding_id(dedup),
        "run_id": run_id,
        "kind": "review_comment",
        "source": f"mergecraft_json:{raw.get('fingerprint')}",
        "rule_id": rule_id,
        "severity": _mergecraft_severity(raw),
        "category": str(raw.get("category") or ""),
        "effort": None,
        "suggestion": suggestion,
        "file": path or None,
        "line_range": [start, end],
        "symbol_ref": None,
        "message_raw": message,
        "message_normalized": message_norm,
        "raised_at": _now(),
        "head_sha": head_sha,
        "state": "open",
        "confidence": _mergecraft_confidence(raw),
        "evidence": evidence_text[:2000] if evidence_text else message[:500],
        "extractor": _EXTRACTOR_JSON,
        "extractor_version": _EXTRACTOR_VERSION,
        "mergecraft_fingerprint": str(raw.get("fingerprint") or ""),
        "mergecraft_tool": str(raw.get("tool") or ""),
        "mergecraft_source": str(raw.get("source") or ""),
        "introduced_by_pr": str(raw.get("introduced_by_pr") or "unknown"),
    }


def normalize_mergecraft_findings(
    raw_findings: list[dict[str, Any]],
    *,
    run_id: str = "local",
    head_sha: str = "",
) -> list[dict[str, Any]]:
    """Normalize a batch of mergeCraft findings.

    Args:
        raw_findings (list[dict[str, Any]]): mergeCraft Finding dicts.
        run_id (str): Run id for each normalized finding.
        head_sha (str): Optional git head SHA.

    Returns:
        list[dict[str, Any]]: Normalized tripll findings (one per input).
    """
    return [
        normalize_mergecraft_finding(item, run_id=run_id, head_sha=head_sha)
        for item in raw_findings
    ]


__all__ = [
    "MERGECRAFT_FINDING_REQUIRED_KEYS",
    "MergecraftFindingsPayloadError",
    "load_mergecraft_findings_json",
    "normalize_mergecraft_finding",
    "normalize_mergecraft_findings",
]
