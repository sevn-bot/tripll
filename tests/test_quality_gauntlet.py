"""Quality gauntlet harness and plan wiring (D26-D28)."""

from __future__ import annotations

from pathlib import Path

from tripll.harness.contracts import render_completion
from tripll.harness.quality import (
    QualityVerdict,
    check_quality_exits,
    evaluate_stop_condition,
    parse_wave_outcome,
    quality_gauntlet_enabled,
    resolve_decomposition,
    run_quality_gauntlet,
)
from tripll.plan.providers import wave_node_from_v3


def test_quality_gauntlet_enabled_requires_reference_path() -> None:
    assert quality_gauntlet_enabled(
        {"quality_gauntlet": {"enabled": True}, "reference": {"path": "docs/x.html"}}
    )
    assert not quality_gauntlet_enabled({"quality_gauntlet": {"enabled": True}, "reference": {}})


def test_resolve_decomposition_wave_override() -> None:
    assert (
        resolve_decomposition(
            wave_decomposition="gauntlet",
            quality={"decomposition": "prescribed"},
        )
        == "gauntlet"
    )


def test_evaluate_stop_reference_wins() -> None:
    verdict = QualityVerdict(
        round_num=1,
        comparison="blind_ab",
        winner="build",
        gap="",
        artifact_paths=("src/a.py",),
        reference_path="docs/ref.html",
    )
    stop, reason = evaluate_stop_condition(
        stop_when="reference_wins",
        verdict=verdict,
        round_num=1,
        max_rounds=5,
    )
    assert stop is True
    assert "build" in reason


def test_check_quality_exits_turn_cap() -> None:
    assert (
        check_quality_exits(
            round_num=6,
            max_rounds=5,
            sub_budget_spent=0.0,
            sub_budget_usd=0.0,
            artifact_hashes=["a", "b", "c"],
        )
        == 2
    )


def test_run_quality_gauntlet_writes_workbench(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    owned = wt / "src" / "menu.py"
    owned.parent.mkdir(parents=True)
    owned.write_text("menu copy\n")
    ref = tmp_path / "docs" / "ref.html"
    ref.parent.mkdir(parents=True)
    ref.write_text("<section>reference</section>\n")

    outcome = parse_wave_outcome(
        {
            "reference": {
                "kind": "html_crop",
                "path": "docs/ref.html",
                "comparison": "blind_ab",
                "stop_when": "reference_wins",
            },
            "quality_gauntlet": {"enabled": True, "max_rounds": 3},
        },
        owned_paths=["src/menu.py"],
    )

    def _critic(
        round_num: int,
        artifacts: list[str],
        reference: dict[str, str],
    ) -> QualityVerdict:
        return QualityVerdict(
            round_num=round_num,
            comparison=str(reference.get("comparison") or ""),
            winner="build",
            gap="",
            artifact_paths=tuple(artifacts),
            reference_path=str(reference.get("path") or ""),
        )

    run_dir = tmp_path / "runs" / "r1"
    result = run_quality_gauntlet(
        repo_root=tmp_path,
        run_dir=run_dir,
        worktree=wt,
        node_id="plan:W3",
        outcome=outcome,
        critic_verdict=_critic,
    )
    assert result.state == "passed"
    assert (run_dir / "workbench.html").is_file()
    assert (run_dir / "quality-rounds.json").is_file()


def test_wave_node_from_v3_carries_outcome_contract() -> None:
    wave = {
        "id": "W3",
        "targets": ["src/menu.py"],
        "decomposition": "gauntlet",
        "outcome": {
            "reference": {"kind": "html_crop", "path": "docs/ref.html"},
            "quality_gauntlet": {"enabled": True},
        },
    }
    node = wave_node_from_v3(
        wave,
        plan_id="plan",
        plan_file="plan.md",
        lane="lane",
        owned_paths=["src/menu.py"],
        node_id_map={"W3": "plan:W3"},
    )
    assert node.decomposition == "gauntlet"
    assert node.outcome_contract is not None
    assert node.outcome_contract["quality_gauntlet"]["enabled"] is True


def test_render_completion_includes_quality_rounds() -> None:
    msg = render_completion(
        grader_output={"make test": "pass"},
        quality_rounds=[{"round": 1, "winner": "build", "gap": ""}],
    )
    assert "Quality gauntlet" in msg
    assert "Round 1" in msg
