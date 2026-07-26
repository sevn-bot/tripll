"""tripll.engine — DAG scheduler, retry/escalate, and Pre-0 human gate.

Drives a :class:`~tripll.graph.RunGraph` to completion under policy (D2, D7):

* Pre-0 is always a human gate — the engine writes a decisions sheet and stops
  until ``approve`` is called (no implementation dispatch before approval).
  After approval, waves listed in ``is_human_gate`` batches (e.g. W0) are marked
  ``done`` without agent dispatch; the first implementation wave (e.g. R1) runs
  in the next batch.
* Waves run batch-by-batch in graph order (so coordination batch A lands before
  dependent lanes); within a batch, dependency order is respected and disjoint
  nodes are dispatched **concurrently** via ``asyncio.gather`` under a bounded
  ``asyncio.Semaphore`` (``TRIPLL_MAX_PARALLEL``, default 3).
* Each wave is dispatched via an :class:`~tripll.adapters.base.AgentAdapter`,
  verified with its make targets inside an isolated worktree, and scope-checked
  against forbidden paths (D9).
* 2 retries with a corrected brief, then escalate (``blocked``) — no sham greens.
  Each attempt is checkpointed to the lane branch; retries never discard work.
* Ledger-mutating sequences are guarded by a single ``asyncio.Lock``
  (``_ledger_lock``) so concurrent ``_execute_node`` coroutines cannot interleave
  multi-statement logical transactions across ``await`` points.

**W2 cost/retry additions:**

* **Model defaults** — the default model is ``claude-sonnet-5`` (see
  :data:`~tripll.adapters.claude_code.DEFAULT_MODEL`).  No wave runs on opus
  silently; the wave's execution-graph row must declare it explicitly.
* **Smarter retries** — ``_execute_node`` distinguishes:
  - *Transient verify failure*: agent reported done, edits exist, but verify
    targets failed → kept by ``_verify_with_retries`` (verify-only retries,
    no second full dispatch for just a verify flap).
  - *No-progress / scope-permission failure*: the agent produced no edits to any
    owned path since dispatch (``changed_paths`` in the worktree is empty for
    owned paths) → counts as a "no-progress dispatch"; capped at
    :data:`_MAX_NO_PROGRESS_DISPATCHES` (1) so we don't burn all 3 slots on a
    node that provably cannot touch its paths.  Escalates with a clear reason.
* **Runaway guard** — ``run_streaming`` optionally enforces per-attempt ceilings
  on output tokens (``TRIPLL_MAX_OUTPUT_TOKENS``) and tool-use count
  (``TRIPLL_MAX_TOOL_USES``); see :mod:`tripll.adapters.base`.

Worktree allocation and verification are injected (``WorktreeManager`` /
``Verifier``) so the engine is testable with fakes and runnable for real.

Exports:
    NodeResult — terminal outcome for one wave node.
    RunResult — terminal outcome for a whole run.
    WorktreeManager — protocol for worktree allocation/checkpoint/cleanup/scope checks.
    Verifier — protocol for running verify targets.
    GitWorktreeManager — real git-backed worktree manager.
    MakeVerifier — real ``make`` verifier.
    SingleBranchWorktreeManager — reuse one integration worktree on the feature branch.
    ready_nodes — pure ready-wave selection (deps satisfied).
    can_run_concurrently — pure concurrency-gate predicate (D5/W5.2).
    select_concurrent_set — greedy maximal pairwise-disjoint selection from ready nodes.
    human_gate_node_ids — node ids in human-gate batches.
    nodes_for_batch — wave nodes belonging to one batch.
    complete_human_gate_waves — mark human-gate waves done after Pre-0 approve.
    orchestrator_serial_nodes — order nodes for orchestrator serial execution.
    Engine — the orchestration engine.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from tripll.adapters.pools import ProviderPoolRegistry, pools_from_plan
from tripll.adapters.quota import quota_message
from tripll.brief import (
    enrich_brief_with_graph_pack,
    extract_wave_summary,
    render_json_brief,
    write_brief,
)
from tripll.git_commit import commit_and_push_wave
from tripll.graph import CW_HOTSPOTS, Batch, OrchestratorConfig, RunGraph, WaveNode, paths_overlap
from tripll.harness.boundary import (
    assert_verify_isolation,
    build_verify_dispatch,
    materialize_verify_worktree,
    remove_verify_worktree,
)
from tripll.harness.fingerprint import (
    capture_env_fingerprint,
    fingerprint_hash,
    fingerprint_to_json,
)
from tripll.hitl import GateKind, write_form_for_run
from tripll.ledger import (
    ORCHESTRATOR_NODE_ID,
    LedgerConnection,
    append_event,
    end_attempt,
    get_run_cost,
    get_wave,
    insert_attempt,
    insert_run,
    insert_wave,
    list_waves,
    open_ledger,
    transition_run,
    transition_wave,
    void_infra_attempt_count,
)
from tripll.orchestrator_status import (
    OrchestratorTurn,
    StatusRow,
    sync_orchestrator_status,
)
from tripll.parse import build_graph_from_dir
from tripll.report import sync_report, write_report
from tripll.worktrees import (
    Worktree,
    WorktreeError,
    allocate_feature_branch_worktree,
    allocate_worktree,
    changed_paths,
    checkpoint_message,
    checkpoint_worktree,
    cleanup_worktree,
    detect_scope_breach,
    recover_worktree,
    revert_breach,
    stage_dispatch_context,
    staged_wave_plan_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from tripll.adapters.base import AgentAdapter, DispatchResult
    from tripll.ledger import AttemptOutcome, RunState
    from tripll.pipeline import RunsRoot

# Late-coordination hotspots that must serialise within a phase (CW-4/CW-5).
_LATE_CW_PATHS: frozenset[str] = frozenset(CW_HOTSPOTS["CW-4"] + CW_HOTSPOTS["CW-5"])


def human_gate_node_ids(graph: RunGraph) -> set[str]:
    """Return node ids for waves in human-gate batches (Pre-0 / review gate only).

    Args:
        graph (RunGraph): Parsed execution graph.

    Returns:
        set[str]: Node ids that are human gates (no agent dispatch).

    Examples:
        >>> from tripll.graph import Batch, Lane, RunGraph, WaveNode
        >>> n = WaveNode("l:W0", "l", "p.md", "W0", "lane")
        >>> g = RunGraph(
        ...     run_id="r", nodes={"l:W0": n},
        ...     lanes={"l": Lane("l", "lane", [n])},
        ...     batches=[Batch("pre0", ["l"], is_human_gate=True, wave_ids=["W0"])],
        ... )
        >>> human_gate_node_ids(g)
        {'l:W0'}
    """
    ids: set[str] = set()
    for batch in graph.batches:
        if not batch.is_human_gate or not batch.wave_ids:
            continue
        for lane_id in batch.lanes:
            for wave_id in batch.wave_ids:
                node_id = f"{lane_id}:{wave_id}"
                if node_id in graph.nodes:
                    ids.add(node_id)
    return ids


def nodes_for_batch(graph: RunGraph, batch: Batch) -> list[WaveNode]:
    """Return wave nodes belonging to *batch* (respects ``batch.wave_ids`` when set).

    Args:
        graph (RunGraph): Parsed execution graph.
        batch (Batch): One batch row from the graph.

    Returns:
        list[WaveNode]: Nodes in *batch* lanes (filtered by ``wave_ids`` when set).

    Examples:
        >>> from tripll.graph import Batch, Lane, RunGraph, WaveNode
        >>> n = WaveNode("l:W1", "l", "p.md", "W1", "lane")
        >>> g = RunGraph(
        ...     run_id="r", nodes={"l:W1": n},
        ...     lanes={"l": Lane("l", "lane", [n])},
        ...     batches=[Batch("a", ["l"], wave_ids=["W1"])],
        ... )
        >>> [x.wave_id for x in nodes_for_batch(g, g.batches[0])]
        ['W1']
    """
    out: list[WaveNode] = []
    for lane_id in batch.lanes:
        lane = graph.lanes.get(lane_id)
        if lane is None:
            continue
        for wave in lane.waves:
            if wave.node_id not in graph.nodes:
                continue
            if batch.wave_ids and wave.wave_id not in batch.wave_ids:
                continue
            out.append(graph.nodes[wave.node_id])
    return out


def complete_human_gate_waves(
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    *,
    done: set[str],
    blocked: list[str],
    results: dict[str, NodeResult],
) -> None:
    """Mark human-gate batch waves done without agent dispatch (after Pre-0 approve).

    Args:
        lc (LedgerConnection): Open run ledger.
        run_id (str): Run identifier.
        graph (RunGraph): Parsed execution graph.
        done (set[str]): Mutable set of completed node ids (updated in place).
        blocked (list[str]): Mutable list of blocked node ids (may be cleared).
        results (dict[str, NodeResult]): Mutable per-node results (updated in place).

    Examples:
        >>> complete_human_gate_waves.__name__
        'complete_human_gate_waves'
    """
    for node_id in sorted(human_gate_node_ids(graph)):
        if node_id in done:
            continue
        row = get_wave(lc, run_id, node_id)
        if row.state == "blocked":
            transition_wave(lc, run_id, node_id, "queued")
            row = get_wave(lc, run_id, node_id)
        if row.state != "done":
            transition_wave(lc, run_id, node_id, "done")
        done.add(node_id)
        if node_id in blocked:
            blocked.remove(node_id)
        results[node_id] = NodeResult(
            node_id,
            "done",
            row.attempt_count,
            "human gate — operator decisions only (no agent dispatch)",
        )
        append_event(
            lc,
            run_id=run_id,
            node_id=node_id,
            phase="done",
            last_action="human gate cleared (Pre-0 approved)",
        )
        logger.info("engine: {} node {} — human gate auto-completed (no dispatch)", run_id, node_id)


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Terminal outcome for one wave node.

    Args:
        node_id (str): The wave node id.
        state (str): ``'done'`` or ``'blocked'``.
        attempts (int): Number of dispatch attempts made.
        evidence (str): Last failure evidence (empty when done).
    """

    node_id: str
    state: str
    attempts: int
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class RunResult:
    """Terminal (or paused) outcome for a whole run.

    Args:
        run_id (str): Run identifier.
        state (str): ``'paused'`` | ``'done'`` | ``'failed'``.
        nodes (dict[str, NodeResult]): Per-node outcomes.
        pre0_pending (bool): True when stopped at the Pre-0 human gate.
        hitl_pending (bool): True when stopped at any HITL gate (Pre-0 or review).
        hitl_gate_kind (str | None): ``pre0`` or ``review_gate`` when *hitl_pending*.
        quota_pending (bool): True when paused due to provider quota/session limit.
        cost_pending (bool): True when paused due to cost budget exhaustion.
    """

    run_id: str
    state: str
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    pre0_pending: bool = False
    hitl_pending: bool = False
    hitl_gate_kind: str | None = None
    quota_pending: bool = False
    cost_pending: bool = False


# ---------------------------------------------------------------------------
# Pure scheduling helpers (W5.1 / W5.2)
# ---------------------------------------------------------------------------


def ready_nodes(nodes: Iterable[WaveNode], done: set[str]) -> list[WaveNode]:
    """Return nodes whose dependencies are all satisfied and not yet done.

    Args:
        nodes (Iterable[WaveNode]): Candidate nodes.
        done (set[str]): node_ids already completed.

    Returns:
        list[WaveNode]: Nodes ready to dispatch.

    Examples:
        >>> from tripll.graph import WaveNode
        >>> a = WaveNode("a", "a", "p", "W0", "a")
        >>> b = WaveNode("b", "b", "p", "W1", "b", depends_on=["a"])
        >>> [n.node_id for n in ready_nodes([a, b], set())]
        ['a']
    """
    out: list[WaveNode] = []
    for node in nodes:
        if node.node_id in done:
            continue
        if all(dep in done for dep in node.depends_on):
            out.append(node)
    return out


def _touches_late_cw(node: WaveNode) -> bool:
    """Return True when *node* owns a CW-4/CW-5 hotspot path.

    Args:
        node (WaveNode): Candidate wave node.

    Returns:
        bool: True when owned paths overlap late coordination hotspots.

    Examples:
        >>> from tripll.graph import WaveNode
        >>> n = WaveNode("a", "a", "p", "W0", "a", owned_paths=["infra/sevn.schema.json"])
        >>> _touches_late_cw(n)
        True
    """
    for owned in node.owned_paths:
        o = owned.rstrip("/")
        for cw in _LATE_CW_PATHS:
            c = cw.rstrip("/")
            if o == c or o.startswith(c + "/") or c.startswith(o + "/"):
                return True
    return False


def can_run_concurrently(a: WaveNode, b: WaveNode) -> bool:
    """Return True when two nodes may run in parallel within a phase (W5.2).

    Parallel only when owned paths are disjoint **and** the two do not both
    touch CW-4/CW-5 hotspots in the same phase.

    Args:
        a (WaveNode): First node.
        b (WaveNode): Second node.

    Returns:
        bool: True if the pair may run concurrently.

    Examples:
        >>> from tripll.graph import WaveNode
        >>> a = WaveNode("a", "a", "p", "W0", "a", owned_paths=["src/sevn/a/"])
        >>> b = WaveNode("b", "b", "p", "W0", "b", owned_paths=["src/sevn/b/"])
        >>> can_run_concurrently(a, b)
        True
    """
    if paths_overlap(a.owned_paths, b.owned_paths):
        return False
    return not (_touches_late_cw(a) and _touches_late_cw(b))


def select_concurrent_set(candidates: list[WaveNode]) -> list[WaveNode]:
    """Greedily select a maximal pairwise-disjoint subset from *candidates*.

    Iterates *candidates* in order and adds each node to the running set
    only if it is ``can_run_concurrently`` with every node already selected.
    Nodes that fail the pairwise check are skipped for this round; they will
    be reconsidered after the selected nodes finish.

    Args:
        candidates (list[WaveNode]): Ready nodes to choose from.

    Returns:
        list[WaveNode]: The largest prefix-consistent concurrent set.

    Examples:
        >>> from tripll.graph import WaveNode
        >>> a = WaveNode("a", "a", "p", "W0", "a", owned_paths=["src/a/"])
        >>> b = WaveNode("b", "b", "p", "W0", "b", owned_paths=["src/b/"])
        >>> c = WaveNode("c", "c", "p", "W0", "c", owned_paths=["src/a/x.py"])
        >>> [n.node_id for n in select_concurrent_set([a, b, c])]
        ['a', 'b']
    """
    selected: list[WaveNode] = []
    for node in candidates:
        if all(can_run_concurrently(node, s) for s in selected):
            selected.append(node)
    return selected


# ---------------------------------------------------------------------------
# Worktree / verify injection points
# ---------------------------------------------------------------------------


class WorktreeManager(Protocol):
    """Protocol for worktree allocation, checkpoint, cleanup, and scope checks."""

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        """Allocate (or reuse) a worktree for a lane-wave.

        Args:
            run_id (str): Run identifier.
            lane_id (str): Lane id.
            wave_id (str): Wave id.

        Returns:
            Worktree: Allocated worktree handle.

        Examples:
            >>> WorktreeManager.allocate.__name__
            'allocate'
        """
        ...

    def checkpoint(
        self,
        worktree: Worktree,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
    ) -> str | None:
        """Commit all worktree changes for *attempt*; return commit SHA or None.

        Args:
            worktree (Worktree): Lane worktree.
            run_id (str): Run identifier.
            node_id (str): Wave node id.
            attempt (int): Attempt number (1-based).

        Returns:
            str | None: Commit SHA when changes were committed.

        Examples:
            >>> WorktreeManager.checkpoint.__name__
            'checkpoint'
        """
        ...

    def recover(self, worktree: Worktree, *, run_id: str, node_id: str) -> str | None:
        """Commit orphaned work in *worktree* after a crash.

        Args:
            worktree (Worktree): Lane worktree.
            run_id (str): Run identifier.
            node_id (str): Wave node id.

        Returns:
            str | None: Commit SHA when recovery committed changes.

        Examples:
            >>> WorktreeManager.recover.__name__
            'recover'
        """
        ...

    def cleanup(self, worktree: Worktree) -> None:
        """Remove the worktree after a successful wave.

        Args:
            worktree (Worktree): Lane worktree to remove.

        Examples:
            >>> WorktreeManager.cleanup.__name__
            'cleanup'
        """
        ...

    def scope_breach(
        self,
        worktree: Worktree,
        forbidden: list[str],
        *,
        owned_paths: list[str] | None = None,
    ) -> list[str]:
        """Return changed paths under any forbidden path.

        Args:
            worktree (Worktree): Lane worktree.
            forbidden (list[str]): Paths the wave may not edit.
            owned_paths (list[str] | None): Optional owned-path hint for detection.

        Returns:
            list[str]: Repo-relative breached paths (empty when clean).

        Examples:
            >>> WorktreeManager.scope_breach.__name__
            'scope_breach'
        """
        ...

    def revert(self, worktree: Worktree, files: list[str]) -> None:
        """Revert breached files in *worktree*.

        Args:
            worktree (Worktree): Lane worktree.
            files (list[str]): Repo-relative paths to revert.

        Examples:
            >>> WorktreeManager.revert.__name__
            'revert'
        """
        ...


class Verifier(Protocol):
    """Protocol for running a node's verify targets."""

    def verify(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        """Run *targets* in *worktree_path*; return ``(ok, evidence)``.

        Args:
            worktree_path (Path): Lane worktree root.
            targets (list[str]): Makefile targets (e.g. ``make lint``).

        Returns:
            tuple[bool, str]: Success flag and evidence string.

        Examples:
            >>> Verifier.verify.__name__
            'verify'
        """
        ...


class GitWorktreeManager:
    """Real git-backed worktree manager (production path).

    Args:
        repo_root (Path): The sevn.bot checkout.
        runs_root (RunsRoot): Runs root (for per-run worktree dirs).
        base_ref (str): Git ref to branch from.
    """

    def __init__(self, repo_root: Path, runs_root: RunsRoot, *, base_ref: str = "HEAD") -> None:
        """Store repo and runs-root paths for worktree allocation."""
        self.repo_root = repo_root
        self.runs_root = runs_root
        self.base_ref = base_ref

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        """Allocate a git worktree for *lane_id*:*wave_id* under the run."""
        return allocate_worktree(
            self.repo_root,
            self.runs_root.worktrees_dir(run_id),
            run_id=run_id,
            lane_id=lane_id,
            wave_id=wave_id,
            base_ref=self.base_ref,
        )

    def checkpoint(
        self,
        worktree: Worktree,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
    ) -> str | None:
        """Checkpoint *worktree* changes for attempt *attempt*."""
        msg = checkpoint_message(run_id=run_id, node_id=node_id, attempt=attempt)
        return checkpoint_worktree(worktree.path, message=msg)

    def recover(self, worktree: Worktree, *, run_id: str, node_id: str) -> str | None:
        """Recover orphaned work in *worktree* after a crash."""
        return recover_worktree(worktree.path, run_id=run_id, node_id=node_id)

    def cleanup(self, worktree: Worktree) -> None:
        """Remove *worktree* from disk and prune the git worktree entry."""
        cleanup_worktree(self.repo_root, worktree)

    def scope_breach(
        self,
        worktree: Worktree,
        forbidden: list[str],
        *,
        owned_paths: list[str] | None = None,
    ) -> list[str]:
        """Detect forbidden-path edits in *worktree*."""
        return detect_scope_breach(worktree.path, forbidden, owned_paths=owned_paths)

    def revert(self, worktree: Worktree, files: list[str]) -> None:
        """Revert *files* in *worktree* after a scope breach."""
        revert_breach(worktree.path, files)


class MakeVerifier:
    """Real verifier that runs each make target inside the worktree.

    Uses the main checkout toolchain (``UV_PROJECT``) so worktrees do not build a
    stale local ``.venv``. ``typecheck`` is scoped to ``src/sevn`` files changed
    on the lane branch (not full-repo ``mypy``).

    Args:
        repo_root (Path): sevn.bot checkout (toolchain + ``UV_PROJECT`` target).
        timeout_s (int): Per-target subprocess timeout.
    """

    def __init__(self, *, repo_root: Path, timeout_s: int = 1800) -> None:
        """Store toolchain root and per-target timeout."""
        self.repo_root = repo_root.resolve()
        self.timeout_s = timeout_s

    def _toolchain_env(self) -> dict[str, str]:
        """Return subprocess env with ``UV_PROJECT`` pointed at the main checkout."""
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_PROJECT"] = str(self.repo_root)
        return env

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Run *argv* in *cwd* with *env* and capture output."""
        return subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=self.timeout_s,
            env=env,
        )

    def _merge_base(self, worktree_path: Path, env: dict[str, str]) -> str:
        """Return a merge-base ref for diffing ``src/sevn`` changes on the lane branch."""
        refs: list[str] = []
        sym = self._run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=worktree_path,
            env=env,
        )
        if sym.returncode == 0 and sym.stdout.strip():
            refs.append(sym.stdout.strip().removeprefix("origin/"))
        refs.extend(["main", "master", "test-pre"])
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            proc = self._run(
                ["git", "merge-base", "HEAD", ref],
                cwd=worktree_path,
                env=env,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        return "HEAD~1"

    def _changed_src_sevn(self, worktree_path: Path, env: dict[str, str]) -> list[str]:
        """List changed or untracked ``src/sevn`` Python files on the lane branch."""
        base = self._merge_base(worktree_path, env)
        proc = self._run(
            ["git", "diff", "--name-only", base, "--", "src/sevn"],
            cwd=worktree_path,
            env=env,
        )
        if proc.returncode != 0:
            return []
        paths = {line.strip() for line in proc.stdout.splitlines() if line.strip().endswith(".py")}
        untracked = self._run(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                "src/sevn",
            ],
            cwd=worktree_path,
            env=env,
        )
        if untracked.returncode == 0:
            paths.update(
                line.strip()
                for line in untracked.stdout.splitlines()
                if line.strip().endswith(".py")
            )
        return sorted(paths)

    def _verify_typecheck(self, worktree_path: Path, env: dict[str, str]) -> tuple[bool, str]:
        """Run scoped ``mypy`` on changed ``src/sevn`` files only."""
        files = self._changed_src_sevn(worktree_path, env)
        if not files:
            return True, "typecheck skipped (no src/sevn changes on branch)"
        uv = shutil.which("uv") or "uv"
        proc = self._run(
            [uv, "run", "mypy", *files],
            cwd=worktree_path,
            env=env,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "")[-1000:]
            return False, f"make typecheck failed: {detail}"
        return True, f"typecheck ok ({len(files)} files)"

    def verify(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        """Run each make target in *worktree_path*; return ``(ok, evidence)``."""
        make = shutil.which("make") or "make"
        env = self._toolchain_env()
        for target in targets:
            tgt = target.removeprefix("make ").strip()
            try:
                if tgt == "typecheck":
                    ok, ev = self._verify_typecheck(worktree_path, env)
                    if not ok:
                        return False, ev
                    continue
                proc = self._run([make, tgt], cwd=worktree_path, env=env)
            except subprocess.TimeoutExpired:
                return False, f"{target} timed out after {self.timeout_s}s"
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "")[-1000:]
                return False, f"{target} failed: {detail}"
        return True, "all verify targets passed"


class SingleBranchWorktreeManager(GitWorktreeManager):
    """Reuse one integration worktree on the orchestrator feature branch (D8)."""

    def __init__(
        self,
        repo_root: Path,
        runs_root: RunsRoot,
        *,
        feature_branch: str,
        base_ref: str = "HEAD",
    ) -> None:
        """Store *feature_branch* for single-worktree orchestrator mode."""
        super().__init__(repo_root, runs_root, base_ref=base_ref)
        self.feature_branch = feature_branch
        self._shared: Worktree | None = None

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        """Reuse the shared integration worktree when already allocated."""
        if self._shared is not None:
            return Worktree(
                path=self._shared.path,
                branch=self._shared.branch,
                lane_id=lane_id,
                wave_id=wave_id,
            )
        path = self.runs_root.worktrees_dir(run_id) / "integration"
        wt = allocate_feature_branch_worktree(
            self.repo_root,
            path,
            branch=self.feature_branch,
            base_ref=self.base_ref,
        )
        self._shared = wt
        return Worktree(path=wt.path, branch=wt.branch, lane_id=lane_id, wave_id=wave_id)

    def cleanup(self, worktree: Worktree) -> None:
        """No-op — integration worktree persists across orchestrator waves."""
        return None


def _topological_sort_nodes(graph: RunGraph) -> list[WaveNode]:
    """Return *graph* nodes in dependency order (best-effort when cycles exist)."""
    nodes = list(graph.nodes.values())
    done: set[str] = set()
    ordered: list[WaveNode] = []
    while len(ordered) < len(nodes):
        progressed = False
        for node in nodes:
            if node.node_id in done:
                continue
            if all(dep in done for dep in node.depends_on):
                ordered.append(node)
                done.add(node.node_id)
                progressed = True
        if not progressed:
            break
    return ordered


def orchestrator_serial_nodes(graph: RunGraph) -> list[WaveNode]:
    """Order nodes for orchestrator serial execution (W2.1).

    Args:
        graph (RunGraph): Parsed execution graph.

    Returns:
        list[WaveNode]: Nodes ordered by ``orchestrator.serial_waves`` then topo sort.

    Examples:
        >>> orchestrator_serial_nodes.__name__
        'orchestrator_serial_nodes'
    """
    cfg = graph.orchestrator
    if cfg is None:
        return _topological_sort_nodes(graph)
    by_wave: dict[str, list[WaveNode]] = {}
    for node in graph.nodes.values():
        by_wave.setdefault(node.wave_id, []).append(node)
    ordered: list[WaveNode] = []
    for wid in cfg.serial_waves:
        ordered.extend(by_wave.get(wid, []))
    seen = {n.node_id for n in ordered}
    for node in _topological_sort_nodes(graph):
        if node.node_id not in seen:
            ordered.append(node)
    return ordered


def _initial_orchestrator_rows(cfg: OrchestratorConfig) -> list[StatusRow]:
    """Build initial orchestrator status rows for each serial wave."""
    branch = cfg.feature_branch or "—"
    return [StatusRow(w, branch=branch) for w in cfg.serial_waves]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_PRE0_MARKER = "pre0-approved"
_QUOTA_MARKER = "quota-paused.md"
_COST_MARKER = "cost-budget-paused.md"
_PAUSE_MARKER = "pause-requested.md"
_REVIEW_GATE_MARKER = "review-gate-pending.md"
_REVIEW_GATE_APPROVED = "review-gate-approved"
_VERIFY_ONLY_RETRIES = 2


def _orchestrator_agent_enabled() -> bool:
    """Return True when headless wave-orchestrator gate dispatch is enabled (W4.4).

    Returns:
        bool: True when ``TRIPLL_ORCHESTRATOR_AGENT`` is truthy.

    Examples:
        >>> isinstance(_orchestrator_agent_enabled(), bool)
        True
    """
    return os.environ.get("TRIPLL_ORCHESTRATOR_AGENT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


#: Maximum full re-dispatches when the agent made **no progress** (no edits to
#: owned paths since dispatch).  Capped to 1 so we don't burn all 3 attempts on
#: a node that cannot touch its assigned paths (scope-permission failure, wrong
#: worktree, misconfigured brief, etc.).  A second no-progress dispatch would
#: almost certainly fail for the same reason; we escalate with a clear message.
_MAX_NO_PROGRESS_DISPATCHES = 1

_DEFAULT_MAX_PARALLEL = 3


def _max_parallel_from_env() -> int:
    """Read ``TRIPLL_MAX_PARALLEL`` from the environment (default 3).

    Returns:
        int: Maximum number of nodes to run concurrently within a batch.

    Examples:
        >>> isinstance(_max_parallel_from_env(), int)
        True
    """
    try:
        v = int(os.environ.get("TRIPLL_MAX_PARALLEL", _DEFAULT_MAX_PARALLEL))
        return max(1, v)
    except (ValueError, TypeError):
        return _DEFAULT_MAX_PARALLEL


class Engine:
    """Orchestration engine that drives a run graph under policy.

    Within each batch the engine runs eligible nodes **concurrently**: it
    repeatedly selects the maximal pairwise-disjoint ``ready_nodes`` subset,
    dispatches them with ``asyncio.gather`` under a ``Semaphore(max_parallel)``,
    then recomputes readiness until the batch drains.  If no node becomes ready
    while undrained nodes remain the batch has a dependency deadlock; the engine
    escalates those nodes as blocked rather than dispatching them blindly.

    All ledger-mutating sequences are guarded by ``_ledger_lock`` (a single
    ``asyncio.Lock``) so concurrent coroutines cannot interleave multi-statement
    logical transactions across ``await`` points.

    Args:
        adapter (AgentAdapter): Backend used to dispatch waves.
        runs_root (RunsRoot): Configured runs root.
        repo_root (Path): The sevn.bot checkout.
        worktree_manager (WorktreeManager | None): Override (default git-backed).
        verifier (Verifier | None): Override (default ``make`` verifier).
        max_attempts (int): Attempts before escalation (tests-first model → 5).
        cost_budget_usd (float): Pause when run cost reaches this USD total (0 = unlimited).
        max_parallel (int | None): Max concurrent nodes per batch.  Defaults to
            ``TRIPLL_MAX_PARALLEL`` env (default 3).

    Examples:
        >>> Engine.__name__
        'Engine'
    """

    def __init__(
        self,
        *,
        adapter: AgentAdapter,
        runs_root: RunsRoot,
        repo_root: Path,
        worktree_manager: WorktreeManager | None = None,
        verifier: Verifier | None = None,
        max_attempts: int = 5,
        cost_budget_usd: float = 0.0,
        max_parallel: int | None = None,
        role_dispatch: bool | None = None,
        grep_brief: bool = False,
    ) -> None:
        """Initialize engine state from constructor arguments."""
        self.adapter = adapter
        self.runs_root = runs_root
        self.repo_root = repo_root
        self.wtm: WorktreeManager = worktree_manager or GitWorktreeManager(repo_root, runs_root)
        self.verifier: Verifier = verifier or MakeVerifier(repo_root=repo_root)
        self.max_attempts = max_attempts
        self.cost_budget_usd = max(0.0, cost_budget_usd)
        self._max_parallel: int = (
            max_parallel if max_parallel is not None else _max_parallel_from_env()
        )
        self._role_dispatch_cli: bool | None = role_dispatch
        self._role_dispatch_effective: bool = False
        self._grep_brief = grep_brief
        self._ledger_lock: asyncio.Lock = asyncio.Lock()
        self._pools: ProviderPoolRegistry | None = None
        self._default_provider: str = "claude_code"
        self._orchestrator_mode: bool = False
        self._orchestrator_single_branch: bool = False
        self._wave_commit_shas: dict[str, str] = {}
        self._orchestrator_rows: list[StatusRow] = []
        self._orchestrator_turns: list[OrchestratorTurn] = []
        self._last_dispatch_result_text: str = ""
        self._last_worktree_path: Path | None = None
        self._last_checkpoint_sha: str = ""

    # -- public API ---------------------------------------------------------

    async def start(self, input_path: Path) -> RunResult:
        """Claim *input_path*, build + seed the graph, and drive the run.

        Args:
            input_path (Path): Input directory (Mode A set or plain folder).

        Returns:
            RunResult: ``paused`` at Pre-0, or terminal ``done``/``failed``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Engine.start)
            True
        """
        self.runs_root.init()
        run_id = self.runs_root.claim_input(input_path)
        run_dir = self.runs_root.run_dir(run_id)
        from tripll.run_dispatch import write_dispatch_config

        adapter_model = getattr(self.adapter, "model", None)
        adapter_agent = getattr(self.adapter, "agent", None)
        write_dispatch_config(
            run_dir,
            backend=self.adapter.name,
            model=adapter_model,
            agent=adapter_agent,
            role_dispatch=self._role_dispatch_cli,
        )
        graph = build_graph_from_dir(run_dir, run_id=run_id)
        self._init_provider_fabric(graph)
        self.runs_root.briefs_dir(run_id).mkdir(parents=True, exist_ok=True)
        self.runs_root.logs_dir(run_id).mkdir(parents=True, exist_ok=True)

        import json

        self.runs_root.graph_path(run_id).write_text(json.dumps(graph.to_dict(), indent=2))

        from tripll.graphstore.task_sync import TaskGraphWriter

        task_writer = TaskGraphWriter(self.runs_root.graph_db_path(run_id))
        try:
            task_writer.sync_run_start(
                run_id=run_id,
                graph=graph,
                backend=self.adapter.name,
                model=adapter_model,
                agent=adapter_agent,
            )
        finally:
            task_writer.close()

        with open_ledger(self.runs_root.ledger_path(run_id)) as lc:
            insert_run(
                lc,
                run_id=run_id,
                slug=run_id.rsplit("-", 2)[0],
                source_mode=graph.source_mode,
                input_path=str(run_dir),
            )
            for node in graph.nodes.values():
                insert_wave(
                    lc,
                    node_id=node.node_id,
                    run_id=run_id,
                    plan_id=node.plan_id,
                    wave_id=node.wave_id,
                    lane=node.lane,
                    initial_state="queued",
                )
        return await self._drive(run_id, graph)

    def approve(self, run_id: str) -> None:
        """Approve the pending HITL gate for *run_id*.

        When ``hitl-form.json`` exists, requires complete ``hitl-responses.json``.
        Legacy runs without a form still write ``pre0-approved`` only.

        Args:
            run_id (str): Run to approve.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Engine.approve)
            True
        """
        from tripll import hitl

        run_dir = self.runs_root.run_dir(run_id)
        if hitl.load_form(run_dir) is not None:
            kind = hitl.approve_gate(run_dir, run_id=run_id)
            logger.info("engine: HITL gate approved ({}) for {}", kind.value, run_id)
            return
        pending = hitl.detect_pending_gate(run_dir)
        if pending is not None and pending.kind == GateKind.REVIEW_GATE:
            (run_dir / _REVIEW_GATE_APPROVED).write_text(f"{pending.wave_id or 'gate'}\n")
            (run_dir / _REVIEW_GATE_MARKER).unlink(missing_ok=True)
            logger.info("engine: review gate approved for {}", run_id)
            return
        (run_dir / _PRE0_MARKER).write_text("approved\n")
        logger.info("engine: Pre-0 approved for {}", run_id)

    async def resume(self, run_id: str) -> RunResult:
        """Resume a run from its on-disk state (rebuild graph + drive).

        Args:
            run_id (str): Run to resume.

        Returns:
            RunResult: Terminal or paused outcome.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Engine.resume)
            True
        """
        run_dir = self.runs_root.run_dir(run_id)
        graph = build_graph_from_dir(run_dir, run_id=run_id)
        self._init_provider_fabric(graph)
        return await self._drive(run_id, graph)

    # -- internals ----------------------------------------------------------

    def _plan_role_dispatch(self, graph: RunGraph) -> bool:
        """Return plan-level role-dispatch from graph or orchestrator config.

        Args:
            graph (RunGraph): Parsed execution graph.

        Returns:
            bool: True when plan or orchestrator config enables role dispatch.

        Examples:
            >>> _plan_role_dispatch.__name__
            '_plan_role_dispatch'
        """
        if graph.role_dispatch:
            return True
        cfg = graph.orchestrator
        return bool(cfg and cfg.role_dispatch)

    def _resolve_role_dispatch(self, graph: RunGraph) -> bool:
        """Resolve effective role-dispatch (CLI > env > plan > orchestrator-implied).

        Args:
            graph (RunGraph): Parsed execution graph.

        Returns:
            bool: Whether per-role agent injection is active.

        Examples:
            >>> _resolve_role_dispatch.__name__
            '_resolve_role_dispatch'
        """
        from tripll.adapters.options import resolve_role_dispatch, role_dispatch_from_env

        cfg = graph.orchestrator
        return resolve_role_dispatch(
            cli=self._role_dispatch_cli,
            env=role_dispatch_from_env(),
            plan_config=self._plan_role_dispatch(graph),
            orchestrator_enabled=bool(cfg and cfg.enabled),
        )

    def _is_approved(self, run_id: str) -> bool:
        """Return True when Pre-0 approval marker exists for *run_id*."""
        return (self.runs_root.run_dir(run_id) / _PRE0_MARKER).exists()

    def _pause_requested(self, run_id: str) -> bool:
        """Return True when an API-written pause marker exists for *run_id*.

        Args:
            run_id (str): Run identifier.

        Returns:
            bool: True when ``pause-requested.md`` is present.

        Examples:
            >>> Engine._pause_requested.__name__
            'pause_requested'
        """
        return (self.runs_root.run_dir(run_id) / _PAUSE_MARKER).exists()

    def _sync_report(
        self,
        run_id: str,
        graph: RunGraph,
        *,
        current_node_id: str | None = None,
        partial_results: dict[str, NodeResult] | None = None,
    ) -> None:
        """Refresh ``report.md`` for *run_id* from ledger and partial results."""
        sync_report(
            self.runs_root.run_dir(run_id),
            graph,
            self.runs_root.ledger_path(run_id),
            run_id=run_id,
            current_node_id=current_node_id,
            partial_results=partial_results,
            pre0_approved=self._is_approved(run_id),
        )

    def _write_pre0_sheet(self, run_id: str, graph: RunGraph) -> None:
        """Write ``pre0-decisions.md`` checklist for operator Pre-0 approval."""
        lines = [f"# Pre-0 decisions — {run_id}\n", "\n"]
        lines.append("Resolve each gate, then run `tripll approve " + run_id + "`.\n\n")
        for i, gate in enumerate(graph.pre0_gates, 1):
            lines.append(f"{i}. [ ] {gate}\n")
        (self.runs_root.run_dir(run_id) / "pre0-decisions.md").write_text("".join(lines))

    def _write_escalation(
        self, run_id: str, blocked: list[str], results: dict[str, NodeResult]
    ) -> None:
        """Write ``escalation.md`` listing blocked waves and failure evidence."""
        lines = [
            f"# Escalation — {run_id}\n",
            "\n",
            f"Blocked waves ({self.max_attempts} attempts exhausted):\n\n",
        ]
        for node_id in blocked:
            res = results[node_id]
            lines.append(f"- {node_id} ({res.attempts} attempts): {res.evidence}\n")
        (self.runs_root.run_dir(run_id) / "escalation.md").write_text("".join(lines))

    def _write_quota_pause(self, run_id: str, node_id: str, evidence: str, backend: str) -> None:
        """Write ``quota-paused.md`` with provider quota/session-limit guidance."""
        msg = quota_message(evidence)
        lines = [
            f"# Quota pause — {run_id}\n\n",
            f"Provider quota or session limit hit during `{node_id}`.\n\n",
            f"**Backend:** `{backend}`\n\n",
            f"**Message:** {msg}\n\n",
            "Resume with another provider/model when quota resets, e.g.:\n\n",
            "```bash\n",
            f"make continue-run RUN={run_id} PROVIDER=cursor_local MODEL=auto\n",
            "```\n",
        ]
        (self.runs_root.run_dir(run_id) / _QUOTA_MARKER).write_text("".join(lines))

    def _write_cost_pause(self, run_id: str, spent_usd: float) -> None:
        """Write ``cost-budget-paused.md`` when run cost exceeds the budget."""
        lines = [
            f"# Cost budget pause — {run_id}\n\n",
            f"Run cost **${spent_usd:.4f}** reached the configured budget "
            f"(**${self.cost_budget_usd:.2f}**).\n\n",
            "Resume after raising the budget, e.g.:\n\n",
            "```bash\n",
            f"TRIPLL_COST_BUDGET_USD=50 make resume-run RUN={run_id}\n",
            "```\n",
        ]
        (self.runs_root.run_dir(run_id) / _COST_MARKER).write_text("".join(lines))

    def _write_review_gate_pause(self, run_id: str, wave_id: str, gate_label: str) -> None:
        """Write review-gate pause marker and HITL form for operator review."""
        lines = [
            f"# Review gate pause — {run_id}\n\n",
            f"Wave **{wave_id}** completed — **AWAITING REVIEW** ({gate_label}).\n\n",
            "Complete the HITL form in the dashboard, then approve and resume:\n\n",
            "```bash\n",
            f"make approve-run RUN={run_id}\n",
            f"make resume-run RUN={run_id}\n",
            "```\n",
        ]
        run_dir = self.runs_root.run_dir(run_id)
        (run_dir / _REVIEW_GATE_MARKER).write_text("".join(lines))
        graph = build_graph_from_dir(run_dir, run_id=run_id)
        write_form_for_run(
            run_dir,
            graph,
            gate_kind=GateKind.REVIEW_GATE,
            wave_id=wave_id,
            gate_label=gate_label,
        )

    def _init_provider_fabric(self, graph: RunGraph) -> None:
        """Load per-provider pools from the plan and run auth preflight."""
        if getattr(self.adapter, "name", "") == "fake":
            self._pools, self._default_provider = pools_from_plan(
                None,
                global_limit=self._max_parallel,
            )
            return
        from tripll.adapters.auth_preflight import run_auth_preflight
        from tripll.plan.providers import plan_from_text, providers_used_by_graph

        plan: dict[str, object] = {}
        for node in graph.nodes.values():
            plan_path = (self.repo_root / node.plan_file).resolve()
            if plan_path.is_file():
                plan = plan_from_text(plan_path.read_text(encoding="utf-8"))
                break
        self._pools, self._default_provider = pools_from_plan(
            plan,
            global_limit=self._max_parallel,
        )
        if not self._orchestrator_mode:
            providers = providers_used_by_graph(graph, self._default_provider)
            run_auth_preflight(providers)

    def _provider_chain(self, node: WaveNode) -> list[str]:
        """Return primary provider followed by configured fallbacks."""
        primary = node.provider or self._default_provider
        chain = [primary]
        for name in node.fallback:
            if name not in chain:
                chain.append(name)
        return chain

    def _pick_provider(self, node: WaveNode) -> tuple[str, bool]:
        """Choose a provider, failing over when the primary is in cooldown."""
        chain = self._provider_chain(node)
        for index, provider in enumerate(chain):
            if self._pools is not None and self._pools.in_cooldown(provider):
                continue
            return provider, index > 0
        return chain[0], False

    def _resolve_adapter(
        self,
        node: WaveNode,
        graph: RunGraph,
        *,
        provider: str,
    ) -> AgentAdapter:
        """Build the adapter for *node* on *provider* (PROV-01)."""
        if getattr(self.adapter, "name", "") == "fake":
            return self.adapter
        from tripll.adapters import build_adapter
        from tripll.adapters.options import BackendOptions

        cfg = self._pools.configs.get(provider) if self._pools else None
        model = node.model
        if not model and cfg and cfg.default_model:
            model = cfg.default_model
        agent = node.agent
        if agent is None and hasattr(self.adapter, "agent"):
            agent = getattr(self.adapter, "agent", None)
        opts = BackendOptions(
            model=model,
            agent=agent,
            reasoning_effort=node.reasoning_effort,
            max_budget_usd=node.max_budget_usd,
        )
        orchestrator = graph.orchestrator if not self._orchestrator_mode else None
        return build_adapter(provider, options=opts, orchestrator=orchestrator)

    def _configure_orchestrator(self, graph: RunGraph, *, run_id: str) -> None:
        """Apply orchestrator-mode adapter, worktree, and status settings."""
        cfg = graph.orchestrator
        if cfg is None or not cfg.enabled:
            self._orchestrator_mode = False
            return
        self._orchestrator_mode = True
        from tripll.adapters import BACKENDS, build_adapter
        from tripll.adapters.claude_code import ClaudeCodeAdapter
        from tripll.adapters.cursor_local import CursorLocalAdapter
        from tripll.adapters.options import BackendOptions

        if self.adapter.name in BACKENDS:
            opts = BackendOptions()
            if isinstance(self.adapter, ClaudeCodeAdapter):
                opts = BackendOptions(
                    model=self.adapter.model,
                    agent=self.adapter.agent,
                    verbose=self.adapter.verbose,
                )
            elif isinstance(self.adapter, CursorLocalAdapter):
                opts = BackendOptions(model=self.adapter.model, agent=self.adapter.agent)
            self.adapter = build_adapter(self.adapter.name, options=opts, orchestrator=cfg)
        self._max_parallel = 1
        self._pools, self._default_provider = pools_from_plan(None, global_limit=1)
        self._orchestrator_rows = _initial_orchestrator_rows(cfg)
        self._orchestrator_turns = []
        run_dir = self.runs_root.run_dir(run_id)
        if (run_dir / "orchestrator-status.md").is_file():
            from tripll.orchestrator_status import read_latest

            snap = read_latest(run_dir)
            self._orchestrator_turns = list(snap.turns)
            if snap.rows:
                self._orchestrator_rows = list(snap.rows)
        self._wave_commit_shas = {}
        if cfg.single_branch and cfg.feature_branch:
            self._orchestrator_single_branch = True
            if isinstance(self.wtm, GitWorktreeManager) and not isinstance(
                self.wtm, SingleBranchWorktreeManager
            ):
                self.wtm = SingleBranchWorktreeManager(
                    self.repo_root,
                    self.runs_root,
                    feature_branch=cfg.feature_branch,
                )
        else:
            self._orchestrator_single_branch = False

    def _orchestrator_sync(
        self,
        run_id: str,
        graph: RunGraph,
        *,
        turn: OrchestratorTurn | None = None,
        lc: LedgerConnection | None = None,
    ) -> None:
        """Write ``orchestrator-status.md`` and optionally emit a ledger event."""
        sync_orchestrator_status(
            self.runs_root.run_dir(run_id),
            graph,
            rows=list(self._orchestrator_rows),
            turns=self._orchestrator_turns,
            turn=turn,
            run_id=run_id,
        )
        if turn is not None:
            logger.info("orchestrator: {} — {}", turn.turn_type, turn.summary)
            self._emit_orchestrator_event(run_id, turn, lc=lc)

    def _emit_orchestrator_event(
        self,
        run_id: str,
        turn: OrchestratorTurn,
        *,
        lc: LedgerConnection | None = None,
    ) -> None:
        """Append a ledger ``phase=orchestrator`` event for terminal/SSE feed (W3).

        Args:
            run_id (str): Run identifier.
            turn (OrchestratorTurn): Orchestrator turn to record.
            lc (LedgerConnection | None): Open ledger when already inside a transaction.

        Examples:
            >>> _emit_orchestrator_event.__name__
            '_emit_orchestrator_event'
        """
        excerpt_parts = [turn.summary.strip()]
        if turn.wave_summary.strip():
            excerpt_parts.append(turn.wave_summary.strip())
        excerpt = "\n\n".join(excerpt_parts)[:500]
        one_line = " ".join(turn.summary.split())
        metadata = json.dumps({"turn_type": turn.turn_type, "excerpt": excerpt}, ensure_ascii=False)

        def _append(target: LedgerConnection) -> None:
            append_event(
                target,
                run_id=run_id,
                node_id=ORCHESTRATOR_NODE_ID,
                phase="orchestrator",
                last_action=one_line[:240],
                metadata=metadata,
            )

        if lc is not None:
            _append(lc)
            return
        ledger_path = self.runs_root.ledger_path(run_id)
        if not ledger_path.is_file():
            return
        with open_ledger(ledger_path) as local_lc:
            _append(local_lc)

    def _update_orchestrator_row(
        self,
        wave_id: str,
        *,
        status: str,
        branch: str | None = None,
        commit: str = "—",
        evidence: str = "",
    ) -> None:
        """Update one row in the orchestrator status table for *wave_id*."""
        branch_val = branch or "—"
        for i, row in enumerate(self._orchestrator_rows):
            if row.wave == wave_id:
                self._orchestrator_rows[i] = StatusRow(
                    wave=wave_id,
                    status=status,
                    branch=branch_val,
                    commit=commit,
                    evidence=evidence,
                )
                return
        self._orchestrator_rows.append(
            StatusRow(
                wave=wave_id,
                status=status,
                branch=branch_val,
                commit=commit,
                evidence=evidence,
            )
        )

    def _orchestrator_commit_subject(self, cfg: OrchestratorConfig, wave_id: str) -> str:
        """Return the commit subject for orchestrator wave *wave_id*."""
        return cfg.commit_subjects.get(wave_id, f"feat(tripll): {wave_id}")

    def _orchestrator_commit_wave(
        self,
        run_id: str,
        graph: RunGraph,
        node: WaveNode,
        worktree: Worktree,
    ) -> tuple[bool, str]:
        """Commit and push orchestrator wave *node* when ``commit_per_wave`` is enabled."""
        cfg = graph.orchestrator
        if cfg is None or not cfg.commit_per_wave:
            return True, ""
        subject = self._orchestrator_commit_subject(cfg, node.wave_id)
        ok, result = commit_and_push_wave(
            worktree.path,
            self.repo_root,
            message=subject,
            branch=worktree.branch,
        )
        if not ok:
            self._orchestrator_sync(
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "stop",
                    f"Push failed after {node.wave_id}: {result[:200]}",
                ),
            )
            return False, result
        self._wave_commit_shas[node.wave_id] = result
        return True, result

    def _cost_budget_exceeded(self, lc: LedgerConnection, run_id: str) -> bool:
        """Return True when run cost meets or exceeds ``cost_budget_usd``."""
        if self.cost_budget_usd <= 0:
            return False
        return get_run_cost(lc, run_id) >= self.cost_budget_usd

    def _verify_with_retries(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        """Run verify targets with transient-flap retries (verify-only, no re-dispatch)."""
        evidence = ""
        for attempt in range(_VERIFY_ONLY_RETRIES + 1):
            ok, evidence = self.verifier.verify(worktree_path, targets)
            if ok:
                return True, evidence
            if attempt < _VERIFY_ONLY_RETRIES:
                logger.info(
                    "engine: verify retry {}/{} — {}",
                    attempt + 1,
                    _VERIFY_ONLY_RETRIES,
                    evidence[:120],
                )
        return False, evidence

    def _run_isolated_verify(
        self,
        *,
        run_id: str,
        node: WaveNode,
        implementer_worktree: Path,
        commit_sha: str,
        targets: list[str],
        transcript: str = "",
    ) -> tuple[bool, str]:
        """Dispatch isolated verify and always clean up the verify worktree."""
        verify_path: Path | None = None
        implementer = {
            "process_id": os.getpid(),
            "worktree": str(implementer_worktree),
            "transcript": transcript or None,
        }
        verify_ctx = build_verify_dispatch(
            implementer=implementer,
            wave={"node_id": node.node_id, "commit_sha": commit_sha or "HEAD"},
            runs_root=self.runs_root.run_dir(run_id) / "verify-wts",
        )
        assert_verify_isolation(implementer=implementer, verifier=verify_ctx)
        run_path = implementer_worktree
        if commit_sha and commit_sha not in {"", "unknown", "HEAD"}:
            try:
                run_path = materialize_verify_worktree(self.repo_root, verify_ctx)
                verify_path = run_path
            except RuntimeError as exc:
                logger.warning("engine: isolated verify worktree failed — {}", exc)
        try:
            return self._verify_with_retries(run_path, targets)
        finally:
            if verify_path is not None:
                remove_verify_worktree(self.repo_root, verify_path)

    def _end_attempt_with_usage(
        self,
        lc: LedgerConnection,
        attempt_id: str,
        *,
        outcome: AttemptOutcome,
        evidence: str | None,
        result: DispatchResult,
    ) -> None:
        """Close a ledger attempt row with usage fields from *result*."""
        end_attempt(
            lc,
            attempt_id,
            outcome=outcome,
            evidence=evidence,
            cost_usd=result.cost_usd,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    def _scaffold_w0_worktrees(self, run_id: str, graph: RunGraph) -> None:
        """Allocate W0 worktrees and stage plan slices before human-gate dispatch (D5).

        Args:
            run_id (str): Run identifier.
            graph (RunGraph): Parsed execution graph.

        Examples:
            >>> _scaffold_w0_worktrees.__name__
            '_scaffold_w0_worktrees'
        """
        run_dir = self.runs_root.run_dir(run_id)
        for node in graph.nodes.values():
            if node.wave_id != "W0":
                continue
            try:
                worktree = self.wtm.allocate(run_id, node.plan_id, node.wave_id)
                stage_dispatch_context(
                    run_dir,
                    worktree.path,
                    node.plan_file,
                    wave_id=node.wave_id,
                )
                logger.info(
                    "engine: {} scaffolded W0 worktree {} on {}",
                    run_id,
                    node.node_id,
                    worktree.path,
                )
            except Exception as exc:
                logger.warning(
                    "engine: {} W0 worktree scaffold for {} failed: {}",
                    run_id,
                    node.node_id,
                    exc,
                )

    async def _drive(self, run_id: str, graph: RunGraph) -> RunResult:
        """Main run loop: batches, concurrent dispatch, gates, and terminal state."""
        from tripll.loops import graph_available, require_graph
        from tripll.loops.l1_outer import plan_requires_langgraph, record_loop_snapshot

        if plan_requires_langgraph(graph):
            require_graph(feature="cyclic run plan")

        self._scaffold_w0_worktrees(run_id, graph)
        # Pre-0 human gate (W5.4).
        if graph.pre0_gates and not self._is_approved(run_id):
            from tripll.plan.human_gates import (
                HumanGateOutcome,
                evaluate_ci_billing_canary,
                pipeline_config_for_graph,
                resolve_human_gate_mode,
                resolve_pre0_gate,
            )

            pipeline = pipeline_config_for_graph(graph, self.repo_root)
            mode = resolve_human_gate_mode(pipeline)
            canary = evaluate_ci_billing_canary()
            outcome = resolve_pre0_gate(mode=mode, auto_acceptable=True, canary=canary)
            run_dir = self.runs_root.run_dir(run_id)

            if outcome is HumanGateOutcome.FAIL:
                logger.error("engine: {} Pre-0 gate rejected (human_gates=fail)", run_id)
                with open_ledger(self.runs_root.ledger_path(run_id)) as lc:
                    transition_run(lc, run_id, "failed")
                write_report(
                    self.runs_root.run_dir(run_id),
                    graph,
                    run_id=run_id,
                    state="failed",
                    results={},
                )
                return RunResult(run_id=run_id, state="failed")

            if outcome is HumanGateOutcome.PARKED:
                logger.warning(
                    "engine: {} Pre-0 PARKED — canary red under auto_accept ({})",
                    run_id,
                    canary.detail,
                )
                with open_ledger(self.runs_root.ledger_path(run_id)) as lc:
                    transition_run(lc, run_id, "paused")
                write_report(
                    self.runs_root.run_dir(run_id),
                    graph,
                    run_id=run_id,
                    state="parked",
                    results={},
                )
                return RunResult(run_id=run_id, state="parked")

            if outcome is HumanGateOutcome.PROCEED:
                (run_dir / _PRE0_MARKER).write_text("auto_accept\n")
                logger.info(
                    "engine: {} Pre-0 auto-accepted (canary ok: {})",
                    run_id,
                    canary.detail,
                )
            else:
                self._write_pre0_sheet(run_id, graph)
                write_form_for_run(run_dir, graph, gate_kind=GateKind.PRE0)
                with open_ledger(self.runs_root.ledger_path(run_id)) as lc:
                    transition_run(lc, run_id, "paused")
                write_report(
                    self.runs_root.run_dir(run_id),
                    graph,
                    run_id=run_id,
                    state="paused",
                    results={},
                )
                logger.info("engine: {} paused at Pre-0 ({} gates)", run_id, len(graph.pre0_gates))
                return RunResult(
                    run_id=run_id,
                    state="paused",
                    pre0_pending=True,
                    hitl_pending=True,
                    hitl_gate_kind=GateKind.PRE0.value,
                )

        results: dict[str, NodeResult] = {}
        done: set[str] = set()
        blocked: list[str] = []

        with open_ledger(self.runs_root.ledger_path(run_id)) as lc:
            # Crash recovery: re-queue waves interrupted mid-dispatch.
            for w in list_waves(lc, run_id):
                if w.state in ("running", "dispatched", "verifying"):
                    transition_wave(lc, run_id, w.node_id, "queued")

            transition_run(lc, run_id, "active")

            if graph_available():
                record_loop_snapshot(
                    lc,
                    run_id=run_id,
                    step="validate",
                    history=[],
                    next_node="waves",
                    extra={"thread_id": run_id},
                )

            # Resumability: skip waves already marked done or blocked in the ledger.
            for w in list_waves(lc, run_id):
                if w.state == "done":
                    done.add(w.node_id)
                    results[w.node_id] = NodeResult(w.node_id, "done", w.attempt_count)
                elif w.state == "blocked":
                    blocked.append(w.node_id)
                    results[w.node_id] = NodeResult(
                        w.node_id, "blocked", w.attempt_count, "already blocked on resume"
                    )
            if done:
                logger.info("engine: {} resuming — {} waves already done", run_id, len(done))
            if blocked:
                logger.info("engine: {} resuming — {} waves already blocked", run_id, len(blocked))
            if self._is_approved(run_id):
                complete_human_gate_waves(
                    lc,
                    run_id,
                    graph,
                    done=done,
                    blocked=blocked,
                    results=results,
                )
            self._sync_report(run_id, graph, partial_results=results)

            self._role_dispatch_effective = self._resolve_role_dispatch(graph)
            if self._pools is None:
                self._init_provider_fabric(graph)
            self._configure_orchestrator(graph, run_id=run_id)
            if self._orchestrator_mode:
                return await self._drive_orchestrator_serial(
                    lc, run_id, graph, done, blocked, results
                )

            logs_dir = self.runs_root.logs_dir(run_id)
            logger.info(
                "engine: {} dispatching waves — logs in {}",
                run_id,
                logs_dir,
            )

            for batch in graph.batches:
                if batch.is_human_gate:
                    continue
                logger.info("engine: {} batch {} — lanes {}", run_id, batch.batch_id, batch.lanes)
                batch_nodes = nodes_for_batch(graph, batch)

                # Drain the batch iteratively: each iteration selects the
                # maximal pairwise-disjoint ready set, runs it concurrently,
                # then repeats until the batch is empty.
                pause_result = await self._drain_batch(
                    lc, run_id, graph, batch_nodes, done, blocked, results
                )
                if pause_result is not None:
                    return pause_result

            state: RunState = "failed" if blocked else "done"
            if blocked:
                self._write_escalation(run_id, blocked, results)
            transition_run(lc, run_id, state)

        self._sync_report(run_id, graph, partial_results=results)

        if blocked:
            self.runs_root.fail_run(run_id)
            return RunResult(run_id=run_id, state="failed", nodes=results)
        self.runs_root.complete_run(run_id)
        return RunResult(run_id=run_id, state="done", nodes=results)

    async def _handle_review_gate(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        node: WaveNode,
        cfg: OrchestratorConfig,
        *,
        branch: str,
        short_commit: str,
        summary: str,
        results: dict[str, NodeResult],
    ) -> RunResult | None:
        """Handle a review gate after a wave completes (extracted from serial loop).

        When the wave has a review gate configured (either via
        ``orchestrator.review_gates`` or ``node.is_review_gate``), writes the
        gate marker, optionally dispatches a headless gate agent, and either
        continues (gate approved) or pauses the run.

        Args:
            lc (LedgerConnection): Open ledger connection.
            run_id (str): Run identifier.
            graph (RunGraph): Execution graph.
            node (WaveNode): The wave node that just completed.
            cfg (OrchestratorConfig): Orchestrator configuration.
            branch (str): Feature branch name for status updates.
            short_commit (str): Abbreviated commit SHA for status rows.
            summary (str): Wave completion summary text.
            results (dict[str, NodeResult]): Accumulated node results (for report sync).

        Returns:
            RunResult | None: ``RunResult(state="paused")`` when stopped at the gate,
            or ``None`` when the gate was approved.

        Examples:
            >>> _handle_review_gate.__name__
            '_handle_review_gate'
        """
        gate_label = cfg.review_gates.get(node.wave_id)
        if not gate_label and not node.is_review_gate:
            return None

        label = gate_label or f"{node.wave_id} review gate"
        self._write_review_gate_pause(run_id, node.wave_id, label)
        self._update_orchestrator_row(
            node.wave_id,
            status="awaiting review",
            branch=branch,
            commit=short_commit,
            evidence=f"AWAITING REVIEW ({label})",
        )
        self._orchestrator_sync(
            run_id,
            graph,
            turn=OrchestratorTurn(
                "review_gate",
                f"**AWAITING REVIEW** ({label}) — approve before next wave",
            ),
            lc=lc,
        )
        gate_proceed = False
        if _orchestrator_agent_enabled():
            from tripll.adapters import BACKENDS, build_gate_adapter
            from tripll.orchestrator_gate import dispatch_orchestrator_gate

            run_dir = self.runs_root.run_dir(run_id)
            wt_path = self._last_worktree_path or self.repo_root
            gate_adapter = (
                build_gate_adapter(self.adapter.name, cfg)
                if self.adapter.name in BACKENDS
                else self.adapter
            )
            gate_prompt = f"{label} complete — present summary, STOP"
            context: dict[str, object] = {
                "wave_id": node.wave_id,
                "gate_label": label,
                "wave_summary": summary,
                "worktree_path": str(wt_path),
                "branch": branch,
                "plan_path": node.plan_file,
            }
            decision = await dispatch_orchestrator_gate(
                run_dir,
                gate_prompt,
                context,
                adapter=gate_adapter,
                orchestrator=cfg,
                worktree_path=wt_path,
                timeout_s=node.wall_clock_limit_s,
            )
            gate_proceed = decision.proceed
            self._orchestrator_sync(
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "orchestrator_agent",
                    decision.summary[:240],
                ),
                lc=lc,
            )
        if gate_proceed:
            run_dir = self.runs_root.run_dir(run_id)
            (run_dir / _REVIEW_GATE_APPROVED).write_text(f"{node.wave_id}\n")
            (run_dir / _REVIEW_GATE_MARKER).unlink(missing_ok=True)
            logger.info(
                "orchestrator: gate agent approved {} — continuing serial run",
                node.wave_id,
            )
            return None  # continue
        async with self._ledger_lock:
            transition_run(lc, run_id, "paused")
        self._sync_report(run_id, graph, partial_results=results)
        return RunResult(
            run_id=run_id,
            state="paused",
            nodes=results,
            hitl_pending=True,
            hitl_gate_kind=GateKind.REVIEW_GATE.value,
        )

    async def _drive_orchestrator_serial(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        done: set[str],
        blocked: list[str],
        results: dict[str, NodeResult],
    ) -> RunResult:
        """Serial orchestrator drive — one wave at a time with status turns (W2).

        Args:
            lc (LedgerConnection): Open ledger connection.
            run_id (str): Run identifier.
            graph (RunGraph): Execution graph.
            done (set[str]): Completed node ids (updated in place).
            blocked (list[str]): Blocked node ids (updated in place).
            results (dict[str, NodeResult]): Per-node outcomes (updated in place).

        Returns:
            RunResult: Terminal or paused run outcome.

        Examples:
            >>> _drive_orchestrator_serial.__name__
            '_drive_orchestrator_serial'
        """
        cfg = graph.orchestrator
        if cfg is None:
            return RunResult(run_id=run_id, state="failed", nodes=results)

        branch = cfg.feature_branch or "—"
        self._orchestrator_sync(
            run_id,
            graph,
            turn=OrchestratorTurn(
                "bootstrap",
                f"Orchestrator serial run on `{branch}` — "
                f"{len(orchestrator_serial_nodes(graph))} waves",
            ),
            lc=lc,
        )

        for node in orchestrator_serial_nodes(graph):
            if node.node_id in done or node.node_id in blocked:
                continue

            # Pause-marker check: honour API pause before starting a new wave.
            # In-flight waves are NOT killed -- they run to completion.
            if self._pause_requested(run_id):
                logger.info(
                    "engine: {} pause-requested marker found -- pausing before {}",
                    run_id,
                    node.wave_id,
                )
                self._orchestrator_sync(
                    run_id,
                    graph,
                    turn=OrchestratorTurn(
                        "stop",
                        f"Pause requested -- stopping before {node.wave_id}",
                    ),
                    lc=lc,
                )
                async with self._ledger_lock:
                    transition_run(lc, run_id, "paused")
                self._sync_report(run_id, graph, partial_results=results)
                return RunResult(run_id=run_id, state="paused", nodes=results)

            self._update_orchestrator_row(node.wave_id, status="in progress", branch=branch)
            self._orchestrator_sync(
                run_id,
                graph,
                turn=OrchestratorTurn(
                    "wave_dispatched",
                    f"Dispatching wave-runner for **{node.wave_id}** (`{node.node_id}`)",
                ),
                lc=lc,
            )
            self._sync_report(run_id, graph, current_node_id=node.node_id, partial_results=results)

            res = await self._execute_node(lc, run_id, graph, node)
            results[node.node_id] = res

            if res.state == "done":
                summary = extract_wave_summary(self._last_dispatch_result_text)
                commit_sha = self._wave_commit_shas.get(node.wave_id, "—")
                short_commit = commit_sha[:12] if commit_sha != "—" else "—"
                self._update_orchestrator_row(
                    node.wave_id,
                    status="done",
                    branch=branch,
                    commit=short_commit,
                    evidence=summary[:120] if summary else "verify ok",
                )
                self._orchestrator_sync(
                    run_id,
                    graph,
                    turn=OrchestratorTurn(
                        "wave_complete",
                        f"**{node.wave_id}** complete",
                        wave_summary=summary,
                    ),
                    lc=lc,
                )
                done.add(node.node_id)

                gate_result = await self._handle_review_gate(
                    lc,
                    run_id,
                    graph,
                    node,
                    cfg,
                    branch=branch,
                    short_commit=short_commit,
                    summary=summary,
                    results=results,
                )
                if gate_result is not None:
                    return gate_result

            elif res.state in ("quota_paused", "cost_paused"):
                self._orchestrator_sync(
                    run_id,
                    graph,
                    turn=OrchestratorTurn(
                        "stop",
                        f"Paused during {node.wave_id}: {res.evidence[:200]}",
                    ),
                    lc=lc,
                )
                self._sync_report(run_id, graph, partial_results=results)
                return RunResult(
                    run_id=run_id,
                    state="paused",
                    nodes=results,
                    quota_pending=res.state == "quota_paused",
                    cost_pending=res.state == "cost_paused",
                )
            elif res.state == "blocked":
                evidence = res.evidence or ""
                if "push failed" in evidence.lower() or "git push" in evidence.lower():
                    self._orchestrator_sync(
                        run_id,
                        graph,
                        turn=OrchestratorTurn(
                            "stop",
                            f"Push failed during {node.wave_id}: {evidence[:200]}",
                        ),
                        lc=lc,
                    )
                    async with self._ledger_lock:
                        transition_run(lc, run_id, "paused")
                    self._sync_report(run_id, graph, partial_results=results)
                    return RunResult(run_id=run_id, state="paused", nodes=results)
                self._update_orchestrator_row(
                    node.wave_id,
                    status="failed",
                    branch=branch,
                    evidence=evidence[:120],
                )
                self._orchestrator_sync(
                    run_id,
                    graph,
                    turn=OrchestratorTurn(
                        "wave_failed",
                        f"**{node.wave_id}** blocked: {evidence[:200]}",
                    ),
                    lc=lc,
                )
                blocked.append(node.node_id)
                self._sync_report(run_id, graph, partial_results=results)

        state: RunState = "failed" if blocked else "done"
        if blocked:
            self._write_escalation(run_id, blocked, results)
        transition_run(lc, run_id, state)
        self._sync_report(run_id, graph, partial_results=results)
        if blocked:
            self.runs_root.fail_run(run_id)
            return RunResult(run_id=run_id, state="failed", nodes=results)
        self.runs_root.complete_run(run_id)
        return RunResult(run_id=run_id, state="done", nodes=results)

    async def _drain_batch(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        batch_nodes: list[WaveNode],
        done: set[str],
        blocked: list[str],
        results: dict[str, NodeResult],
    ) -> RunResult | None:
        """Drain *batch_nodes* using repeated concurrent rounds until empty.

        Each round:

        1. Compute ``ready_nodes(undrained, done)`` — nodes whose deps are all
           satisfied and that are not yet done/blocked.
        2. If nothing is ready but undrained nodes remain → dependency deadlock.
           The undrained nodes are marked blocked and escalated.
        3. Otherwise select the maximal pairwise-disjoint subset with
           ``select_concurrent_set`` and dispatch them concurrently under
           ``_sem``.
        4. If any node returns ``quota_paused`` or ``cost_paused``, let the
           siblings finish (they were already awaited via ``gather``), then
           pause the run and return the appropriate ``RunResult``.
        5. Repeat until all batch nodes are done or blocked.

        Args:
            lc (LedgerConnection): Open ledger connection (shared across rounds).
            run_id (str): Run identifier.
            graph (RunGraph): Execution graph.
            batch_nodes (list[WaveNode]): All nodes in the current batch.
            done (set[str]): node_ids already completed (mutated in-place).
            blocked (list[str]): node_ids already blocked (mutated in-place).
            results (dict[str, NodeResult]): Accumulated results (mutated in-place).

        Returns:
            RunResult | None: A paused ``RunResult`` when a pause is triggered;
            ``None`` when the batch drained cleanly (caller continues).

        Examples:
            >>> _drain_batch.__name__
            '_drain_batch'
        """
        undrained = [n for n in batch_nodes if n.node_id not in done and n.node_id not in blocked]

        while undrained:
            # Nodes whose deps are satisfied — safe to dispatch.
            candidates = ready_nodes(undrained, done)

            if not candidates:
                # Dependency deadlock: undrained nodes exist but none are ready.
                # This should not happen in a valid graph, but guard against it.
                deadlocked = [n.node_id for n in undrained]
                reason = (
                    f"dependency deadlock — {len(deadlocked)} node(s) undrained but "
                    f"none are ready (done={sorted(done)!r}, "
                    f"blocked={sorted(blocked)!r}): {deadlocked}"
                )
                logger.error("engine: {} {}", run_id, reason)
                for node in undrained:
                    blocked.append(node.node_id)
                    results[node.node_id] = NodeResult(node.node_id, "blocked", 0, reason)
                    async with self._ledger_lock:
                        transition_wave(lc, run_id, node.node_id, "blocked")
                self._sync_report(run_id, graph, partial_results=results)
                return None  # outer loop will write escalation

            # Pause-marker check: honour API pause before dispatching new waves.
            # In-flight waves are NOT killed -- they run to completion.
            if self._pause_requested(run_id):
                logger.info(
                    "engine: {} pause-requested marker found -- pausing before next dispatch",
                    run_id,
                )
                async with self._ledger_lock:
                    transition_run(lc, run_id, "paused")
                self._sync_report(run_id, graph, partial_results=results)
                return RunResult(run_id=run_id, state="paused", nodes=results)

            # Greedy maximal pairwise-disjoint subset.
            concurrent = select_concurrent_set(candidates)
            logger.info(
                "engine: {} dispatching {} node(s) concurrently: {}",
                run_id,
                len(concurrent),
                [n.node_id for n in concurrent],
            )
            self._sync_report(run_id, graph, partial_results=results)

            # Run the selected nodes under the semaphore and gather results.
            node_results = await self._run_concurrent_set(lc, run_id, graph, concurrent)

            # Integrate results.
            pause_quota: NodeResult | None = None
            pause_cost: NodeResult | None = None
            for res in node_results:
                results[res.node_id] = res
                if res.state == "done":
                    done.add(res.node_id)
                elif res.state == "quota_paused":
                    if pause_quota is None:
                        pause_quota = res
                elif res.state == "cost_paused":
                    if pause_cost is None:
                        pause_cost = res
                else:
                    blocked.append(res.node_id)

            self._sync_report(run_id, graph, partial_results=results)

            # Handle pauses: siblings already finished (gather awaited them all).
            if pause_quota is not None:
                self._write_quota_pause(
                    run_id, pause_quota.node_id, pause_quota.evidence, self.adapter.name
                )
                async with self._ledger_lock:
                    transition_run(lc, run_id, "paused")
                self._sync_report(run_id, graph, partial_results=results)
                logger.warning(
                    "engine: {} paused — provider quota on {} ({})",
                    run_id,
                    pause_quota.node_id,
                    pause_quota.evidence[:120],
                )
                return RunResult(
                    run_id=run_id,
                    state="paused",
                    nodes=results,
                    quota_pending=True,
                )

            if pause_cost is not None:
                async with self._ledger_lock:
                    self._write_cost_pause(run_id, get_run_cost(lc, run_id))
                    transition_run(lc, run_id, "paused")
                self._sync_report(run_id, graph, partial_results=results)
                logger.warning(
                    "engine: {} paused — cost budget reached on {}",
                    run_id,
                    pause_cost.node_id,
                )
                return RunResult(
                    run_id=run_id,
                    state="paused",
                    nodes=results,
                    cost_pending=True,
                )

            # Recompute undrained for next round.
            undrained = [
                n for n in batch_nodes if n.node_id not in done and n.node_id not in blocked
            ]

        return None

    async def _run_concurrent_set(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        nodes: list[WaveNode],
    ) -> list[NodeResult]:
        """Dispatch *nodes* concurrently under ``_sem`` and return all results.

        Each node runs inside a semaphore slot so at most ``max_parallel``
        coroutines are executing the long ``adapter.dispatch`` at once.  All
        nodes in *nodes* are guaranteed to finish (or fail) before this method
        returns — callers must check results for pause signals.

        Args:
            lc (LedgerConnection): Open ledger connection (shared).
            run_id (str): Run identifier.
            graph (RunGraph): Execution graph.
            nodes (list[WaveNode]): Nodes to dispatch concurrently.

        Returns:
            list[NodeResult]: One result per node, in the same order as *nodes*.
        """

        async def _guarded(node: WaveNode) -> NodeResult:
            return await self._execute_node(lc, run_id, graph, node)

        return list(await asyncio.gather(*(_guarded(n) for n in nodes)))

    async def _execute_node(
        self, lc: LedgerConnection, run_id: str, graph: RunGraph, node: WaveNode
    ) -> NodeResult:
        """Dispatch, verify, and checkpoint one wave node (with retries and scope checks)."""
        worktree = self.wtm.allocate(run_id, node.plan_id, node.wave_id)
        self._last_worktree_path = worktree.path
        run_dir = self.runs_root.run_dir(run_id)
        stage_dispatch_context(run_dir, worktree.path, node.plan_file, wave_id=node.wave_id)
        # --- read: no lock needed ---
        wave = get_wave(lc, run_id, node.node_id)
        if self._cost_budget_exceeded(lc, run_id):
            spent = get_run_cost(lc, run_id)
            self._write_cost_pause(run_id, spent)
            return NodeResult(
                node.node_id,
                "cost_paused",
                wave.attempt_count,
                f"cost budget ${self.cost_budget_usd:.2f} reached (${spent:.4f} spent)",
            )
        async with self._ledger_lock:
            if wave.state in ("running", "dispatched", "verifying"):
                transition_wave(lc, run_id, node.node_id, "queued")
        self._recover_worktree(worktree, run_id, node.node_id)

        prior_failures: list[str] = []
        evidence = ""
        cleanup_worktree_on_exit = False
        attempts_used = wave.attempt_count
        # Smarter retries (W2): track how many full re-dispatches produced no edits
        # in owned paths.  Once this counter reaches _MAX_NO_PROGRESS_DISPATCHES we
        # escalate immediately rather than burning all max_attempts slots.
        no_progress_dispatches: int = 0
        provider, _fallback_used = self._pick_provider(node)
        adapter = self._resolve_adapter(node, graph, provider=provider)
        pools = self._pools
        if pools is not None:
            await pools.acquire(provider)
        try:
            while attempts_used < self.max_attempts:
                if self._cost_budget_exceeded(lc, run_id):
                    spent = get_run_cost(lc, run_id)
                    self._write_cost_pause(run_id, spent)
                    return NodeResult(
                        node.node_id,
                        "cost_paused",
                        attempts_used,
                        f"cost budget ${self.cost_budget_usd:.2f} reached (${spent:.4f} spent)",
                    )

                # No-progress early exit: if we already hit the cap, escalate now
                # instead of dispatching another doomed full attempt.
                if no_progress_dispatches >= _MAX_NO_PROGRESS_DISPATCHES:
                    evidence = (
                        f"no-progress escalation after {no_progress_dispatches} "
                        f"dispatch(es) produced no edits in owned paths "
                        f"{node.owned_paths!r} — likely a scope-permission or "
                        f"brief-configuration problem"
                    )
                    logger.warning(
                        "engine: {} {} — {}",
                        run_id,
                        node.node_id,
                        evidence,
                    )
                    async with self._ledger_lock:
                        transition_wave(lc, run_id, node.node_id, "blocked")
                    return NodeResult(node.node_id, "blocked", attempts_used, evidence)

                attempt = attempts_used + 1
                provider, fallback_used = self._pick_provider(node)
                adapter = self._resolve_adapter(node, graph, provider=provider)
                brief = self._brief_for(
                    run_id, graph, node, worktree, prior_failures, attempt=attempt
                )
                if fallback_used:
                    brief["fallback_used"] = True
                    brief["provider"] = provider
                if node.max_budget_usd is not None:
                    brief["max_budget_usd"] = node.max_budget_usd
                if node.reasoning_effort:
                    brief["reasoning_effort"] = node.reasoning_effort
                write_brief(brief, self.runs_root.briefs_dir(run_id))
                log_path = self.runs_root.logs_dir(run_id) / (
                    f"{_safe(node.node_id)}-attempt{attempt}.log"
                )
                if attempt == 1 and attempts_used == 0:
                    logger.info(
                        "engine: {} node {} — branch {} worktree {}",
                        run_id,
                        node.node_id,
                        worktree.branch,
                        worktree.path,
                    )
                logger.info(
                    "engine: {} attempt {} — log {}",
                    node.node_id,
                    attempt,
                    log_path,
                )
                # Snapshot owned-path edits *before* dispatch so we can detect
                # whether the agent produced any new work (W2 no-progress guard).
                # None means the worktree is not git-backed (e.g. tests) — skip guard.
                pre_dispatch_owned = self._owned_changed_paths(worktree, node.owned_paths)

                # --- mutating sequence: insert_attempt + transition_wave x2 ---
                task_id = f"{run_id}:{node.node_id}"
                env_fp = capture_env_fingerprint(
                    task_id=task_id,
                    model_id=node.model or getattr(adapter, "model", None) or "",
                    repo_root=self.repo_root,
                )
                fp_json = fingerprint_to_json(env_fp)
                fp_hash = fingerprint_hash(env_fp)
                async with self._ledger_lock:
                    attempt_id = insert_attempt(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        attempt_n=attempt,
                        backend=adapter.name,
                        brief_path=str(self.runs_root.briefs_dir(run_id)),
                        log_path=str(log_path),
                        model=node.model or getattr(adapter, "model", None),
                        agent=getattr(adapter, "agent", None),
                        env_fingerprint_json=fp_json,
                        env_fingerprint_hash=fp_hash,
                    )
                    attempts_used += 1
                    transition_wave(lc, run_id, node.node_id, "dispatched")
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        phase="dispatched",
                        attempt_n=attempt,
                    )
                    transition_wave(lc, run_id, node.node_id, "running")
                    append_event(lc, run_id=run_id, node_id=node.node_id, phase="running")

                wave_label = node.wave_id
                start_msg = (
                    f"Executing wave {wave_label}: reading the plan contract "
                    f"and checking branch state."
                )
                async with self._ledger_lock:
                    append_event(
                        lc,
                        run_id=run_id,
                        node_id=node.node_id,
                        phase="running",
                        last_action=start_msg,
                        attempt_n=attempt,
                    )

                # Build an async callback so run_streaming can write live events.
                # The callback is throttled inside run_streaming; here we only
                # guard the ledger write under _ledger_lock.
                # Capture node_id in the default arg to avoid the B023 closure
                # binding issue (ruff: loop variable capture in function definition).
                _bound_node_id: str = node.node_id

                async def _on_stream_event(
                    *,
                    last_action: str | None = None,
                    input_tokens: int | None = None,
                    output_tokens: int | None = None,
                    cost_usd: float | None = None,
                    _nid: str = _bound_node_id,
                ) -> None:
                    # Called from inside run_streaming — emit a running event.
                    from tripll.log_format import format_terminal_summary

                    async with self._ledger_lock:
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=_nid,
                            phase="running",
                            last_action=last_action,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cost_usd=cost_usd,
                        )
                    # Concise terminal heartbeat — one line per agent per meaningful change.
                    if last_action or output_tokens:
                        short_id = _nid.split(":", 1)[-1] if ":" in _nid else _nid
                        tok_part = (
                            f" | {input_tokens or 0}→{output_tokens or 0} tok"
                            if output_tokens
                            else ""
                        )
                        cost_part = f" | ${cost_usd:.4f}" if cost_usd else ""
                        action_part = f" ▸ {last_action.strip()}" if last_action else ""
                        import sys

                        sys.stderr.write(
                            format_terminal_summary(
                                f"telemetry:{short_id}{action_part}{tok_part}{cost_part}"
                            )
                            + "\n"
                        )
                        sys.stderr.flush()

                # --- long await: no lock held ---
                result = await adapter.dispatch(
                    brief,
                    worktree_path=worktree.path,
                    log_path=log_path,
                    timeout_s=node.wall_clock_limit_s,
                    log_header={
                        "run_id": run_id,
                        "node_id": node.node_id,
                        "attempt": attempt,
                        "backend": adapter.name,
                    },
                    on_event=_on_stream_event,
                )
                self._last_dispatch_result_text = result.result_text or ""
                from tripll.adapters.failure_class import classify_dispatch

                failure_class = classify_dispatch(result)
                if failure_class == "infra":
                    if pools is not None:
                        pools.record_infra(provider)
                    async with self._ledger_lock:
                        void_infra_attempt_count(lc, run_id=run_id, node_id=node.node_id)
                        attempts_used -= 1
                        self._end_attempt_with_usage(
                            lc,
                            attempt_id,
                            outcome="failed",
                            evidence=result.result_text or "infra failure",
                            result=result,
                        )
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="infra",
                            last_action=f"infra on {provider}: {(result.result_text or '')[:120]}",
                            attempt_n=attempt,
                        )
                        transition_wave(lc, run_id, node.node_id, "queued")
                    cooldown = pools.configs[provider].cooldown_s if pools else 0
                    if cooldown > 0:
                        await asyncio.sleep(float(cooldown))
                    continue
                if pools is not None:
                    pools.record_success(provider)
                if result.cost_usd:
                    logger.info(
                        "engine: {} {} attempt {} cost ${:.4f}",
                        run_id,
                        node.node_id,
                        attempt,
                        result.cost_usd,
                    )

                # W2 no-progress detection: check if any owned path was touched.
                # Skip when pre is None (non-git worktree — guard disabled).
                if pre_dispatch_owned is not None:
                    post_dispatch_owned = self._owned_changed_paths(worktree, node.owned_paths)
                    made_progress = post_dispatch_owned is None or bool(
                        post_dispatch_owned - pre_dispatch_owned
                    )
                    if not made_progress:
                        no_progress_dispatches += 1
                        logger.warning(
                            "engine: {} {} attempt {} — no edits in owned paths "
                            "(no-progress #{}/{})",
                            run_id,
                            node.node_id,
                            attempt,
                            no_progress_dispatches,
                            _MAX_NO_PROGRESS_DISPATCHES,
                        )

                if self._cost_budget_exceeded(lc, run_id):
                    async with self._ledger_lock:
                        self._end_attempt_with_usage(
                            lc,
                            attempt_id,
                            outcome="failed",
                            evidence="cost budget exceeded after dispatch",
                            result=result,
                        )
                        spent = get_run_cost(lc, run_id)
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="paused",
                            last_action=f"cost budget ${self.cost_budget_usd:.2f} reached",
                            cost_usd=result.cost_usd,
                        )
                    self._write_cost_pause(run_id, spent)
                    return NodeResult(
                        node.node_id,
                        "cost_paused",
                        attempt,
                        f"cost budget ${self.cost_budget_usd:.2f} reached (${spent:.4f} spent)",
                    )
                if result.outcome == "done":
                    breach = self.wtm.scope_breach(
                        worktree,
                        node.forbidden_paths,
                        owned_paths=node.owned_paths,
                    )
                    if breach:
                        self.wtm.revert(worktree, breach)
                        evidence = f"scope breach reverted: {breach}"
                        async with self._ledger_lock:
                            self._end_attempt_with_usage(
                                lc,
                                attempt_id,
                                outcome="scope_breach",
                                evidence=evidence,
                                result=result,
                            )
                            append_event(
                                lc,
                                run_id=run_id,
                                node_id=node.node_id,
                                phase="failed",
                                last_action=f"scope breach reverted: {str(breach)[:120]}",
                            )
                        self._checkpoint_attempt(worktree, run_id, node.node_id, attempt)
                    else:
                        self._checkpoint_attempt(worktree, run_id, node.node_id, attempt)
                        async with self._ledger_lock:
                            transition_wave(lc, run_id, node.node_id, "verifying")
                            append_event(lc, run_id=run_id, node_id=node.node_id, phase="verifying")
                        ok, ev = self._run_isolated_verify(
                            run_id=run_id,
                            node=node,
                            implementer_worktree=worktree.path,
                            commit_sha=self._last_checkpoint_sha,
                            targets=node.verify_targets,
                            transcript=result.result_text,
                        )
                        if ok:
                            if (
                                self._orchestrator_mode
                                and graph.orchestrator
                                and graph.orchestrator.commit_per_wave
                            ):
                                commit_ok, commit_result = self._orchestrator_commit_wave(
                                    run_id, graph, node, worktree
                                )
                                if not commit_ok:
                                    async with self._ledger_lock:
                                        self._end_attempt_with_usage(
                                            lc,
                                            attempt_id,
                                            outcome="failed",
                                            evidence=commit_result,
                                            result=result,
                                        )
                                        transition_wave(lc, run_id, node.node_id, "blocked")
                                        transition_run(lc, run_id, "paused")
                                    return NodeResult(
                                        node.node_id,
                                        "blocked",
                                        attempt,
                                        commit_result,
                                    )
                            async with self._ledger_lock:
                                self._end_attempt_with_usage(
                                    lc,
                                    attempt_id,
                                    outcome="done",
                                    evidence=ev,
                                    result=result,
                                )
                                transition_wave(lc, run_id, node.node_id, "done")
                                append_event(
                                    lc,
                                    run_id=run_id,
                                    node_id=node.node_id,
                                    phase="done",
                                    input_tokens=result.input_tokens,
                                    output_tokens=result.output_tokens,
                                    cost_usd=result.cost_usd,
                                )
                            cleanup_worktree_on_exit = True
                            logger.info("engine: {} node {} done (verify ok)", run_id, node.node_id)
                            return NodeResult(node.node_id, "done", attempt)
                        evidence = ev
                        async with self._ledger_lock:
                            self._end_attempt_with_usage(
                                lc,
                                attempt_id,
                                outcome="failed",
                                evidence=ev,
                                result=result,
                            )
                            append_event(
                                lc,
                                run_id=run_id,
                                node_id=node.node_id,
                                phase="failed",
                                last_action=f"verify failed: {ev[:120]}",
                                input_tokens=result.input_tokens,
                                output_tokens=result.output_tokens,
                                cost_usd=result.cost_usd,
                            )
                elif result.outcome == "quota_exhausted":
                    evidence = result.result_text or result.outcome
                    async with self._ledger_lock:
                        self._end_attempt_with_usage(
                            lc,
                            attempt_id,
                            outcome="quota_exhausted",
                            evidence=evidence,
                            result=result,
                        )
                        self._checkpoint_attempt(worktree, run_id, node.node_id, attempt)
                        transition_wave(lc, run_id, node.node_id, "queued")
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="paused",
                            last_action="quota exhausted — pausing",
                        )
                    logger.warning(
                        "engine: {} quota exhausted on {} — pausing (no retry burn)",
                        run_id,
                        node.node_id,
                    )
                    return NodeResult(node.node_id, "quota_paused", attempt, evidence)
                else:
                    evidence = result.result_text or result.outcome
                    outcome: AttemptOutcome = (
                        "timed_out" if result.outcome == "timed_out" else "failed"
                    )
                    async with self._ledger_lock:
                        self._end_attempt_with_usage(
                            lc,
                            attempt_id,
                            outcome=outcome,
                            evidence=evidence,
                            result=result,
                        )
                        append_event(
                            lc,
                            run_id=run_id,
                            node_id=node.node_id,
                            phase="failed",
                            last_action=f"attempt {attempt} {outcome}: {evidence[:120]}",
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost_usd=result.cost_usd,
                        )
                    self._checkpoint_attempt(worktree, run_id, node.node_id, attempt)

                prior_failures.append(f"attempt {attempt}: {evidence}")
                if attempts_used < self.max_attempts:
                    async with self._ledger_lock:
                        transition_wave(lc, run_id, node.node_id, "queued")

            async with self._ledger_lock:
                transition_wave(lc, run_id, node.node_id, "blocked")
                append_event(
                    lc,
                    run_id=run_id,
                    node_id=node.node_id,
                    phase="failed",
                    last_action=f"blocked after {attempts_used} attempts: {evidence[:120]}",
                )
            return NodeResult(node.node_id, "blocked", attempts_used, evidence)
        finally:
            if pools is not None:
                pools.release(provider)
            self._recover_worktree(worktree, run_id, node.node_id)
            row = get_wave(lc, run_id, node.node_id)
            if row.state in ("running", "dispatched", "verifying"):
                async with self._ledger_lock:
                    transition_wave(lc, run_id, node.node_id, "queued")
            if cleanup_worktree_on_exit and not self._orchestrator_single_branch:
                self.wtm.cleanup(worktree)

    def _owned_changed_paths(self, worktree: Worktree, owned_paths: list[str]) -> set[str] | None:
        """Return the set of changed worktree paths that fall under *owned_paths*.

        Used by the no-progress guard (W2) to detect whether the agent made any
        edits to its assigned paths since the last dispatch.

        Returns ``None`` when the worktree is not a git repository (e.g. in-memory
        fakes in tests) — callers should treat ``None`` as "indeterminate / assume
        progress" so the guard never fires on non-git worktrees.

        Args:
            worktree (Worktree): The lane worktree.
            owned_paths (list[str]): Paths the wave is assigned to edit.

        Returns:
            set[str] | None: Repo-relative changed paths under an owned path, or
            ``None`` when the status cannot be determined.
        """
        try:
            all_changed = changed_paths(worktree.path)
        except Exception:
            # Non-git worktree (FakeWorktreeManager in tests) — cannot tell.
            return None
        if not owned_paths:
            return set(all_changed)
        owned: set[str] = set()
        for path in all_changed:
            p = path.rstrip("/")
            for op in owned_paths:
                o = op.rstrip("/")
                # Changed path is under an owned path.
                if p == o or p.startswith(o + "/"):
                    owned.add(path)
                    break
                # Changed path is a directory prefix of an owned path — git
                # reports untracked directories at the first new ancestor level
                # (e.g. "src/" when "src/sevn/demo/marker.txt" was created).
                # In this case the owned path is *inside* the changed directory.
                if o.startswith(p + "/") or o == p:
                    owned.add(path)
                    break
        return owned

    def _recover_worktree(self, worktree: Worktree, run_id: str, node_id: str) -> None:
        """Commit orphaned work in *worktree* after a crash or timeout."""
        sha = self.wtm.recover(worktree, run_id=run_id, node_id=node_id)
        if sha:
            logger.info(
                "engine: {} {} recovery checkpoint {}",
                run_id,
                node_id,
                sha[:12],
            )

    def _checkpoint_attempt(
        self, worktree: Worktree, run_id: str, node_id: str, attempt: int
    ) -> None:
        """Checkpoint *worktree* after attempt *attempt* (logs SHA when present)."""
        try:
            sha = self.wtm.checkpoint(worktree, run_id=run_id, node_id=node_id, attempt=attempt)
        except WorktreeError as exc:
            logger.error(
                "engine: {} {} attempt {} checkpoint failed: {}",
                run_id,
                node_id,
                attempt,
                exc,
            )
            return
        if sha:
            self._last_checkpoint_sha = sha
            logger.info(
                "engine: {} {} attempt {} checkpoint {}",
                run_id,
                node_id,
                attempt,
                sha[:12],
            )

    @staticmethod
    def _append_external_upload_dirs(
        brief: dict[str, object],
        worktree_path: Path,
    ) -> dict[str, object]:
        """Append external upload parent dirs to ``workspace_scope`` (D3).

        Args:
            brief (dict[str, object]): Dispatch brief from :func:`render_json_brief`.
            worktree_path (Path): Lane worktree root.

        Returns:
            dict[str, object]: *brief* with external dirs merged into ``workspace_scope``.

        Examples:
            >>> from pathlib import Path
            >>> b = Engine._append_external_upload_dirs(
            ...     {"workspace_scope": ["src/"]}, Path("/wt"),
            ... )
            >>> "workspace_scope" in b
            True
        """
        from tripll.plan_paths import normalize_plan_refs

        repo_root = worktree_path.resolve()
        staged_dir = repo_root / "plan" / "tripll"
        external_dirs: list[str] = []
        if staged_dir.is_dir():
            for path in sorted(staged_dir.glob("*.md")):
                _, dirs = normalize_plan_refs(path.read_text(encoding="utf-8"), repo_root)
                external_dirs.extend(dirs)
        if not external_dirs:
            return brief
        scope_raw = brief.get("workspace_scope")
        scope = [str(x) for x in scope_raw] if isinstance(scope_raw, list) else []
        seen = set(scope)
        for directory in external_dirs:
            if directory not in seen:
                seen.add(directory)
                scope.append(directory)
        brief["workspace_scope"] = scope
        return brief

    def _brief_for(
        self,
        run_id: str,
        graph: RunGraph,
        node: WaveNode,
        worktree: Worktree,
        prior_failures: list[str],
        *,
        attempt: int = 1,
    ) -> dict[str, object]:
        """Build the JSON dispatch brief for *node*, including retry directives."""
        plan_worktree_path = str(staged_wave_plan_path(worktree.path, node.plan_file, node.wave_id))
        brief = render_json_brief(
            node,
            run_id=run_id,
            branch=worktree.branch,
            worktree_path=str(worktree.path),
            plan_worktree_path=plan_worktree_path,
            model=node.model,
            orchestrator=graph.orchestrator,
            role_dispatch=self._role_dispatch_effective,
        )
        if node.reasoning_effort:
            brief["reasoning_effort"] = node.reasoning_effort
        if node.max_budget_usd is not None:
            brief["max_budget_usd"] = node.max_budget_usd
        if node.provider:
            brief["provider"] = node.provider
        brief = self._append_external_upload_dirs(brief, worktree.path)
        orch_cfg = graph.orchestrator
        if orch_cfg and orch_cfg.enabled and self._wave_commit_shas:
            brief["prior_wave_commits"] = dict(self._wave_commit_shas)
        if prior_failures:
            directives = brief["agent_directives"]
            if isinstance(directives, list):
                directives.append(
                    "Prior attempt failures — correct these: " + " | ".join(prior_failures)
                )
                directives.append(
                    f"Prior work is checkpointed on branch `{worktree.branch}`; "
                    "continue from the current checkout — do not reset or delete "
                    "unrelated files."
                )
                brief["agent_directives"] = directives
        elif attempt > 1:
            directives = brief["agent_directives"]
            if isinstance(directives, list):
                directives.append(
                    f"Continue from checkpointed work on branch `{worktree.branch}`; "
                    "do not reset or delete unrelated files."
                )
                brief["agent_directives"] = directives
        graph_db = self.runs_root.graph_db_path(run_id)
        if not graph_db.is_file():
            graph_db = self.repo_root / ".tripll" / "graph.db"
        at_sha = self._last_checkpoint_sha or "HEAD"
        targets = list(node.owned_paths)
        brief = enrich_brief_with_graph_pack(
            brief,
            wave_targets=targets,
            graph_store=str(graph_db),
            at_sha=at_sha,
            grep_brief=self._grep_brief,
            run_dir=worktree.path.parent.parent / "brief-spill",
        )
        return brief


def _safe(node_id: str) -> str:
    """Return a filename-safe form of *node_id*.

    Args:
        node_id (str): Raw node id.

    Returns:
        str: Sanitised id.

    Examples:
        >>> _safe("telemetry:W0->Final")
        'telemetry_W0-Final'
    """
    return node_id.replace(":", "_").replace("/", "_").replace(">", "")
