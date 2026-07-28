"""Quality-critic and smoothing-pass adapter dispatch (D27)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._fakes import FakeAdapter
from tripll.adapters.base import DispatchResult
from tripll.graph import WaveNode
from tripll.harness.quality import quality_gauntlet_enabled
from tripll.harness.quality_dispatch import (
    build_quality_critic_brief,
    build_smoothing_brief,
    dispatch_quality_critic_round,
    dispatch_smoothing_pass,
    parse_quality_verdict,
    render_quality_critic_prompt,
    resolve_quality_adapter,
    run_quality_gauntlet_live,
)


class QualityCriticFakeAdapter(FakeAdapter):
    """FakeAdapter that returns a JSON quality verdict."""

    def __init__(self, *, winner: str = "build", gap: str = "") -> None:
        super().__init__()
        self.winner = winner
        self.gap = gap

    async def dispatch(
        self, brief, *, worktree_path, log_path, timeout_s, log_header=None, on_event=None
    ):
        self.calls += 1
        self.dispatched.append(str(brief.get("node_id", "?")))
        agent = str(brief.get("agent") or "")
        if agent == "smoothing-pass":
            payload = {"verdict": "no_op", "summary": "already consistent", "files_touched": []}
        else:
            payload = {
                "winner": self.winner,
                "gap": self.gap,
                "comparison": "blind_ab",
                "round": brief.get("quality_round", 1),
                "artifact_paths": brief.get("artifact_paths") or [],
                "reference_path": (brief.get("reference") or {}).get("path", ""),
            }
        return DispatchResult(
            outcome="done",
            result_text=json.dumps(payload),
            returncode=0,
            log_path=str(log_path),
            argv=self.build_argv(brief, worktree_path),
        )


def test_render_quality_critic_prompt_includes_round_and_paths(tmp_path: Path) -> None:
    prompt = render_quality_critic_prompt(
        round_num=2,
        comparison="blind_ab",
        reference={"kind": "html_crop", "path": "docs/ref.html", "stop_when": "reference_wins"},
        artifact_paths=["src/menu.py"],
        worktree_path=tmp_path,
        verdict_path=tmp_path / "quality-verdict.json",
    )
    assert "Round: 2" in prompt
    assert "src/menu.py" in prompt
    assert "blind_ab" in prompt


def test_parse_quality_verdict_from_json_block() -> None:
    text = 'noise {"winner": "reference", "gap": "tone drift", "comparison": "blind_ab"} tail'
    verdict = parse_quality_verdict(
        text,
        round_num=1,
        comparison="blind_ab",
        reference_path="docs/ref.html",
        artifact_paths=("src/a.py",),
    )
    assert verdict is not None
    assert verdict.winner == "reference"
    assert verdict.gap == "tone drift"


def test_build_quality_critic_brief_has_no_transcript(tmp_path: Path) -> None:
    brief = build_quality_critic_brief(
        run_id="run1",
        node_id="plan:W3",
        wave_id="W3",
        round_num=1,
        comparison="blind_ab",
        reference={"kind": "html_crop", "path": "docs/ref.html"},
        artifact_paths=["src/menu.py"],
        worktree_path=tmp_path,
        run_dir=tmp_path / "runs" / "run1",
        owned_paths=["src/menu.py"],
    )
    assert brief["agent"] == "quality-critic"
    assert "implementer transcript" in " ".join(brief["agent_directives"]).lower()
    assert brief.get("_prompt_override")
    assert (
        "transcript" not in str(brief).lower() or "no implementer transcript" in str(brief).lower()
    )


@pytest.mark.asyncio
async def test_dispatch_quality_critic_round_parses_verdict(tmp_path: Path) -> None:
    adapter = QualityCriticFakeAdapter(winner="build")
    brief = {
        "node_id": "plan:W3:quality:round-1",
        "agent": "quality-critic",
        "run_id": "run1",
        "quality_round": 1,
        "reference": {"path": "docs/ref.html"},
        "artifact_paths": ["src/menu.py"],
        "workspace_scope": ["src/menu.py"],
        "agent_directives": [],
    }
    run_dir = tmp_path / "runs" / "run1"
    result = await dispatch_quality_critic_round(
        adapter=adapter,
        brief=brief,
        worktree_path=tmp_path,
        run_dir=run_dir,
        round_num=1,
        comparison="blind_ab",
        reference_path="docs/ref.html",
        artifact_paths=("src/menu.py",),
    )
    assert result.outcome == "done"
    assert result.verdict is not None
    assert result.verdict.winner == "build"


@pytest.mark.asyncio
async def test_run_quality_gauntlet_live_with_fake_adapter(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    owned = wt / "src" / "menu.py"
    owned.parent.mkdir(parents=True)
    owned.write_text("menu copy\n")
    ref = tmp_path / "docs" / "ref.html"
    ref.parent.mkdir(parents=True)
    ref.write_text("<section>reference</section>\n")

    node = WaveNode(
        "plan:W3",
        "plan",
        "plan.md",
        "W3",
        "lane",
        owned_paths=["src/menu.py"],
    )
    outcome = {
        "reference": {
            "kind": "html_crop",
            "path": "docs/ref.html",
            "comparison": "blind_ab",
            "stop_when": "reference_wins",
        },
        "quality_gauntlet": {"enabled": True, "max_rounds": 3},
        "_owned_paths": ["src/menu.py"],
    }
    run_dir = tmp_path / "runs" / "run1"
    adapter = QualityCriticFakeAdapter(winner="build")
    result = await run_quality_gauntlet_live(
        repo_root=tmp_path,
        run_dir=run_dir,
        run_id="run1",
        worktree=wt,
        node=node,
        outcome=outcome,
        commit_sha="",
        adapter=adapter,
        adapter_override=adapter,
    )
    assert result.state == "passed"
    assert len(result.rounds) == 1
    assert adapter.calls == 1
    assert (run_dir / "workbench.html").is_file()


@pytest.mark.asyncio
async def test_dispatch_smoothing_pass_no_op(tmp_path: Path) -> None:
    adapter = QualityCriticFakeAdapter()
    brief = build_smoothing_brief(
        run_id="run1",
        node_id="plan:W3",
        wave_id="W3",
        owned_paths=["src/menu.py"],
        worktree_path=tmp_path,
        run_dir=tmp_path / "runs" / "run1",
        quality_rounds=2,
        reference_path="docs/ref.html",
    )
    ok, summary = await dispatch_smoothing_pass(
        adapter=adapter,
        brief=brief,
        worktree_path=tmp_path,
        run_dir=tmp_path / "runs" / "run1",
    )
    assert ok is True
    assert "consistent" in summary


def test_resolve_quality_adapter_uses_fake_override() -> None:
    fake = FakeAdapter()
    resolved = resolve_quality_adapter(
        run_dir=Path("/nonexistent"),
        agent="quality-critic",
        adapter_override=fake,
    )
    assert resolved is fake


def test_quality_gauntlet_enabled_for_bench_task_shape() -> None:
    task = {
        "outcome_contract": {
            "reference": {
                "kind": "html_crop",
                "path": "bench/tasks/g1-menu-section/reference/menu.html",
            },
            "quality_gauntlet": {"enabled": True},
        }
    }
    assert quality_gauntlet_enabled(task["outcome_contract"])
