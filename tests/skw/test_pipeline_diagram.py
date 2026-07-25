"""Tests for deterministic pipeline diagram artifacts."""

from __future__ import annotations

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.pipeline_diagram import (
    build_pipeline_steps,
    render_pipeline_html,
    sync_pipeline_artifacts,
)

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"


def test_build_pipeline_steps_includes_review() -> None:
    steps = build_pipeline_steps(PIPELINE_FIXTURE, KIT_ROOT)
    kinds = [step.kind for step in steps]
    assert kinds[0] == "validate"
    assert "review" in kinds
    assert "generate" in kinds


def test_render_pipeline_html_deterministic() -> None:
    steps = build_pipeline_steps(PIPELINE_FIXTURE, KIT_ROOT)
    html_a = render_pipeline_html(
        title="T",
        slug="s",
        branch="b",
        base="main",
        steps=steps,
    )
    html_b = render_pipeline_html(
        title="T",
        slug="s",
        branch="b",
        base="main",
        steps=steps,
    )
    assert html_a == html_b
    assert "<!DOCTYPE html>" in html_a
    assert "reviewer" in html_a or "wave-runner" in html_a


def test_sync_pipeline_artifacts_writes_files(tmp_path) -> None:
    import shutil

    kit = tmp_path / "kit"
    shutil.copytree(KIT_ROOT / "prompts", kit / "prompts")
    wave = kit / "wave.md"
    wave.write_text(PIPELINE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    json_path, html_path = sync_pipeline_artifacts(wave, kit)
    assert json_path.is_file()
    assert html_path.is_file()
    assert html_path.suffix == ".html"
