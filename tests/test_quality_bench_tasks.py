"""Bench tasks G1-G10 for quality gauntlet (design section 9.4 extension)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripll.bench import load_tasks
from tripll.harness.quality import (
    parse_wave_outcome,
    quality_gauntlet_enabled,
    run_quality_gauntlet,
)
from tripll.harness.quality_dispatch import parse_quality_verdict

_BENCH_DIR = Path(__file__).resolve().parents[1] / "bench"

_QUALITY_GAUNTLET_TASKS: tuple[tuple[str, str], ...] = (
    ("g1-menu-section", "html_crop"),
    ("g2-skill-exemplar", "skill_exemplar"),
    ("g3-changelog-rubric", "rubric_only"),
    ("g4-runbook-section", "spec_section"),
    ("g5-error-panel", "html_crop"),
    ("g6-commit-skill", "skill_exemplar"),
    ("g7-readme-rubric", "rubric_only"),
    ("g8-outcome-spec", "spec_section"),
    ("g9-merge-gate", "html_crop"),
    ("g10-benchmark-bundle", "benchmark_task"),
)


@pytest.mark.parametrize(("task_id", "reference_kind"), _QUALITY_GAUNTLET_TASKS)
def test_g_bench_tasks_load_and_enable_quality_gauntlet(
    task_id: str,
    reference_kind: str,
) -> None:
    task_path = _BENCH_DIR / "tasks" / f"{task_id}.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    outcome = payload["outcome_contract"]
    assert outcome["reference"]["kind"] == reference_kind
    assert quality_gauntlet_enabled(outcome)
    ref_path = Path(outcome["reference"]["path"].split("#", 1)[0])
    assert (_BENCH_DIR.parent / ref_path).is_file()


def test_load_tasks_includes_g1_through_g10() -> None:
    ids = {task["task_id"] for task in load_tasks(_BENCH_DIR)}
    expected = {task_id for task_id, _ in _QUALITY_GAUNTLET_TASKS}
    assert expected.issubset(ids)
    assert len(expected) == 10


def test_g1_fixture_runs_quality_loop_with_stub_critic(tmp_path: Path) -> None:
    task_path = _BENCH_DIR / "tasks" / "g1-menu-section.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    outcome = parse_wave_outcome(
        payload["outcome_contract"],
        owned_paths=payload["owned_paths"],
    )
    wt = tmp_path / "wt"
    wt.mkdir()
    menu_dir = wt / "src" / "menu"
    menu_dir.mkdir(parents=True)
    (menu_dir / "deploy_section.html").write_text("<section>build</section>\n")

    ref_rel = "bench/tasks/g1-menu-section/reference/menu.html"
    ref = tmp_path / ref_rel
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(
        (_BENCH_DIR / "tasks" / "g1-menu-section" / "reference" / "menu.html").read_text()
    )

    outcome["reference"] = dict(outcome["reference"])
    outcome["reference"]["path"] = ref_rel

    def _critic(round_num: int, artifacts: list[str], reference: dict[str, str]):
        from tripll.harness.quality import QualityVerdict

        return QualityVerdict(
            round_num=round_num,
            comparison=str(reference.get("comparison") or ""),
            winner="build",
            gap="",
            artifact_paths=tuple(artifacts),
            reference_path=str(reference.get("path") or ""),
        )

    run_dir = tmp_path / "runs" / "g1"
    result = run_quality_gauntlet(
        repo_root=tmp_path,
        run_dir=run_dir,
        worktree=wt,
        node_id="g1-menu-section",
        outcome=outcome,
        critic_verdict=_critic,
    )
    assert result.state == "passed"
    assert (run_dir / "workbench.html").is_file()


def test_g4_spec_section_reference_exists() -> None:
    task_path = _BENCH_DIR / "tasks" / "g4-runbook-section.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    ref_path = payload["outcome_contract"]["reference"]["path"].split("#", 1)[0]
    ref = _BENCH_DIR.parent / ref_path
    text = ref.read_text(encoding="utf-8")
    assert "Stuck wave" in text
    assert "git clean -x" in text


def test_g10_benchmark_bundle_has_multiple_reference_files() -> None:
    bundle_dir = _BENCH_DIR / "tasks" / "g10-benchmark-bundle" / "reference"
    names = {path.name for path in bundle_dir.iterdir() if path.is_file()}
    assert {"README.md", "style.css"}.issubset(names)


def test_g3_rubric_verdict_parses_rubric_winner() -> None:
    text = json.dumps(
        {
            "winner": "reference",
            "gap": "category_correctness below bar",
            "comparison": "rubric",
            "round": 1,
            "artifact_paths": ["CHANGELOG.md"],
            "reference_path": "bench/tasks/g3-changelog-rubric/reference/rubric.md",
            "rubric_scores": {"specificity": 6},
        }
    )
    verdict = parse_quality_verdict(
        text,
        round_num=1,
        comparison="rubric",
        reference_path="bench/tasks/g3-changelog-rubric/reference/rubric.md",
        artifact_paths=("CHANGELOG.md",),
    )
    assert verdict is not None
    assert verdict.winner == "reference"
    assert "category" in verdict.gap


@pytest.mark.asyncio
async def test_g2_bench_reference_bundle_exists() -> None:
    task_path = _BENCH_DIR / "tasks" / "g2-skill-exemplar.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    ref = _BENCH_DIR.parent / payload["outcome_contract"]["reference"]["path"]
    assert ref.is_file()
    assert "Procedure" in ref.read_text(encoding="utf-8")
