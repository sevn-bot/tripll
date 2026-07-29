"""Tests for tripll.review — mergeCraft config, scaffold, dispatch."""

from __future__ import annotations

from pathlib import Path

from tripll.config import load_config
from tripll.review import (
    ReviewConfig,
    dispatch_mode,
    review_config_from_raw,
    scaffold_mergecraft,
)


def test_review_config_defaults() -> None:
    cfg = review_config_from_raw(None)
    assert cfg.provider == "mergecraft"
    assert cfg.posture == "review_only"
    assert cfg.ci.push == "disabled"
    assert not cfg.allows_mode_dispatch()


def test_review_config_fix_posture() -> None:
    cfg = review_config_from_raw(
        {
            "posture": "fix",
            "ci": {"push": "restricted", "shell": "restricted"},
        }
    )
    assert cfg.posture == "fix"
    assert cfg.allows_mode_dispatch()
    assert cfg.ci.push == "restricted"


def test_load_config_includes_review(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TRIPLL_DEFAULT_PROVIDER", raising=False)
    (tmp_path / "tripll.toml").write_text(
        '[review]\nposture = "full"\n\n[review.ci]\npush = "restricted"\n',
        encoding="utf-8",
    )
    cfg = load_config(repo_root=tmp_path)
    assert isinstance(cfg.review, ReviewConfig)
    assert cfg.review.posture == "full"
    assert cfg.review.allows_mode_dispatch()


def test_scaffold_mergecraft_writes_paths(tmp_path: Path) -> None:
    msgs = scaffold_mergecraft(tmp_path, force=True, write_workflow=True)
    assert (tmp_path / ".mergecraft" / "config.yaml").is_file()
    assert (tmp_path / ".mergecraft" / "learnings.md").is_file()
    assert (tmp_path / ".github" / "workflows" / "mergecraft.yml").is_file()
    assert any("mergecraft" in m for m in msgs)
    text = (tmp_path / ".mergecraft" / "learnings.md").read_text(encoding="utf-8")
    assert "Withdrawn review findings" in text


def test_dispatch_skipped_under_review_only() -> None:
    result = dispatch_mode(
        pr=1,
        mode="Fix",
        prompt="fix CI",
        review=ReviewConfig(posture="review_only"),
    )
    assert result["skipped"] is True
    assert result["ok"] is True


def test_dispatch_dry_run_when_posture_allows() -> None:
    result = dispatch_mode(
        pr=42,
        mode="AddressReviews",
        prompt="fix review comments",
        review=ReviewConfig(posture="fix"),
        dry_run=True,
    )
    assert result["skipped"] is False
    assert result["dry_run"] is True
    assert "AddressReviews" in result["prompt"]
