"""Tests for ``skw.changelog_eval`` — double LLM score (mocked judge, no network).

Every model call is monkeypatched at the single ``_run_judge`` seam, so these
tests spend no tokens and make no network calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tripll.skw import changelog_eval as ce

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

_CHANGELOG = """# Changelog

## [Unreleased]

### Added

- New `--retry` flag on `sevn onboard` to resume interrupted runs

### Changed

### Fixed

- Crash when a workspace path contained a trailing space

### Security

## [0.0.1] - 2026-07-08

### Added

- First release
"""

_EMPTY_UNRELEASED = """# Changelog

## [Unreleased]

### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security

## [0.0.1] - 2026-07-08

### Added

- First release
"""


def _stub_judge(structured_scores: dict[str, int], unstructured: int):
    """Return a fake ``_run_judge`` yielding fixed structured + holistic scores."""

    def _fake(model: str, instructions: str, prompt: str, output_type: type[Any]) -> Any:
        if output_type is ce.StructuredScore:
            return ce.StructuredScore(
                scores=[
                    ce.DimensionScore(dimension=dim, score=score, rationale=f"{dim} ok")
                    for dim, score in structured_scores.items()
                ]
            )
        if output_type is ce.UnstructuredScore:
            return ce.UnstructuredScore(score=unstructured, rationale="holistic prose")
        raise AssertionError(f"unexpected output_type {output_type!r}")

    return _fake


def _write_changelog(tmp_path: Path, text: str = _CHANGELOG) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(text, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class TestLoadEvalConfig:
    def test_defaults_when_missing(self) -> None:
        cfg = ce.load_eval_config(None)
        assert cfg.structured_min == 7
        assert cfg.unstructured_min == 7
        assert cfg.rubric_dimensions == ce.DEFAULT_RUBRIC_DIMENSIONS

    def test_reads_eval_block(self, tmp_path: Path) -> None:
        toml = tmp_path / "changelog-rules.toml"
        toml.write_text(
            "[eval]\n"
            "structured_min = 8\n"
            "unstructured_min = 6\n"
            'rubric_dimensions = ["specificity", "clarity"]\n'
            'judge_model = "anthropic:claude-haiku-4-5-20251001"\n',
            encoding="utf-8",
        )
        cfg = ce.load_eval_config(toml)
        assert cfg.structured_min == 8
        assert cfg.unstructured_min == 6
        assert cfg.rubric_dimensions == ("specificity", "clarity")

    def test_partial_block_falls_back(self, tmp_path: Path) -> None:
        toml = tmp_path / "changelog-rules.toml"
        toml.write_text("[eval]\nstructured_min = 9\n", encoding="utf-8")
        cfg = ce.load_eval_config(toml)
        assert cfg.structured_min == 9
        assert cfg.unstructured_min == 7  # fallback
        assert cfg.rubric_dimensions == ce.DEFAULT_RUBRIC_DIMENSIONS


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


class TestExtractEntries:
    def test_extracts_bullets_with_categories(self) -> None:
        entries = ce.extract_unreleased_entries(_CHANGELOG)
        assert [(e.category, e.text) for e in entries] == [
            ("Added", "New `--retry` flag on `sevn onboard` to resume interrupted runs"),
            ("Fixed", "Crash when a workspace path contained a trailing space"),
        ]

    def test_does_not_leak_into_released_versions(self) -> None:
        entries = ce.extract_unreleased_entries(_CHANGELOG)
        assert all("First release" not in e.text for e in entries)

    def test_empty_unreleased_yields_no_entries(self) -> None:
        assert ce.extract_unreleased_entries(_EMPTY_UNRELEASED) == []

    def test_missing_unreleased_block(self) -> None:
        assert ce.extract_unreleased_entries("# Changelog\n## [0.1] - 2026\n- x\n") == []


# --------------------------------------------------------------------------- #
# Verdict logic against thresholds
# --------------------------------------------------------------------------- #


class TestBuildVerdict:
    def test_pass_when_both_clear(self) -> None:
        structured = ce.StructuredScore(
            scores=[ce.DimensionScore(dimension=d, score=8, rationale="ok") for d in ("a", "b")]
        )
        unstructured = ce.UnstructuredScore(score=8, rationale="clear")
        verdict = ce.build_verdict(structured, unstructured, ce.EvalConfig(), 2)
        assert verdict.passed
        assert verdict.structured_passed
        assert verdict.unstructured_passed
        assert verdict.failing_dimensions == ()

    def test_fail_when_one_dimension_below(self) -> None:
        structured = ce.StructuredScore(
            scores=[
                ce.DimensionScore(dimension="a", score=8, rationale="ok"),
                ce.DimensionScore(dimension="b", score=5, rationale="vague"),
            ]
        )
        unstructured = ce.UnstructuredScore(score=9, rationale="great")
        verdict = ce.build_verdict(structured, unstructured, ce.EvalConfig(), 2)
        assert not verdict.passed
        assert not verdict.structured_passed
        assert verdict.unstructured_passed
        assert verdict.failing_dimensions == ("b",)

    def test_fail_when_holistic_below(self) -> None:
        structured = ce.StructuredScore(
            scores=[ce.DimensionScore(dimension=d, score=9, rationale="ok") for d in ("a", "b")]
        )
        unstructured = ce.UnstructuredScore(score=4, rationale="weak")
        verdict = ce.build_verdict(structured, unstructured, ce.EvalConfig(), 2)
        assert not verdict.passed
        assert verdict.structured_passed
        assert not verdict.unstructured_passed

    def test_boundary_equal_to_threshold_passes(self) -> None:
        structured = ce.StructuredScore(
            scores=[ce.DimensionScore(dimension="a", score=7, rationale="edge")]
        )
        unstructured = ce.UnstructuredScore(score=7, rationale="edge")
        verdict = ce.build_verdict(structured, unstructured, ce.EvalConfig(), 1)
        assert verdict.passed

    def test_empty_structured_is_fail(self) -> None:
        structured = ce.StructuredScore(scores=[])
        unstructured = ce.UnstructuredScore(score=10, rationale="n/a")
        verdict = ce.build_verdict(structured, unstructured, ce.EvalConfig(), 0)
        assert not verdict.structured_passed
        assert not verdict.passed


# --------------------------------------------------------------------------- #
# Scoring passes (mocked judge)
# --------------------------------------------------------------------------- #


class TestScoringPasses:
    def test_score_structured_uses_judge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ce, "_run_judge", _stub_judge({"specificity": 9}, 8))
        entries = ce.extract_unreleased_entries(_CHANGELOG)
        result = ce.score_structured(entries, "test-model")
        assert result.by_dimension()["specificity"].score == 9

    def test_score_structured_empty_raises(self) -> None:
        with pytest.raises(ce.NoEntriesError):
            ce.score_structured([], "test-model")

    def test_score_unstructured_uses_judge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ce, "_run_judge", _stub_judge({"specificity": 9}, 6))
        entries = ce.extract_unreleased_entries(_CHANGELOG)
        result = ce.score_unstructured(entries, "test-model")
        assert result.score == 6


# --------------------------------------------------------------------------- #
# End-to-end evaluate (mocked judge + model access)
# --------------------------------------------------------------------------- #


def _all_dims(config: ce.EvalConfig, score: int) -> dict[str, int]:
    return {dim: score for dim in config.rubric_dimensions}


class TestEvaluate:
    def test_pass_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _write_changelog(tmp_path)
        monkeypatch.setattr(ce, "_run_judge", _stub_judge(_all_dims(ce.EvalConfig(), 9), 8))
        verdict = ce.evaluate(repo, model="test-model", diff_context="")
        assert verdict.passed
        assert verdict.entry_count == 2

    def test_structured_fail_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _write_changelog(tmp_path)
        scores = _all_dims(ce.EvalConfig(), 9)
        scores["diff_equivalence"] = 3
        monkeypatch.setattr(ce, "_run_judge", _stub_judge(scores, 9))
        verdict = ce.evaluate(repo, model="test-model", diff_context="")
        assert not verdict.passed
        assert "diff_equivalence" in verdict.failing_dimensions

    def test_no_entries_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _write_changelog(tmp_path, _EMPTY_UNRELEASED)
        monkeypatch.setattr(ce, "_run_judge", _stub_judge(_all_dims(ce.EvalConfig(), 9), 9))
        with pytest.raises(ce.NoEntriesError):
            ce.evaluate(repo, model="test-model", diff_context="")

    def test_no_model_access_fails_loudly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _write_changelog(tmp_path)
        for var in ce._MODEL_KEY_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(ce.MODEL_ENV_VAR, raising=False)
        with pytest.raises(ce.ModelUnavailableError):
            ce.evaluate(repo, model="anthropic:claude-haiku-4-5-20251001", diff_context="")

    def test_test_model_bypasses_credential_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _write_changelog(tmp_path)
        for var in ce._MODEL_KEY_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(ce, "_run_judge", _stub_judge(_all_dims(ce.EvalConfig(), 8), 8))
        verdict = ce.evaluate(repo, model="test-model", diff_context="")
        assert verdict.passed


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class TestCli:
    def test_cli_pass_returns_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _write_changelog(tmp_path)
        monkeypatch.setattr(ce, "_run_judge", _stub_judge(_all_dims(ce.EvalConfig(), 9), 9))
        monkeypatch.setattr(ce, "gather_diff_context", lambda *a, **k: "")
        rc = ce.main(["--repo", str(repo), "--model", "test-model", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        assert '"passed": true' in out

    def test_cli_quality_fail_returns_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _write_changelog(tmp_path)
        scores = _all_dims(ce.EvalConfig(), 9)
        scores["specificity"] = 2
        monkeypatch.setattr(ce, "_run_judge", _stub_judge(scores, 9))
        monkeypatch.setattr(ce, "gather_diff_context", lambda *a, **k: "")
        rc = ce.main(["--repo", str(repo), "--model", "test-model"])
        assert rc == 1
        assert "FAIL" in capsys.readouterr().out

    def test_cli_no_model_returns_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _write_changelog(tmp_path)
        for var in ce._MODEL_KEY_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(ce.MODEL_ENV_VAR, raising=False)
        rc = ce.main(["--repo", str(repo), "--model", "anthropic:claude-haiku-4-5-20251001"])
        assert rc == 2
        assert "no model access" in capsys.readouterr().err

    def test_cli_no_entries_returns_three(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _write_changelog(tmp_path, _EMPTY_UNRELEASED)
        rc = ce.main(["--repo", str(repo), "--model", "test-model"])
        assert rc == 3
        assert "no entries" in capsys.readouterr().err.lower()
