"""Tests for mergeCraft diff-review --json ingest (W8 / #64)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli._review import review_app
from tripll.review.findings_json import (
    MergecraftFindingsPayloadError,
    load_mergecraft_findings_json,
    normalize_mergecraft_finding,
    normalize_mergecraft_findings,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "review" / "mergecraft_findings.json"
_RUNNER = CliRunner()


def test_load_mergecraft_findings_json_reads_fixture() -> None:
    raw = load_mergecraft_findings_json(_FIXTURE)
    assert len(raw) == 1
    assert raw[0]["tool"] == "agent"
    assert raw[0]["fingerprint"] == "a1b2c3d4e5f6789012345678"


def test_load_mergecraft_findings_json_rejects_missing_findings(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(MergecraftFindingsPayloadError, match="missing required key"):
        load_mergecraft_findings_json(bad)


def test_normalize_mergecraft_finding_maps_to_tripll_schema() -> None:
    raw = load_mergecraft_findings_json(_FIXTURE)[0]
    finding = normalize_mergecraft_finding(raw, head_sha="deadbeef")
    assert finding["rule_id"] == "mergecraft:review"
    assert finding["kind"] == "review_comment"
    assert finding["file"] == "src/tripll/demo.py"
    assert finding["line_range"] == [10, 12]
    assert finding["severity"] == "high"
    assert finding["confidence"] == 0.75
    assert finding["head_sha"] == "deadbeef"
    assert finding["extractor"] == "tripll.review.findings_json"
    assert finding["mergecraft_fingerprint"] == "a1b2c3d4e5f6789012345678"


def test_normalize_mergecraft_findings_batch() -> None:
    raw = load_mergecraft_findings_json(_FIXTURE)
    out = normalize_mergecraft_findings(raw)
    assert len(out) == 1
    assert out[0]["finding_id"]


def test_review_load_json_cli_emits_normalized_payload() -> None:
    result = _RUNNER.invoke(review_app, ["load-json", str(_FIXTURE)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload["findings"], list)
    assert payload["findings"][0]["rule_id"] == "mergecraft:review"
