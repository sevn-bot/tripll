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
* Ledger-mutating sequences are guarded by ``_ledger_lock``.
* Default model is ``claude-sonnet-5`` unless the wave row declares otherwise.

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
    Engine — the orchestration engine (façade over ``engine_*`` seam modules).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from tripll.adapters.pools import ProviderPoolRegistry, pools_from_plan
from tripll.engine_batch_drive import (
    _drain_batch as _drain_batch_impl,
)
from tripll.engine_batch_drive import (
    _drive as _drive_impl,
)
from tripll.engine_batch_drive import (
    _drive_via_outer_loop as _drive_via_outer_loop_impl,
)
from tripll.engine_batch_drive import (
    _prepare_run_ledger as _prepare_run_ledger_impl,
)
from tripll.engine_batch_drive import (
    _run_concurrent_set as _run_concurrent_set_impl,
)
from tripll.engine_batch_drive import (
    _scaffold_w0_worktrees as _scaffold_w0_worktrees_impl,
)
from tripll.engine_batch_drive import (
    _shielded_finalize_wave_ledger as _shielded_finalize_wave_ledger_impl,
)
from tripll.engine_batch_drive import (
    _write_cost_pause as _write_cost_pause_impl,
)
from tripll.engine_batch_drive import (
    _write_escalation as _write_escalation_impl,
)
from tripll.engine_batch_drive import (
    _write_pre0_sheet as _write_pre0_sheet_impl,
)
from tripll.engine_batch_drive import (
    _write_quota_pause as _write_quota_pause_impl,
)
from tripll.engine_batch_drive import (
    _write_review_gate_pause as _write_review_gate_pause_impl,
)
from tripll.engine_batch_drive import (
    drive_wave_batches as _drive_wave_batches_impl,
)
from tripll.engine_brief import append_external_upload_dirs, brief_for
from tripll.engine_exits import (
    _build_exit_eval_context as _build_exit_eval_context_impl,
)
from tripll.engine_exits import (
    _cost_budget_exceeded as _cost_budget_exceeded_impl,
)
from tripll.engine_exits import (
    _evaluate_engine_exit as _evaluate_engine_exit_impl,
)
from tripll.engine_exits import (
    _external_event_state as _external_event_state_impl,
)
from tripll.engine_exits import (
    _fire_error_threshold_exit as _fire_error_threshold_exit_impl,
)
from tripll.engine_exits import (
    _fire_goal_met_exit as _fire_goal_met_exit_impl,
)
from tripll.engine_exits import (
    _init_run_wall_clock as _init_run_wall_clock_impl,
)
from tripll.engine_exits import (
    _load_check_runs_for_run as _load_check_runs_for_run_impl,
)
from tripll.engine_exits import (
    _pause_requested as _pause_requested_impl,
)
from tripll.engine_exits import (
    _scan_pre_dispatch_exits as _scan_pre_dispatch_exits_impl,
)
from tripll.engine_human_gates import _resolve_grep_brief, complete_human_gate_waves
from tripll.engine_node_dispatch import (
    _MAX_NO_PROGRESS_DISPATCHES,
)
from tripll.engine_node_dispatch import (
    _execute_node as _execute_node_impl,
)
from tripll.engine_orchestrator import (
    _REVIEW_GATE_APPROVED,
    _REVIEW_GATE_MARKER,
)
from tripll.engine_orchestrator import (
    _configure_orchestrator as _configure_orchestrator_impl,
)
from tripll.engine_orchestrator import (
    _drive_orchestrator_serial as _drive_orchestrator_serial_impl,
)
from tripll.engine_orchestrator import (
    _emit_orchestrator_event as _emit_orchestrator_event_impl,
)
from tripll.engine_orchestrator import (
    _handle_review_gate as _handle_review_gate_impl,
)
from tripll.engine_orchestrator import (
    _orchestrator_commit_subject as _orchestrator_commit_subject_impl,
)
from tripll.engine_orchestrator import (
    _orchestrator_commit_wave as _orchestrator_commit_wave_impl,
)
from tripll.engine_orchestrator import (
    _orchestrator_sync as _orchestrator_sync_impl,
)
from tripll.engine_orchestrator import (
    _update_orchestrator_row as _update_orchestrator_row_impl,
)
from tripll.engine_scheduling import (
    can_run_concurrently,
    human_gate_node_ids,
    max_parallel_from_env,
    nodes_for_batch,
    orchestrator_serial_nodes,
    ready_nodes,
    select_concurrent_set,
)
from tripll.engine_verify import (
    VERIFY_ONLY_RETRIES,
    run_isolated_verify,
    run_quality_gauntlet,
    verify_with_retries,
)
from tripll.engine_worktrees import (
    GitWorktreeManager,
    MakeVerifier,
    SingleBranchWorktreeManager,
    Verifier,
    WorktreeManager,
)
from tripll.hitl import GateKind
from tripll.ledger import (
    LedgerConnection,
    insert_run,
    insert_wave,
    open_ledger,
)
from tripll.parse import build_graph_from_dir
from tripll.report import sync_report, write_report

__all__ = [
    "_MAX_NO_PROGRESS_DISPATCHES",
    "Engine",
    "GitWorktreeManager",
    "MakeVerifier",
    "NodeResult",
    "RunResult",
    "SingleBranchWorktreeManager",
    "Verifier",
    "WorktreeManager",
    "can_run_concurrently",
    "complete_human_gate_waves",
    "human_gate_node_ids",
    "nodes_for_batch",
    "orchestrator_serial_nodes",
    "ready_nodes",
    "select_concurrent_set",
    "write_report",
]

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.adapters.base import AgentAdapter
    from tripll.graph import OrchestratorConfig, RunGraph, WaveNode
    from tripll.orchestrator_status import OrchestratorTurn, StatusRow
    from tripll.pipeline import RunsRoot
    from tripll.worktrees import Worktree


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
# Engine
# ---------------------------------------------------------------------------

_PRE0_MARKER = "pre0-approved"
_VERIFY_ONLY_RETRIES = VERIFY_ONLY_RETRIES


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

    Exit evaluation is delegated to :mod:`tripll.engine_exits` (``evaluate_exit``,
    ``exit_fired``, ``goal_met``, ``review_success``, ``wall_clock``,
    ``error_threshold``, ``external_event``).

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
        grep_brief: bool | None = None,
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
            max_parallel if max_parallel is not None else max_parallel_from_env()
        )
        self._role_dispatch_cli: bool | None = role_dispatch
        self._role_dispatch_effective: bool = False
        self._grep_brief = _resolve_grep_brief(grep_brief)
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
        self._run_wall_clock_start: float | None = None
        self._run_deadline_ts: float | None = None
        self._last_fired_exit_id: int | None = None
        self._active_run_graph: RunGraph | None = None

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

        self.runs_root.graph_path(run_id).write_text(json.dumps(graph.to_dict(), indent=2))

        graph_db = self.runs_root.graph_db_path(run_id)
        from tripll.plan.code_graph import refresh_code_graph

        if refresh_code_graph(graph_db, self.repo_root):
            logger.info("engine: refreshed code graph at {}", graph_db)

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

        from tripll.calibrate.sync import sync_run_calibration_metadata

        sync_run_calibration_metadata(
            run_id=run_id,
            run_dir=run_dir,
            graph_db_path=graph_db,
            repo_root=self.repo_root,
        )

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
        from tripll.inject import reconcile_run_graph

        with open_ledger(self.runs_root.ledger_path(run_id)) as lc:
            result = reconcile_run_graph(
                self.runs_root,
                run_id,
                lc=lc,
                dry_run=False,
                require_pause=False,
                source="resume",
            )
        graph = result.graph
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

    def _init_provider_fabric(self, graph: RunGraph) -> None:
        """Load per-provider pools from the plan and run auth preflight."""
        if getattr(self.adapter, "name", "") == "fake":
            self._pools, self._default_provider = pools_from_plan(
                None,
                global_limit=self._max_parallel,
            )
            return
        from tripll.adapters.auth_preflight import run_auth_preflight
        from tripll.plan.providers import providers_used_by_graph

        plan = self._plan_for_graph(graph)
        self._pools, self._default_provider = pools_from_plan(
            plan,
            global_limit=self._max_parallel,
        )
        if not self._orchestrator_mode:
            providers = providers_used_by_graph(graph, self._default_provider)
            run_auth_preflight(providers)

    def _plan_for_graph(self, graph: RunGraph) -> dict[str, object]:
        """Return the first v3 plan dict referenced by *graph*."""
        from tripll.plan.providers import plan_from_text

        for node in graph.nodes.values():
            plan_path = (self.repo_root / node.plan_file).resolve()
            if plan_path.is_file():
                return plan_from_text(plan_path.read_text(encoding="utf-8"))
        return {}

    def _init_run_tracing(self, run_id: str, graph: RunGraph) -> None:
        """Bind local trace sinks for *run_id* using plan + env tracing config."""
        from tripll.obs import configure_observability, get_tracing_config
        from tripll.tracing.spans import init_run_tracing

        plan = self._plan_for_graph(graph)
        configure_observability(plan=plan)
        run_dir = self.runs_root.run_dir(run_id)
        init_run_tracing(run_dir, get_tracing_config(), run_id=run_id)

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

    def _verify_with_retries(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        """Run verify targets with transient-flap retries (verify-only, no re-dispatch)."""
        return verify_with_retries(self.verifier, worktree_path, targets)

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
        return run_isolated_verify(
            verifier=self.verifier,
            repo_root=self.repo_root,
            runs_root=self.runs_root,
            run_id=run_id,
            node=node,
            implementer_worktree=implementer_worktree,
            commit_sha=commit_sha,
            targets=targets,
            transcript=transcript,
        )

    async def _run_quality_gauntlet(
        self,
        *,
        run_id: str,
        node: WaveNode,
        worktree: Worktree,
        outcome: dict[str, object],
    ) -> tuple[bool, str]:
        """Run optional quality inner loop before isolated verify (D26-D28)."""
        return await run_quality_gauntlet(
            adapter=self.adapter,
            repo_root=self.repo_root,
            runs_root=self.runs_root,
            last_checkpoint_sha=self._last_checkpoint_sha,
            run_id=run_id,
            node=node,
            worktree=worktree,
            outcome=outcome,
        )

    def _scaffold_w0_worktrees(self, run_id: str, graph: RunGraph) -> None:
        _scaffold_w0_worktrees_impl(self, run_id, graph)

    async def _drive_via_outer_loop(
        self, run_id: str, graph: RunGraph, *, run_bag: dict[str, Any] | None = None
    ) -> RunResult:
        return await _drive_via_outer_loop_impl(self, run_id, graph, run_bag=run_bag)

    async def _drive(self, run_id: str, graph: RunGraph) -> RunResult:
        return await _drive_impl(self, run_id, graph)

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
        return append_external_upload_dirs(brief, worktree_path)

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
        return brief_for(
            run_id=run_id,
            graph=graph,
            node=node,
            worktree=worktree,
            prior_failures=prior_failures,
            repo_root=self.repo_root,
            runs_root=self.runs_root,
            role_dispatch_effective=self._role_dispatch_effective,
            grep_brief=self._grep_brief,
            wave_commit_shas=self._wave_commit_shas,
            pools=self._pools,
            default_provider=self._default_provider,
            last_checkpoint_sha=self._last_checkpoint_sha,
            attempt=attempt,
        )

    def _pause_requested(self, run_id: str) -> bool:
        return _pause_requested_impl(self, run_id)

    def _write_pre0_sheet(self, run_id: str, graph: RunGraph) -> None:
        _write_pre0_sheet_impl(self, run_id, graph)

    def _write_escalation(
        self, run_id: str, blocked: list[str], results: dict[str, NodeResult]
    ) -> None:
        _write_escalation_impl(self, run_id, blocked, results)

    def _write_quota_pause(self, run_id: str, node_id: str, evidence: str, backend: str) -> None:
        _write_quota_pause_impl(self, run_id, node_id, evidence, backend)

    def _write_cost_pause(self, run_id: str, spent_usd: float) -> None:
        _write_cost_pause_impl(self, run_id, spent_usd)

    def _write_review_gate_pause(self, run_id: str, wave_id: str, gate_label: str) -> None:
        _write_review_gate_pause_impl(self, run_id, wave_id, gate_label)

    def _configure_orchestrator(self, graph: RunGraph, *, run_id: str) -> None:
        _configure_orchestrator_impl(self, graph, run_id=run_id)

    def _orchestrator_sync(
        self,
        run_id: str,
        graph: RunGraph,
        *,
        turn: OrchestratorTurn | None = None,
        lc: LedgerConnection | None = None,
    ) -> None:
        _orchestrator_sync_impl(self, run_id, graph, turn=turn, lc=lc)

    def _emit_orchestrator_event(
        self, run_id: str, turn: OrchestratorTurn, *, lc: LedgerConnection | None = None
    ) -> None:
        _emit_orchestrator_event_impl(self, run_id, turn, lc=lc)

    def _update_orchestrator_row(
        self,
        wave_id: str,
        *,
        status: str,
        branch: str | None = None,
        commit: str = "—",
        evidence: str = "",
    ) -> None:
        _update_orchestrator_row_impl(
            self, wave_id, status=status, branch=branch, commit=commit, evidence=evidence
        )

    def _orchestrator_commit_subject(self, cfg: OrchestratorConfig, wave_id: str) -> str:
        return _orchestrator_commit_subject_impl(self, cfg, wave_id)

    def _orchestrator_commit_wave(
        self, run_id: str, graph: RunGraph, node: WaveNode, worktree: Worktree
    ) -> tuple[bool, str]:
        return _orchestrator_commit_wave_impl(self, run_id, graph, node, worktree)

    def _cost_budget_exceeded(self, lc: LedgerConnection, run_id: str) -> bool:
        return _cost_budget_exceeded_impl(self, lc, run_id)

    def _init_run_wall_clock(self, graph: RunGraph) -> None:
        _init_run_wall_clock_impl(self, graph)

    def _load_check_runs_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return _load_check_runs_for_run_impl(self, run_id)

    def _external_event_state(self, run_id: str) -> tuple[str, str]:
        return _external_event_state_impl(self, run_id)

    def _build_exit_eval_context(
        self,
        lc: LedgerConnection,
        run_id: str,
        *,
        node: WaveNode | None = None,
        turn_hashes: list[str] | None = None,
        outcome_satisfied: bool = False,
        ci_green: bool = False,
        record: bool = True,
    ) -> dict[str, Any]:
        return _build_exit_eval_context_impl(
            self,
            lc,
            run_id,
            node=node,
            turn_hashes=turn_hashes,
            outcome_satisfied=outcome_satisfied,
            ci_green=ci_green,
            record=record,
        )

    def _evaluate_engine_exit(
        self, exit_id: int, lc: LedgerConnection, run_id: str, **extra: Any
    ) -> Any:
        return _evaluate_engine_exit_impl(self, exit_id, lc, run_id, **extra)

    def _scan_pre_dispatch_exits(self, lc: LedgerConnection, run_id: str) -> int | None:
        return _scan_pre_dispatch_exits_impl(self, lc, run_id)

    def _fire_goal_met_exit(
        self,
        lc: LedgerConnection,
        run_id: str,
        *,
        ci_green: bool,
        outcome_satisfied: bool,
    ) -> None:
        _fire_goal_met_exit_impl(
            self, lc, run_id, ci_green=ci_green, outcome_satisfied=outcome_satisfied
        )

    def _fire_error_threshold_exit(
        self,
        lc: LedgerConnection,
        run_id: str,
        *,
        node: WaveNode,
        failures: int,
    ) -> None:
        _fire_error_threshold_exit_impl(self, lc, run_id, node=node, failures=failures)

    async def drive_wave_batches(
        self,
        run_id: str,
        graph: RunGraph,
        *,
        run_bag: dict[str, Any] | None = None,
        record_validate_snapshot: bool = True,
        finalize_run: bool = True,
    ) -> RunResult:
        return await _drive_wave_batches_impl(
            self,
            run_id,
            graph,
            run_bag=run_bag,
            record_validate_snapshot=record_validate_snapshot,
            finalize_run=finalize_run,
        )

    async def _prepare_run_ledger(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        done: set[str],
        blocked: list[str],
        results: dict[str, NodeResult],
        *,
        record_validate_snapshot: bool,
    ) -> None:
        await _prepare_run_ledger_impl(
            self,
            lc,
            run_id,
            graph,
            done,
            blocked,
            results,
            record_validate_snapshot=record_validate_snapshot,
        )

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
        return await _handle_review_gate_impl(
            self,
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

    async def _drive_orchestrator_serial(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        done: set[str],
        blocked: list[str],
        results: dict[str, NodeResult],
    ) -> RunResult:
        return await _drive_orchestrator_serial_impl(
            self, lc, run_id, graph, done, blocked, results
        )

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
        return await _drain_batch_impl(self, lc, run_id, graph, batch_nodes, done, blocked, results)

    async def _run_concurrent_set(
        self,
        lc: LedgerConnection,
        run_id: str,
        graph: RunGraph,
        nodes: list[WaveNode],
    ) -> list[NodeResult]:
        return await _run_concurrent_set_impl(self, lc, run_id, graph, nodes)

    async def _shielded_finalize_wave_ledger(
        self, lc: LedgerConnection, run_id: str, node_id: str
    ) -> None:
        await _shielded_finalize_wave_ledger_impl(self, lc, run_id, node_id)

    async def _execute_node(
        self, lc: LedgerConnection, run_id: str, graph: RunGraph, node: WaveNode
    ) -> NodeResult:
        return await _execute_node_impl(self, lc, run_id, graph, node)
