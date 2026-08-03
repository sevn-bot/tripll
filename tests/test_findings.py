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
    out = tmp_path / ".mergecraft" / "learnings.md"
    export_learnings(
        [
            {
                "state": "rejected",
                "rule_id": "mergecraft:review",
                "message_raw": "unused import",
                "rationale": "intentional pattern",
            }
        ],
        path=out,
    )
    text = out.read_text()
    assert "Withdrawn review findings" in text
    assert "intentional" in text
    assert "mergecraft:review" in text


def test_review_comment_parses_mergecraft_triage_tags() -> None:
    normalize_review_comment = require_module(
        "tripll.github.findings", attr="normalize_review_comment"
    )
    raw = json.loads((_FIXTURES / "review_comment.json").read_text())
    finding = normalize_review_comment(raw)
    assert finding["rule_id"] == "mergecraft:review"
    assert finding["category"] == "Functional Correctness"
    assert finding["severity"] == "high"  # Major → high
    assert finding["effort"] == "Quick win"
    assert finding.get("suggestion")


def test_apply_gate_baseline_candidate_sets_state() -> None:
    apply_gate_verdict = require_module("tripll.github.findings", attr="apply_gate_verdict")
    FindingGateVerdict = require_module("tripll.github.findings", attr="FindingGateVerdict")
    finding = {"state": "open", "message_raw": "Null deref when input is empty"}
    updated = apply_gate_verdict(
        finding,
        FindingGateVerdict(
            verdict="baseline_candidate",
            noise_kind="none",
            reasoning="Concrete regression in the changed path.",
        ),
    )
    assert updated["state"] == "baseline_candidate"
    assert updated["gate_verdict"] == "baseline_candidate"
    assert updated["gate_reasoning"]


def test_apply_gate_noise_keeps_open_without_reject() -> None:
    apply_gate_verdict = require_module("tripll.github.findings", attr="apply_gate_verdict")
    FindingGateVerdict = require_module("tripll.github.findings", attr="FindingGateVerdict")
    finding = {"state": "open", "message_raw": "Maybe consider renaming this?"}
    updated = apply_gate_verdict(
        finding,
        FindingGateVerdict(
            verdict="noise",
            noise_kind="question",
            reasoning="Vague suggestion without a verifiable defect.",
        ),
    )
    assert updated["state"] == "open"
    assert updated["gate_verdict"] == "noise"
    assert updated["gate_noise_kind"] == "question"


def test_gate_precision_tracks_operator_triage() -> None:
    compute_gate_precision = require_module("tripll.github.findings", attr="compute_gate_precision")
    findings = [
        {"gate_verdict": "baseline_candidate", "state": "accepted"},
        {"gate_verdict": "baseline_candidate", "state": "rejected"},
        {"gate_verdict": "noise", "state": "rejected"},
        {"gate_verdict": "noise", "state": "accepted"},
    ]
    report = compute_gate_precision(findings)
    assert report.sample_size == 4
    assert report.true_positive == 1
    assert report.false_positive == 1
    assert report.true_negative == 1
    assert report.false_negative == 1
    assert report.precision == 0.5
    assert report.recall == 0.5


def test_gate_findings_skips_terminal_triage_states(monkeypatch) -> None:
    gate_findings = require_module("tripll.github.findings", attr="gate_findings")
    findings = [
        {"state": "accepted", "finding_id": "a"},
        {"state": "open", "finding_id": "b", "message_raw": "bug"},
    ]

    def _fake_judge(_model: str, finding: dict) -> object:
        FindingGateVerdict = require_module("tripll.github.findings", attr="FindingGateVerdict")
        return FindingGateVerdict(
            verdict="baseline_candidate",
            noise_kind="none",
            reasoning="test",
        )

    monkeypatch.setattr("tripll.github.findings._run_gate_judge", _fake_judge)
    gated = gate_findings(findings, model="test")
    assert gated[0]["state"] == "accepted"
    assert gated[1]["state"] == "baseline_candidate"
