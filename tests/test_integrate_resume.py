"""Integrate resume semantics — BUG-10 (W1.9, tier 2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.integrate import CommandRunner, execute_integration, plan_integration


def _minimal_graph() -> RunGraph:
    node = WaveNode("core:W0", "core", "p", "W0", "core")
    return RunGraph(
        run_id="integrate-r",
        batches=[Batch("A", "batch", lanes=["core"], merge_order=["core"])],
        lanes={"core": Lane("core", waves=[node])},
        nodes={"core:W0": node},
    )


class _RecordingRunner(CommandRunner):
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.create_branch_calls: list[tuple[str, str]] = []
        self.merge_calls: list[str] = []
        self._known_branches: set[str] = set()

    def create_branch(self, name: str, base: str) -> None:
        git = getattr(self, "_git", None)
        if git is not None:
            git("status", "--porcelain")
        if name in self._known_branches:
            return
        self.create_branch_calls.append((name, base))
        self._known_branches.add(name)

    def merge(self, lane_id: str) -> None:
        self.merge_calls.append(lane_id)

    def run_make(self, target: str) -> bool:
        return True

    def commit(self, subject: str) -> None:
        pass


@pytest.mark.tier2
def test_integrate_twice_preserves_lane_merges(tmp_path: Path) -> None:
    plan = plan_integration(_minimal_graph(), run_id="integrate-r", base_ref="main")
    runner = _RecordingRunner(tmp_path)
    execute_integration(plan, runner)
    first_merges = list(runner.merge_calls)
    execute_integration(plan, runner)
    assert runner.merge_calls[: len(first_merges)] == first_merges


@pytest.mark.tier2
def test_second_integrate_does_not_force_reset_branch(tmp_path: Path) -> None:
    plan = plan_integration(_minimal_graph(), run_id="integrate-r", base_ref="main")
    runner = _RecordingRunner(tmp_path)
    execute_integration(plan, runner)
    checkout_b_calls = [c for c in runner.create_branch_calls if c[0] == plan.integration_branch]
    execute_integration(plan, runner)
    second = [c for c in runner.create_branch_calls if c[0] == plan.integration_branch]
    assert len(second) <= len(checkout_b_calls) + 1


@pytest.mark.tier2
def test_dirty_integration_branch_detected_not_clobbered(tmp_path: Path) -> None:
    plan = plan_integration(_minimal_graph(), run_id="integrate-r", base_ref="main")
    runner = _RecordingRunner(tmp_path)
    runner._git = MagicMock(side_effect=RuntimeError("working tree dirty"))  # type: ignore[method-assign]
    with pytest.raises(Exception, match=r"dirty|working tree|fail"):
        execute_integration(plan, runner)
