"""Integration tests for review/generate loop semantics (Fix-W1.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.skw._graph_helpers import copy_minimal_kit, invoke_pipeline_node, write_verdict
from tripll.skw.graph_nodes import run_remediation_turn
from tripll.skw.pipeline import PipelineBuilder, run_pipeline

PIPELINE_FIXTURE_SLUG = "pipeline-three-wave"
NEW_WAVE = "waves/generated-fix-wave-plan.md"
REMEDIATION_SLUG = "generated-fix"


def _minimal_new_wave_markdown() -> str:
    return """# Generated fix wave

```toml
waveorch_format = 2
title = "Generated fix wave"
slug = "generated-fix"
base = "origin/main"
branch = "feature/generated-fix"

[pipeline]
max_turns = 3

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[[waves]]
id = "Fix-W2"
title = "Fix wave"
depends_on = []
role = "impl"
verify = ["make validate-selftest"]
```

## Wave Fix-W2 — Fix wave

- [ ] **Fix-W2.1** Pending fix task.
"""


def test_cross_check_detects_new_wave_against_waves_before(tmp_path: Path) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    waves_dir = kit_root / "waves"
    (waves_dir / "original-wave-plan.md").write_text("# original\n", encoding="utf-8")
    (waves_dir / "generated-fix-wave-plan.md").write_text(
        _minimal_new_wave_markdown(),
        encoding="utf-8",
    )

    builder = PipelineBuilder.from_wave_file(wave_file, kit_root=kit_root)
    state = {
        "wave_file": str(wave_file),
        "waves_before": ["waves/original-wave-plan.md"],
        "history": [],
        "verdict": "changes_required",
    }
    result = invoke_pipeline_node(builder, "cross_check", state)

    assert result.get("new_wave_files") == [NEW_WAVE]


def test_run_remediation_turn_rescans_and_validates_new_wave(tmp_path: Path) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    waves_dir = kit_root / "waves"
    (waves_dir / "seed-wave-plan.md").write_text("# seed\n", encoding="utf-8")
    (waves_dir / "generated-fix-wave-plan.md").write_text(
        _minimal_new_wave_markdown(),
        encoding="utf-8",
    )

    builder = PipelineBuilder.from_wave_file(wave_file, kit_root=kit_root)
    new_path = run_remediation_turn(
        builder,
        wave_file=wave_file,
        waves_before=["waves/seed-wave-plan.md"],
    )

    assert new_path == kit_root / NEW_WAVE


def test_run_pipeline_recompiles_graph_with_new_slug_and_wave_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    write_verdict(kit_root, PIPELINE_FIXTURE_SLUG, "changes_required")
    write_verdict(kit_root, REMEDIATION_SLUG, "pass")
    monkeypatch.setenv("SKW_AUTO_APPROVE", "1")

    builders_seen: list[PipelineBuilder] = []
    original_from_wave = PipelineBuilder.from_wave_file

    def _track_from_wave(wave_path: Path, kit_root_arg: Path) -> PipelineBuilder:
        builder = original_from_wave(wave_path, kit_root_arg)
        builders_seen.append(builder)
        return builder

    commit_calls: list[dict[str, object]] = []

    def _mock_commit(**kwargs: object) -> None:
        commit_calls.append(dict(kwargs))

    def _mock_run_agent(**kwargs: object) -> int:
        if kwargs.get("stage") == "generate":
            new_path = kit_root / NEW_WAVE
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(_minimal_new_wave_markdown(), encoding="utf-8")
        return 0

    monkeypatch.setattr(PipelineBuilder, "from_wave_file", staticmethod(_track_from_wave))
    monkeypatch.setattr("tripll.skw.pipeline._in_pytest", lambda: False)
    monkeypatch.setattr("tripll.skw.pipeline.run_agent", _mock_run_agent)
    monkeypatch.setattr("tripll.skw.pipeline.commit_wave", _mock_commit)
    monkeypatch.setattr(
        "tripll.skw.verify.subprocess.run",
        lambda *_args, **_kwargs: MagicMock(returncode=0),
    )

    result = run_pipeline(wave_file, kit_root)

    assert len(builders_seen) == 2
    assert builders_seen[0].slug == PIPELINE_FIXTURE_SLUG
    assert [s["id"] for s in builders_seen[0].states] == ["W1", "W2", "Final"]
    assert builders_seen[1].slug == REMEDIATION_SLUG
    assert [s["id"] for s in builders_seen[1].states] == ["Fix-W2"]

    history = result.get("history") or []
    run_nodes = [entry["node"] for entry in history if entry.get("action") == "run"]
    assert "Fix-W2" in run_nodes
    assert result.get("verdict") == "pass"

    remediation_commits = [c for c in commit_calls if c.get("slug") == REMEDIATION_SLUG]
    assert remediation_commits
    assert any(c.get("wave_id") == "Fix-W2" for c in remediation_commits)
    assert all(c.get("slug") != PIPELINE_FIXTURE_SLUG for c in remediation_commits)


def test_run_pipeline_uses_initial_max_turns_not_remediation_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    wave_file.write_text(
        wave_file.read_text(encoding="utf-8").replace("max_turns = 3", "max_turns = 2"),
        encoding="utf-8",
    )
    remediation_md = _minimal_new_wave_markdown().replace("max_turns = 3", "max_turns = 99")
    write_verdict(kit_root, PIPELINE_FIXTURE_SLUG, "changes_required")
    write_verdict(kit_root, REMEDIATION_SLUG, "changes_required")
    monkeypatch.setenv("SKW_AUTO_APPROVE", "1")

    def _mock_run_agent(**kwargs: object) -> int:
        if kwargs.get("stage") == "generate":
            new_path = kit_root / NEW_WAVE
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(remediation_md, encoding="utf-8")
        return 0

    monkeypatch.setattr("tripll.skw.pipeline._in_pytest", lambda: False)
    monkeypatch.setattr("tripll.skw.pipeline.run_agent", _mock_run_agent)
    monkeypatch.setattr(
        "tripll.skw.verify.subprocess.run",
        lambda *_args, **_kwargs: MagicMock(returncode=0),
    )

    with pytest.raises(ValueError, match=r"max_turns=2"):
        run_pipeline(wave_file, kit_root)


def test_run_pipeline_generate_failure_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit_root, wave_file = copy_minimal_kit(tmp_path)
    write_verdict(kit_root, PIPELINE_FIXTURE_SLUG, "changes_required")
    monkeypatch.setenv("SKW_AUTO_APPROVE", "1")

    def _fail_generate(**_kwargs: object) -> int:
        return 42

    monkeypatch.setattr("tripll.skw.pipeline._in_pytest", lambda: False)
    monkeypatch.setattr("tripll.skw.pipeline.run_agent", _fail_generate)
    monkeypatch.setattr(
        "tripll.skw.verify.subprocess.run",
        lambda *_args, **_kwargs: MagicMock(returncode=0),
    )

    with pytest.raises(Exception, match=r"42|AgentRunError|exit|non-zero"):
        run_pipeline(wave_file, kit_root)
