"""Regression tests for TurnContext / turn-open state (Fix-W1.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.skw._graph_helpers import copy_minimal_kit, invoke_pipeline_node, write_verdict
from tripll.skw.pipeline import PipelineBuilder

SLUG = "pipeline-three-wave"


def test_validate_node_sets_waves_before_at_turn_open(tmp_path: Path) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    waves_dir = kit_root / "waves"
    (waves_dir / "alpha-wave-plan.md").write_text("# alpha\n", encoding="utf-8")
    (waves_dir / "beta-wave-plan.md").write_text("# beta\n", encoding="utf-8")

    builder = PipelineBuilder.from_wave_file(wave_file, kit_root=kit_root)
    result = invoke_pipeline_node(
        builder,
        "validate",
        {"wave_file": str(wave_file), "turn": 1},
    )
    assert result.get("waves_before") == [
        "waves/alpha-wave-plan.md",
        "waves/beta-wave-plan.md",
    ]


def test_snapshot_waves_lists_wave_plan_files(tmp_path: Path) -> None:
    from tripll.skw.turn_context import snapshot_waves

    kit_root, _wave_file = copy_minimal_kit(tmp_path)
    waves_dir = kit_root / "waves"
    (waves_dir / "z-wave-plan.md").write_text("# z\n", encoding="utf-8")
    (waves_dir / "a-wave-plan.md").write_text("# a\n", encoding="utf-8")

    assert snapshot_waves(kit_root) == [
        "waves/a-wave-plan.md",
        "waves/z-wave-plan.md",
    ]


def test_review_node_loads_verdict_into_state(tmp_path: Path) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    write_verdict(kit_root, SLUG, "changes_required")

    builder = PipelineBuilder.from_wave_file(wave_file, kit_root=kit_root)
    result = invoke_pipeline_node(
        builder,
        "review",
        {"wave_file": str(wave_file), "history": [], "turn": 1},
    )
    assert result.get("verdict") == "changes_required"


def test_load_verdict_reads_review_result_json(tmp_path: Path) -> None:
    from tripll.skw.turn_context import load_verdict

    kit_root, _wave_file = copy_minimal_kit(tmp_path)
    write_verdict(kit_root, SLUG, "pass")

    assert load_verdict(kit_root, SLUG) == "pass"


def test_load_verdict_missing_file_raises(tmp_path: Path) -> None:
    from tripll.skw.turn_context import load_verdict

    kit_root, _wave_file = copy_minimal_kit(tmp_path)

    with pytest.raises((FileNotFoundError, ValueError), match=r"review-result|verdict|missing"):
        load_verdict(kit_root, SLUG)


def test_review_node_missing_verdict_raises(tmp_path: Path) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    builder = PipelineBuilder.from_wave_file(wave_file, kit_root=kit_root)

    with pytest.raises((FileNotFoundError, ValueError), match=r"review-result|verdict|missing"):
        invoke_pipeline_node(
            builder,
            "review",
            {"wave_file": str(wave_file), "history": [], "turn": 1},
        )


def test_load_verdict_empty_verdict_raises(tmp_path: Path) -> None:
    from tripll.skw.turn_context import load_verdict

    kit_root, _wave_file = copy_minimal_kit(tmp_path)
    path = kit_root / "waves" / f"{SLUG}.review-result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"verdict": "", "findings": []}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"verdict|empty"):
        load_verdict(kit_root, SLUG)


def test_review_node_empty_verdict_not_silent_continue(tmp_path: Path) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    write_verdict(kit_root, SLUG, "")
    builder = PipelineBuilder.from_wave_file(wave_file, kit_root=kit_root)

    with pytest.raises(ValueError, match=r"verdict|empty"):
        invoke_pipeline_node(
            builder,
            "review",
            {"wave_file": str(wave_file), "history": [], "turn": 1},
        )
