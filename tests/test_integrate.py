"""Tests for tripll.integrate — per-batch integration plan + execution."""

from __future__ import annotations

import pytest

from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.integrate import (
    CommandRunner,
    IntegrationError,
    execute_integration,
    plan_integration,
    render_dry_run,
)


def _graph() -> RunGraph:
    g = RunGraph(run_id="r")
    g.batches = [
        Batch("Pre-0", "human gate", is_human_gate=True),
        Batch("A", "first", lanes=["core", "ui"], merge_order=["core", "ui"], cw_seams=["CW-4"]),
        Batch("Final", "final", lanes=["docs"], gate_commands=["make ci", "make mc-e2e"]),
    ]
    g.lanes = {
        "core": Lane("core", waves=[WaveNode("core:W0", "core", "p", "W0", "core")]),
        "ui": Lane(
            "ui",
            waves=[WaveNode("ui:W0", "ui", "p", "W0", "ui", docs_menu_sync=["make about-site"])],
        ),
        "docs": Lane("docs", waves=[WaveNode("docs:W0", "docs", "p", "W0", "docs")]),
    }
    return g


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def test_plan_human_gate_has_no_commit() -> None:
    plan = plan_integration(_graph(), run_id="r")
    pre0 = plan.batches[0]
    assert pre0.is_human_gate is True
    assert pre0.commit_subject is None
    assert pre0.merge_order == []


def test_plan_merge_order_and_docs_menu() -> None:
    plan = plan_integration(_graph(), run_id="r")
    batch_a = plan.batches[1]
    assert batch_a.merge_order == ["core", "ui"]
    assert batch_a.docs_menu_targets == ["make about-site"]
    assert batch_a.cw_seams == ["CW-4"]
    assert batch_a.commit_subject is not None
    assert batch_a.commit_subject.startswith("build(tripll): integrate batch A")


def test_plan_final_gate_commands() -> None:
    plan = plan_integration(_graph(), run_id="r")
    final = plan.batches[2]
    assert final.gate_commands == ["make ci", "make mc-e2e"]


def test_plan_integration_branch_off_base() -> None:
    plan = plan_integration(_graph(), run_id="r", base_ref="test-pre")
    assert plan.base_ref == "test-pre"
    assert plan.integration_branch == "tripll/integrate/r"


def test_render_dry_run_lines() -> None:
    lines = render_dry_run(plan_integration(_graph(), run_id="r"))
    text = "\n".join(lines)
    assert "HUMAN GATE" in text
    assert "tripll/integrate/r" in text
    assert "make ci" in text


# ---------------------------------------------------------------------------
# execution (fake repo + fake make)
# ---------------------------------------------------------------------------


class FakeRunner(CommandRunner):
    """Records git/make calls; fails make targets in *fail_targets*."""

    def __init__(self, fail_targets: set[str] | None = None) -> None:
        self.fail_targets = fail_targets or set()
        self.events: list[str] = []

    def create_branch(self, name: str, base: str) -> None:
        self.events.append(f"branch:{name}:{base}")

    def merge(self, lane_id: str) -> None:
        self.events.append(f"merge:{lane_id}")

    def run_make(self, target: str) -> bool:
        self.events.append(f"make:{target}")
        return target not in self.fail_targets

    def commit(self, subject: str) -> None:
        self.events.append(f"commit:{subject}")


def test_execute_merge_order_and_one_commit_per_batch() -> None:
    runner = FakeRunner()
    execute_integration(plan_integration(_graph(), run_id="r"), runner)
    # Branch created once.
    assert sum(e.startswith("branch:") for e in runner.events) == 1
    # Merge order respected within batch A.
    assert [e for e in runner.events if e.startswith("merge:")] == [
        "merge:core",
        "merge:ui",
        "merge:docs",
    ]
    # One commit per non-gate batch (A + Final = 2).
    commits = [e for e in runner.events if e.startswith("commit:")]
    assert len(commits) == 2


def test_execute_no_commit_during_pre0() -> None:
    runner = FakeRunner()
    execute_integration(plan_integration(_graph(), run_id="r"), runner)
    # No merge or commit happened before/for the Pre-0 gate.
    assert "merge:Pre-0" not in runner.events
    for e in runner.events:
        assert "Pre-0" not in e or e.startswith("branch:")


def test_execute_gate_failure_raises_and_skips_commit() -> None:
    runner = FakeRunner(fail_targets={"make ci"})
    with pytest.raises(IntegrationError):
        execute_integration(plan_integration(_graph(), run_id="r"), runner)
    # Batch A failed its gate → no commit for A.
    assert not [e for e in runner.events if e.startswith("commit:")]
