"""GitHub ingestion — Finding schema, dedup, staleness, learnings (W1.11)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import require_module

_FIXTURES = Path(__file__).parent / "fixtures" / "github"


def test_check_run_normalizes_to_finding_schema() -> None:
    normalize_check_run = require_module("tripll.github.findings", attr="normalize_check_run")
    raw = json.loads((_FIXTURES / "check_run.json").read_text())
    finding = normalize_check_run(raw)
    assert finding["kind"] == "ci_check"
    assert finding["rule_id"]
    assert finding["head_sha"] == "abc123def456"
    assert finding["extractor"] == "github.findings"


def test_review_comment_normalizes_to_finding_schema() -> None:
    normalize_review_comment = require_module(
        "tripll.github.findings", attr="normalize_review_comment"
    )
    raw = json.loads((_FIXTURES / "review_comment.json").read_text())
    finding = normalize_review_comment(raw)
    assert finding["kind"] == "review_comment"
    assert finding["file"] == "src/tripll/demo.py"


def test_dedup_key_collapses_duplicates() -> None:
    dedup_findings = require_module("tripll.github.findings", attr="dedup_findings")
    base = {
        "rule_id": "ruff:F401",
        "file": "src/a.py",
        "symbol_ref": "code:Symbol:foo",
        "message_normalized": "unused import",
    }
    findings = [base | {"finding_id": "1"}, base | {"finding_id": "2"}]
    collapsed = dedup_findings(findings)
    assert len(collapsed) == 1


def test_about_resolves_to_symbol() -> None:
    resolve_about = require_module("tripll.github.findings", attr="resolve_about")
    finding = {"file": "src/tripll/demo.py", "line_range": [10, 10]}
    symbol_id = resolve_about(finding, graph_store=":memory:")
    assert symbol_id.startswith("code:Symbol:")


def test_finding_stale_when_about_target_has_valid_to_sha() -> None:
    is_stale = require_module("tripll.github.findings", attr="is_stale")
    finding = {"head_sha": "abc", "about_target": {"valid_to_sha": "def"}}
    assert is_stale(finding, current_head="xyz") is True


def test_rejected_findings_export_to_learnings(tmp_path: Path) -> None:
    export_learnings = require_module("tripll.github.learnings", attr="export_learnings")
    out = tmp_path / ".pullfrog" / "learnings.md"
    export_learnings(
        [
            {
                "state": "rejected",
                "rule_id": "pullfrog:style",
                "rationale": "intentional pattern",
            }
        ],
        path=out,
    )
    text = out.read_text()
    assert "rejected" in text.lower() or "intentional" in text
