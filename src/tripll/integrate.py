"""tripll.integrate — optional autonomous per-batch integration (``--integrate``).

Default OFF. When enabled, after dispatch each non-gate batch is integrated on
a single integration branch off ``test-pre`` (configurable): lanes merge in the
batch merge order, CW seams serialise, per-plan Docs&Menu sync targets run, the
batch gate (``make ci`` + extras) runs, and — on green — **one Conventional
Commit** lands per batch. Pre-0 / review-gate batches never auto-commit.

The plan/render half is pure (no side effects) so ``--integrate --dry-run`` can
print the planned merges, gates, and commit subjects. Execution goes through a
:class:`CommandRunner` protocol so tests inject a fake repo + fake ``make``.

Exports:
    BatchIntegration — per-batch integration step (pure data).
    IntegrationPlan — full integration plan for a run.
    plan_integration — build an IntegrationPlan from a RunGraph.
    render_dry_run — format an IntegrationPlan as printable lines.
    CommandRunner — protocol for git/make side effects.
    GitMakeRunner — real git + make implementation.
    IntegrationError — raised when a batch gate fails.
    execute_integration — run an IntegrationPlan via a CommandRunner.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.graph import RunGraph

_DEFAULT_GATE = ["make ci"]


class IntegrationError(RuntimeError):
    """Raised when a batch gate command fails during integration."""


# ---------------------------------------------------------------------------
# Pure plan model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchIntegration:
    """Integration step for one batch.

    Args:
        batch_id (str): Batch id (``'Pre-0'`` | ``'A'`` … | ``'Final'``).
        label (str): Human-readable batch label.
        is_human_gate (bool): True for Pre-0 / review-gate batches (no commit).
        merge_order (list[str]): lane_ids to merge, in order.
        cw_seams (list[str]): CW ids that serialise within the batch.
        docs_menu_targets (list[str]): Docs&Menu sync make targets.
        gate_commands (list[str]): gate make targets (``make ci`` + extras).
        commit_subject (str | None): Conventional Commit subject, or None
            when the batch must not auto-commit.
    """

    batch_id: str
    label: str
    is_human_gate: bool
    merge_order: list[str] = field(default_factory=list)
    cw_seams: list[str] = field(default_factory=list)
    docs_menu_targets: list[str] = field(default_factory=list)
    gate_commands: list[str] = field(default_factory=list)
    commit_subject: str | None = None


@dataclass(frozen=True)
class IntegrationPlan:
    """Full integration plan for one run.

    Args:
        run_id (str): Run identifier.
        base_ref (str): Branch the integration branch is cut from.
        integration_branch (str): The single integration branch name.
        batches (list[BatchIntegration]): Ordered per-batch integration steps.
    """

    run_id: str
    base_ref: str
    integration_branch: str
    batches: list[BatchIntegration] = field(default_factory=list)


def _docs_menu_for_batch(graph: RunGraph, lane_ids: list[str]) -> list[str]:
    """Collect deduped, order-preserving Docs&Menu targets for a batch's lanes."""
    seen: list[str] = []
    for lane_id in lane_ids:
        lane = graph.lanes.get(lane_id)
        if lane is None:
            continue
        for wave in lane.waves:
            for target in wave.docs_menu_sync:
                if target not in seen:
                    seen.append(target)
    return seen


def plan_integration(
    graph: RunGraph, *, run_id: str, base_ref: str = "test-pre"
) -> IntegrationPlan:
    """Build an :class:`IntegrationPlan` from a parsed run graph.

    Args:
        graph (RunGraph): Parsed run graph.
        run_id (str): Run identifier.
        base_ref (str): Base branch for the integration branch.

    Returns:
        IntegrationPlan: One step per batch; human-gate batches carry no
        merges and no commit subject.

    Examples:
        >>> from tripll.graph import Batch, RunGraph
        >>> g = RunGraph(run_id="r", batches=[Batch("Pre-0", "gate", is_human_gate=True)])
        >>> plan_integration(g, run_id="r").batches[0].commit_subject is None
        True
    """
    steps: list[BatchIntegration] = []
    for batch in graph.batches:
        if batch.is_human_gate:
            steps.append(
                BatchIntegration(
                    batch_id=batch.batch_id,
                    label=batch.label,
                    is_human_gate=True,
                )
            )
            continue
        merge_order = batch.merge_order or batch.lanes
        gate = batch.gate_commands or _DEFAULT_GATE
        docs_menu = _docs_menu_for_batch(graph, merge_order)
        n = len(merge_order)
        subject = f"build(tripll): integrate batch {batch.batch_id} ({n} lane{'s' * (n != 1)})"
        steps.append(
            BatchIntegration(
                batch_id=batch.batch_id,
                label=batch.label,
                is_human_gate=False,
                merge_order=list(merge_order),
                cw_seams=list(batch.cw_seams),
                docs_menu_targets=docs_menu,
                gate_commands=list(gate),
                commit_subject=subject,
            )
        )
    return IntegrationPlan(
        run_id=run_id,
        base_ref=base_ref,
        integration_branch=f"tripll/integrate/{run_id}",
        batches=steps,
    )


def render_dry_run(plan: IntegrationPlan) -> list[str]:
    """Format an :class:`IntegrationPlan` as printable lines (no side effects).

    Args:
        plan (IntegrationPlan): The plan to render.

    Returns:
        list[str]: Lines describing the planned merges, gates, and commits.
    """
    lines = [
        f"[integrate] Branch  : {plan.integration_branch} (off {plan.base_ref})",
    ]
    for step in plan.batches:
        if step.is_human_gate:
            lines.append(f"[integrate] Batch {step.batch_id}: HUMAN GATE — no merge, no commit")
            continue
        lines.append(f"[integrate] Batch {step.batch_id}: {step.label}")
        lines.append(f"             merge   : {', '.join(step.merge_order) or '(none)'}")
        if step.cw_seams:
            lines.append(f"             cw-seam : {', '.join(step.cw_seams)}")
        if step.docs_menu_targets:
            lines.append(f"             docs    : {', '.join(step.docs_menu_targets)}")
        lines.append(f"             gate    : {', '.join(step.gate_commands)}")
        lines.append(f"             commit  : {step.commit_subject}")
    return lines


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class CommandRunner(Protocol):
    """Side-effecting operations needed to execute an integration plan."""

    def create_branch(self, name: str, base: str) -> None: ...

    def merge(self, lane_id: str) -> None: ...

    def run_make(self, target: str) -> bool: ...

    def commit(self, subject: str) -> None: ...


class GitMakeRunner:
    """Real :class:`CommandRunner` — git branches/merges + ``make`` gates.

    Args:
        repo_root (Path): Repository root.
        branch_for_lane (dict[str, str]): Maps a lane_id to its lane branch name.
    """

    def __init__(self, repo_root: Path, *, branch_for_lane: dict[str, str]) -> None:
        self.repo_root = repo_root
        self.branch_for_lane = branch_for_lane

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def _branch_exists(self, name: str) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(self.repo_root), "rev-parse", "--verify", f"refs/heads/{name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return proc.returncode == 0

    def _working_tree_dirty(self) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(self.repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return bool(proc.stdout.strip())

    def create_branch(self, name: str, base: str) -> None:
        if self._branch_exists(name):
            if self._working_tree_dirty():
                msg = (
                    f"integration branch `{name}` has a dirty working tree; "
                    "resolve or stash before re-running integrate"
                )
                raise IntegrationError(msg)
            self._git("checkout", name)
            return
        self._git("checkout", "-b", name, base)

    def merge(self, lane_id: str) -> None:
        branch = self.branch_for_lane.get(lane_id, lane_id)
        self._git("merge", "--no-ff", "--no-edit", branch)

    def run_make(self, target: str) -> bool:
        argv = target.split()
        proc = subprocess.run(
            argv, cwd=self.repo_root, capture_output=True, text=True, timeout=3600, check=False
        )
        return proc.returncode == 0

    def commit(self, subject: str) -> None:
        self._git("commit", "--allow-empty", "-m", subject)


def execute_integration(plan: IntegrationPlan, runner: CommandRunner) -> list[str]:
    """Execute an integration plan via *runner* (one commit per non-gate batch).

    Args:
        plan (IntegrationPlan): Plan to execute.
        runner (CommandRunner): Side-effect backend.

    Returns:
        list[str]: A human-readable log of actions taken.

    Raises:
        IntegrationError: When a batch gate (Docs&Menu or gate command) fails;
            no commit is made for that batch.
    """
    log: list[str] = []
    runner.create_branch(plan.integration_branch, plan.base_ref)
    log.append(f"branch {plan.integration_branch} off {plan.base_ref}")
    for step in plan.batches:
        if step.is_human_gate:
            log.append(f"batch {step.batch_id}: human gate — skipped (no commit)")
            continue
        for lane_id in step.merge_order:
            runner.merge(lane_id)
            log.append(f"batch {step.batch_id}: merged {lane_id}")
        for target in [*step.docs_menu_targets, *step.gate_commands]:
            if not runner.run_make(target):
                logger.error("integrate: batch {} gate failed on `{}`", step.batch_id, target)
                raise IntegrationError(f"batch {step.batch_id} gate failed: {target}")
        if step.commit_subject is not None:
            runner.commit(step.commit_subject)
            log.append(f"batch {step.batch_id}: committed `{step.commit_subject}`")
    return log
