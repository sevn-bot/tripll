"""Deterministic mergeCraft findings verifier for Harbor review tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _normalize_finding(raw: dict[str, Any]) -> dict[str, Any]:
    start = int(raw.get("start_line") or 1)
    end = int(raw.get("end_line") or start)
    return {
        "category": str(raw.get("category") or ""),
        "confidence": str(raw.get("confidence") or ""),
        "end_line": end,
        "fingerprint": str(raw.get("fingerprint") or ""),
        "message": str(raw.get("message") or ""),
        "path": str(raw.get("path") or ""),
        "rule_id": str(raw.get("rule_id") or ""),
        "severity": str(raw.get("severity") or ""),
        "start_line": start,
        "tool": str(raw.get("tool") or ""),
    }


def _load_payload(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: expected object envelope"
        raise ValueError(msg)
    findings = data.get("findings")
    if not isinstance(findings, list):
        msg = f"{path}: findings must be an array"
        raise ValueError(msg)
    return [_normalize_finding(item) for item in findings if isinstance(item, dict)]


def findings_match(actual_path: Path, expected_path: Path) -> bool:
    """Return True when both payloads contain identical normalized findings."""
    actual = sorted(_load_payload(actual_path), key=lambda row: row["fingerprint"])
    expected = sorted(_load_payload(expected_path), key=lambda row: row["fingerprint"])
    return actual == expected


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        sys.stderr.write("usage: verify_findings.py ACTUAL.json EXPECTED.json\n")
        return 2
    actual_path = Path(args[0])
    expected_path = Path(args[1])
    if not actual_path.is_file():
        sys.stderr.write(f"missing findings: {actual_path}\n")
        return 1
    if not expected_path.is_file():
        sys.stderr.write(f"missing expected: {expected_path}\n")
        return 1
    if findings_match(actual_path, expected_path):
        return 0
    sys.stderr.write("findings mismatch\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
