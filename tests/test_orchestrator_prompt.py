"""Golden + unit tests for orchestrator prompt parsing (W1.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.graph import OrchestratorConfig
from tripll.parse.orchestrator_prompt import (
    build_orchestrator_config,
    discover_orchestrator_prompt,
    parse_orchestrator_mode,
    parse_orchestrator_prompt,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN_PROMPT = _REPO_ROOT / "plan" / "tripll-dashboard-ui-orchestrator-prompt.md"


@pytest.fixture
def golden_prompt_path() -> Path:
    if not _GOLDEN_PROMPT.is_file():
        pytest.skip(f"golden prompt not found: {_GOLDEN_PROMPT}")
    return _GOLDEN_PROMPT


def test_golden_dashboard_ui_wave_order(golden_prompt_path: Path) -> None:
    parsed = parse_orchestrator_prompt(golden_prompt_path)
    assert parsed.serial_waves == ["W0", "W1", "W2", "W3", "W4", "Final"]


def test_golden_dashboard_ui_feature_branch(golden_prompt_path: Path) -> None:
    parsed = parse_orchestrator_prompt(golden_prompt_path)
    assert parsed.feature_branch == "feature/tripll-dashboard-ui"


def test_golden_dashboard_ui_partial_ci_verify(golden_prompt_path: Path) -> None:
    parsed = parse_orchestrator_prompt(golden_prompt_path)
    assert parsed.verify_target == "partial-ci"
    assert parsed.ci_base == "origin/test-pre"
    w0 = next(r for r in parsed.wave_verify_commits if r.wave_id == "W0")
    assert "partial-ci" in w0.verify.lower()


def test_golden_dashboard_ui_reporting_columns(golden_prompt_path: Path) -> None:
    parsed = parse_orchestrator_prompt(golden_prompt_path)
    assert parsed.reporting_columns == [
        "Wave",
        "Status",
        "Branch",
        "Commit",
        "Evidence / blockers",
    ]


def test_golden_dashboard_ui_review_gate(golden_prompt_path: Path) -> None:
    parsed = parse_orchestrator_prompt(golden_prompt_path)
    assert parsed.review_gates.get("W0") == "W0.7"


def test_golden_build_orchestrator_config(tmp_path: Path, golden_prompt_path: Path) -> None:
    dest = tmp_path / "set"
    dest.mkdir()
    dest_prompt = dest / "tripll-dashboard-ui-orchestrator-prompt.md"
    dest_prompt.write_text(golden_prompt_path.read_text())
    cfg = build_orchestrator_config(dest, slug="tripll-dashboard-ui")
    assert isinstance(cfg, OrchestratorConfig)
    assert cfg.enabled is True
    assert cfg.single_branch is True
    assert cfg.commit_per_wave is True
    assert cfg.model_policy == "inherit"


def test_discover_prefers_slug_match(tmp_path: Path) -> None:
    other = tmp_path / "other-orchestrator-prompt.md"
    preferred = tmp_path / "demo-orchestrator-prompt.md"
    other.write_text("# other")
    preferred.write_text("# preferred")
    assert discover_orchestrator_prompt(tmp_path, slug="demo") == preferred


def test_orchestrator_mode_off_disables(tmp_path: Path) -> None:
    (tmp_path / "x-orchestrator-prompt.md").write_text("Feature branch: `f`\n")
    plan = "---\norchestrator_mode: off\n---\n# Plan\n"
    cfg = build_orchestrator_config(tmp_path, wave_plan_text=plan)
    assert cfg is None


def test_orchestrator_mode_serial_from_section() -> None:
    text = "## orchestrator mode\n\norchestrator_mode: serial\n"
    assert parse_orchestrator_mode(text) == "serial"
