"""L1 PR fix loop - push, poll, investigate, fix, merge gate (section 8 ph.10-12).

The conditional cycle: push → poll checks + comments → dispatch investigator /
triager → dispatch fixer → re-verify → poll again → escalate or park at the
merge gate. Fan-out dispatches one investigator+fixer chain per open finding.

Exports:
    PR_NODES — ordered node names for the PR LangGraph cycle.
    MERGE_GATE_MARKER — run-dir marker when parked at the human merge gate.
    MERGE_APPROVED_MARKER — operator approval before ``merge`` may run.
    run_pr_loop_step — one PR-loop step (investigate/fix or merge gate).
    evaluate_pr_exits — wire budget, deadline, no-progress, error, external exits.
    build_l1_pr_graph — compile-ready StateGraph builder.
    compile_l1_pr_graph — compiled graph with checkpointer + merge interrupt.
    park_at_merge_gate — write merge-gate marker and return gate state.
    approve_merge_gate — record human merge approval (never auto-merge).
    pr_status — read PR phase state for CLI/API.
    shepherd_run — run one PR shepherd step for a run directory.
    pr_checkpoint_db_path — SQLite checkpoint path for the PR LangGraph loop.
    load_open_findings — open findings from the repo graph store.
    integration_branch_for_run — integration branch name for a run-id.
    render_deliver_dry_run — printable deliver plan (no side effects).
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from tripll.loops.exits import evaluate_exit
from tripll.loops.state import L1OuterState, graph_delta_hash

PR_NODES: tuple[str, ...] = (
    "push",
    "poll",
    "investigate",
    "fix",
    "re_verify",
    "merge_gate",
)

MERGE_GATE_MARKER = "merge-gate-pending"
MERGE_APPROVED_MARKER = "merge-approved"

_AGENT_CHAINS: dict[str, tuple[str, str]] = {
    "ci_check": ("ci-investigator", "check-fixer"),
    "review_comment": ("review-comment-triager", "review-comment-fixer"),
}

PR_CHECKPOINT_FILENAME = "pr-checkpoints.db"

__all__ = [
    "MERGE_APPROVED_MARKER",
    "MERGE_GATE_MARKER",
    "PR_CHECKPOINT_FILENAME",
    "PR_NODES",
    "approve_merge_gate",
    "build_l1_pr_graph",
    "compile_l1_pr_graph",
    "evaluate_pr_exits",
    "load_open_findings",
    "park_at_merge_gate",
    "pr_checkpoint_db_path",
    "pr_status",
    "run_pr_loop_step",
    "shepherd_run",
]


def _open_findings(findings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [f for f in (findings or []) if f.get("state") == "open"]


def _state_findings(state: L1OuterState) -> list[dict[str, Any]]:
    raw = state.get("findings")
    if isinstance(raw, list):
        return raw
    return []


def _state_run_dir(state: L1OuterState) -> Path | str | None:
    raw = state.get("run_dir")
    if isinstance(raw, (Path, str)):
        return raw
    return None


def run_pr_loop_step(
    *,
    findings: list[dict[str, Any]] | None = None,
    phase: str = "investigate_and_fix",
    ci_green: bool = False,
    review_clean: bool = False,
    run_dir: Path | str | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Return the next PR-loop actions or merge-gate state.

    Args:
        findings (list[dict[str, Any]] | None): Open findings driving the loop.
        phase (str): ``investigate_and_fix``, ``merge``, or ``deliver``.
        ci_green (bool): Whether CI is green (merge phase).
        review_clean (bool): Whether review is clean (merge phase).
        run_dir (Path | str | None): Run directory for merge-gate markers.

    Returns:
        dict[str, Any] | list[dict[str, Any]]: Step plan or merge-gate result.
    """
    if phase == "merge":
        return park_at_merge_gate(
            run_dir=run_dir,
            ci_green=ci_green,
            review_clean=review_clean,
        )

    if phase == "deliver":
        return [
            {"node": "push", "action": "push", "agent": "pr-shepherd"},
            {"node": "open_pr", "action": "open_pr", "agent": "pr-shepherd"},
        ]

    steps: list[dict[str, Any]] = []
    for finding in _open_findings(findings):
        kind = str(finding.get("kind") or "ci_check")
        investigator, fixer = _AGENT_CHAINS.get(kind, _AGENT_CHAINS["ci_check"])
        finding_id = finding.get("finding_id") or finding.get("id")
        steps.append(
            {
                "agent": investigator,
                "action": "investigate",
                "finding_id": finding_id,
                "kind": kind,
            }
        )
        steps.append(
            {
                "agent": fixer,
                "action": "fix",
                "finding_id": finding_id,
                "kind": kind,
            }
        )
    # Optional mergeCraft mode dispatch when [review].posture != review_only.
    mergecraft_steps = _maybe_mergecraft_dispatch(findings, run_dir=run_dir)
    if mergecraft_steps:
        steps.extend(mergecraft_steps)
    return steps


def _maybe_mergecraft_dispatch(
    findings: list[dict[str, Any]] | None,
    *,
    run_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Queue mergeCraft workflow_dispatch receipts when posture allows.

    Default ``review_only`` returns []. When posture is ``fix`` or ``full``,
    accepted/open review_comment findings map to AddressReviews and ci_check
    findings map to Fix — via ``gh workflow run`` with an ADR-004 receipt.
    """
    from tripll.config import load_config
    from tripll.review import dispatch_mode

    cfg = load_config()
    if not cfg.review.allows_mode_dispatch():
        return []

    open_findings = _open_findings(findings)
    if not open_findings:
        return []

    # Prefer a PR number from finding evidence / source when present.
    pr_number = 0
    for finding in open_findings:
        for key in ("pr_number", "pr"):
            val = finding.get(key)
            if val is not None:
                with suppress(TypeError, ValueError):
                    pr_number = int(val)
                    break
        if pr_number:
            break

    kinds = {str(f.get("kind") or "") for f in open_findings}
    mode = "AddressReviews" if "review_comment" in kinds else "Fix"
    brief_lines = []
    for finding in open_findings[:12]:
        fid = finding.get("finding_id") or "?"
        msg = (finding.get("message_raw") or finding.get("rule_id") or "")[:200]
        brief_lines.append(f"- {fid}: {msg}")
    prompt = f"Address open findings on PR #{pr_number or '?'}.\n" + "\n".join(brief_lines)
    receipt: Path | None = None
    if run_dir is not None:
        receipt = Path(run_dir) / "receipts" / f"mergecraft-{mode.lower()}.json"
    result = dispatch_mode(
        pr=pr_number or 0,
        mode=mode,
        prompt=prompt,
        workflow=cfg.review.workflow,
        review=cfg.review,
        receipt_path=receipt,
    )
    return [
        {
            "agent": "pr-shepherd",
            "action": "mergecraft_dispatch",
            "mode": mode,
            "result": result,
        }
    ]


def evaluate_pr_exits(context: dict[str, Any] | None = None) -> list[Any]:
    """Evaluate PR-cycle exits (3 budget, 4 deadline, 5 no-progress, 7 errors, 8 external)."""
    ctx = dict(context or {})
    fired: list[Any] = []
    for exit_id in (8, 3, 4, 5, 7):
        result = evaluate_exit(exit_id, ctx)
        if result.fired:
            fired.append(result)
    return fired


def park_at_merge_gate(
    *,
    run_dir: Path | str | None = None,
    ci_green: bool = False,
    review_clean: bool = False,
) -> dict[str, Any]:
    """Park the run at the human merge gate — never auto-merge."""
    if run_dir is not None:
        path = Path(run_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / MERGE_GATE_MARKER).write_text(
            json.dumps(
                {
                    "ci_green": ci_green,
                    "review_clean": review_clean,
                    "merged": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    return {
        "state": "merge_gate_pending",
        "merged": False,
        "ci_green": ci_green,
        "review_clean": review_clean,
        "interrupt": True,
    }


def approve_merge_gate(*, run_dir: Path | str) -> Path:
    """Record operator approval for merge — required before ``merge`` runs."""
    path = Path(run_dir)
    pending = path / MERGE_GATE_MARKER
    if not pending.is_file():
        msg = f"merge gate not pending for {run_dir}"
        raise FileNotFoundError(msg)
    approved = path / MERGE_APPROVED_MARKER
    approved.write_text(json.dumps({"approved": True}, sort_keys=True), encoding="utf-8")
    return approved


def pr_status(*, run_dir: Path | str) -> dict[str, Any]:
    """Return PR phase markers and gate state for a run directory."""
    path = Path(run_dir)
    pending_path = path / MERGE_GATE_MARKER
    approved_path = path / MERGE_APPROVED_MARKER
    payload: dict[str, Any] = {
        "merge_gate_pending": pending_path.is_file(),
        "merge_approved": approved_path.is_file(),
        "state": "running",
    }
    if pending_path.is_file():
        with suppress(json.JSONDecodeError):
            payload.update(json.loads(pending_path.read_text(encoding="utf-8")))
        payload["state"] = "merge_approved" if approved_path.is_file() else "merge_gate_pending"
    return payload


def _dispatch_for_finding(finding: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(finding.get("kind") or "ci_check")
    investigator, fixer = _AGENT_CHAINS.get(kind, _AGENT_CHAINS["ci_check"])
    finding_id = finding.get("finding_id") or finding.get("id")
    return [
        {
            "agent": investigator,
            "action": "investigate",
            "finding_id": finding_id,
            "kind": kind,
        },
        {
            "agent": fixer,
            "action": "fix",
            "finding_id": finding_id,
            "kind": kind,
        },
    ]


def _carry_loop_context(state: L1OuterState) -> dict[str, Any]:
    """Preserve run metadata and findings across node partial updates."""
    carried: dict[str, Any] = {}
    for key in (
        "run_id",
        "thread_id",
        "run_dir",
        "findings",
        "ci_green",
        "review_clean",
    ):
        value = state.get(key)
        if value is not None:
            carried[key] = value
    return carried


def _node_push(state: L1OuterState) -> L1OuterState:
    from tripll.github import pr as github_pr

    run_id = str(state.get("run_id") or state.get("thread_id") or "default")
    key = f"push:{run_id}"
    push_result = github_pr.push(idempotency_key=key, context={"run_id": run_id})
    result_payload = push_result.get("result") or {}
    delta = graph_delta_hash({"node": "push", "run_id": run_id})
    out: dict[str, Any] = {
        "step": "push",
        "history": ["push"],
        "graph_delta_hash": delta,
        "turn_hashes": [delta],
    }
    if push_result.get("dry_run") or result_payload.get("dry_run"):
        out["dry_run"] = True
        out["push_warning"] = (
            "TRIPLL_PR_DRY_RUN=1 — push recorded but no git remote mutation occurred"
        )
    out.update(_carry_loop_context(state))
    return cast("L1OuterState", out)


def _node_poll(state: L1OuterState) -> L1OuterState:
    findings = _state_findings(state)
    run_dir = _state_run_dir(state)
    run_id = str(state.get("run_id") or state.get("thread_id") or "")
    if run_dir is not None and run_id:
        run_graph_db = Path(run_dir) / ".tripll" / "graph.db"
        if run_graph_db.is_file():
            findings = load_open_findings(run_dir=Path(run_dir), run_id=run_id)
    open_count = len(_open_findings(findings))
    delta = graph_delta_hash({"node": "poll", "open": open_count})
    return cast(
        "L1OuterState",
        {
            "step": "poll",
            "history": ["poll"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            **_carry_loop_context(state),
            "findings": findings,
            "open_findings": open_count,
        },
    )


def _node_investigate(state: L1OuterState) -> L1OuterState:
    from tripll.loops.dispatch_bridge import dispatch_results_as_dicts, invoke_loop_dispatches

    findings = _state_findings(state)
    dispatch = [_dispatch_for_finding(f)[0] for f in _open_findings(findings)]
    results = invoke_loop_dispatches(state, dispatch, node="investigate")
    delta = graph_delta_hash(
        {"node": "investigate", "dispatch": dispatch, "outcomes": [r.outcome for r in results]}
    )
    return cast(
        "L1OuterState",
        {
            "step": "investigate",
            "history": ["investigate"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            "dispatch": dispatch,
            "dispatch_results": dispatch_results_as_dicts(results),
            **_carry_loop_context(state),
        },
    )


def _node_fix(state: L1OuterState) -> L1OuterState:
    from tripll.loops.dispatch_bridge import dispatch_results_as_dicts, invoke_loop_dispatches

    findings = _state_findings(state)
    dispatch = [_dispatch_for_finding(f)[1] for f in _open_findings(findings)]
    results = invoke_loop_dispatches(state, dispatch, node="fix")
    delta = graph_delta_hash(
        {"node": "fix", "dispatch": dispatch, "outcomes": [r.outcome for r in results]}
    )
    return cast(
        "L1OuterState",
        {
            "step": "fix",
            "history": ["fix"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            "dispatch": dispatch,
            "dispatch_results": dispatch_results_as_dicts(results),
            **_carry_loop_context(state),
        },
    )


def _node_re_verify(state: L1OuterState) -> L1OuterState:
    delta = graph_delta_hash({"node": "re_verify"})
    return cast(
        "L1OuterState",
        {
            "step": "re_verify",
            "history": ["re_verify"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            **_carry_loop_context(state),
        },
    )


def _node_merge_gate(state: L1OuterState) -> L1OuterState:
    gate = park_at_merge_gate(
        run_dir=_state_run_dir(state),
        ci_green=bool(state.get("ci_green")),
        review_clean=bool(state.get("review_clean")),
    )
    delta = graph_delta_hash({"node": "merge_gate", **gate})
    return cast(
        "L1OuterState",
        {
            "step": "merge_gate",
            "history": ["merge_gate"],
            "graph_delta_hash": delta,
            "turn_hashes": [delta],
            "merge_gate": gate,
            "paused": True,
            **_carry_loop_context(state),
        },
    )


def _route_after_poll(state: L1OuterState) -> str:
    if _open_findings(_state_findings(state)):
        return "investigate"
    return "merge_gate"


def _route_after_re_verify(state: L1OuterState) -> str:
    if _open_findings(_state_findings(state)):
        return "poll"
    return "merge_gate"


def build_l1_pr_graph() -> Any:
    """Build the PR fix-loop ``StateGraph`` (uncompiled)."""
    from tripll.loops import require_graph

    require_graph(feature="L1 PR loop")
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(L1OuterState)
    graph.add_node("push", cast("Any", _node_push))
    graph.add_node("poll", cast("Any", _node_poll))
    graph.add_node("investigate", cast("Any", _node_investigate))
    graph.add_node("fix", cast("Any", _node_fix))
    graph.add_node("re_verify", cast("Any", _node_re_verify))
    graph.add_node("merge_gate", cast("Any", _node_merge_gate))

    graph.add_edge(START, "push")
    graph.add_edge("push", "poll")
    graph.add_conditional_edges("poll", _route_after_poll, ["investigate", "merge_gate"])
    graph.add_edge("investigate", "fix")
    graph.add_edge("fix", "re_verify")
    graph.add_conditional_edges("re_verify", _route_after_re_verify, ["poll", "merge_gate"])
    graph.add_edge("merge_gate", END)
    return graph


def pr_checkpoint_db_path(run_dir: Path) -> Path:
    """Return the PR-loop LangGraph checkpoint database for *run_dir*.

    Args:
        run_dir (Path): ``processing/<run-id>/`` directory.

    Returns:
        Path: SQLite checkpoint path (separate from outer-loop checkpoints).
    """
    return run_dir / PR_CHECKPOINT_FILENAME


def load_open_findings(*, run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Load open findings for *run_id* from the repo graph store.

    Args:
        run_dir (Path): Active run directory.
        run_id (str): Parent run identifier.

    Returns:
        list[dict[str, Any]]: Open finding dicts (empty when graph store absent).
    """
    from tripll.api._l1_panels import resolve_graph_db
    from tripll.github.findings import list_findings_from_store
    from tripll.graphstore import SqliteGraphStore
    from tripll.repo_root import resolve_repo_root

    db_path = resolve_graph_db(run_dir=run_dir, repo_root=resolve_repo_root())
    if db_path is None:
        return []
    store = SqliteGraphStore(str(db_path))
    try:
        rows = list_findings_from_store(store, state="open")
        return [finding for finding in rows if finding.get("run_id") in (None, "", run_id)]
    finally:
        store.close()


def integration_branch_for_run(run_id: str) -> str:
    """Return the integration branch name used by ``--integrate``.

    Args:
        run_id (str): Parent run identifier.

    Returns:
        str: Branch name ``tripll/integrate/<run-id>``.
    """
    return f"tripll/integrate/{run_id}"


def deliver_idempotency_key(action: str, run_id: str) -> str:
    """Stable idempotency key for a deliver-phase PR action.

    Args:
        action (str): ``push`` or ``open_pr``.
        run_id (str): Parent run identifier.

    Returns:
        str: Key written before any external side effect.
    """
    return f"{action}:{run_id}"


def render_deliver_dry_run(*, run_id: str, integration_branch: str | None = None) -> list[str]:
    """Format the post-integrate deliver plan as printable lines (no side effects).

    Args:
        run_id (str): Parent run identifier.
        integration_branch (str | None): Push/open head branch (defaults to integrate branch).

    Returns:
        list[str]: Lines describing push, open_pr keys, and the human merge gate.
    """
    branch = integration_branch or integration_branch_for_run(run_id)
    return [
        f"[deliver] Branch    : {branch}",
        f"[deliver] push      : idempotency_key={deliver_idempotency_key('push', run_id)}",
        f"[deliver] open_pr   : idempotency_key={deliver_idempotency_key('open_pr', run_id)}",
        "[deliver] merge     : human gate — tripll pr approve-merge (never auto-merge)",
    ]


def _deliver_context(*, run_id: str, run_dir: Path) -> dict[str, Any]:
    """Build GitHub action context for the deliver phase."""
    from tripll.repo_root import resolve_repo_root

    branch = integration_branch_for_run(run_id)
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "repo_root": str(resolve_repo_root()),
        "branch": branch,
        "head": branch,
    }


def _run_deliver_phase(*, run_id: str, run_dir: Path) -> dict[str, Any]:
    """Execute idempotent push and open_pr for the deliver phase."""
    from tripll.github import pr as github_pr

    ctx = _deliver_context(run_id=run_id, run_dir=run_dir)
    actions: list[dict[str, Any]] = []
    for action in ("push", "open_pr"):
        key = deliver_idempotency_key(action, run_id)
        outcome = github_pr.run_pr_action(
            action,
            idempotency_key=key,
            context=ctx,
        )
        actions.append({"action": action, **outcome})
    return {"phase": "deliver", "actions": actions}


def _format_graph_result(
    *,
    phase: str,
    values: dict[str, Any],
    next_nodes: tuple[str, ...],
) -> dict[str, Any]:
    """Shape LangGraph state into a shepherd CLI payload."""
    paused = bool(values.get("paused")) or "merge_gate" in next_nodes
    return {
        "phase": phase,
        "step": values.get("step"),
        "history": list(values.get("history") or []),
        "dispatch": values.get("dispatch"),
        "dispatch_results": values.get("dispatch_results"),
        "merge_gate": values.get("merge_gate"),
        "open_findings": values.get("open_findings"),
        "dry_run": values.get("dry_run"),
        "push_warning": values.get("push_warning"),
        "next": list(next_nodes),
        "paused": paused,
        "graph_executed": True,
    }


def _stream_graph(app: Any, cfg: dict[str, Any], seed: L1OuterState | None) -> None:
    """Run the compiled graph via ``stream`` (``invoke(None)`` does not resume ``interrupt_after``)."""
    if seed is not None:
        for _ in app.stream(seed, cfg):
            pass
    else:
        for _ in app.stream(None, cfg):
            pass


def _invoke_pr_graph(
    *,
    run_id: str,
    run_dir: Path,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile and invoke the PR LangGraph loop for one shepherd step."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    from tripll.loops import require_graph

    require_graph(feature="L1 PR loop shepherd")

    db_path = pr_checkpoint_db_path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(db_path)) as cp:
        app = compile_l1_pr_graph(cp, interrupt_after=["re_verify"])
        cfg: dict[str, Any] = {
            "configurable": {"thread_id": run_id},
            "durability": "sync",
        }
        prior = app.get_state(cfg)
        if prior.next:
            _stream_graph(app, cfg, None)
        elif prior.values and prior.values.get("step"):
            values = dict(prior.values)
            return _format_graph_result(
                phase="investigate_and_fix",
                values=values,
                next_nodes=tuple(prior.next or ()),
            )
        else:
            seed: L1OuterState = {
                "run_id": run_id,
                "thread_id": run_id,
                "run_dir": str(run_dir),
                "findings": findings,
                "history": [],
            }
            _stream_graph(app, cfg, seed)
        snapshot = app.get_state(cfg)
        values = dict(snapshot.values or {})
        next_nodes = tuple(snapshot.next or ())
        return _format_graph_result(
            phase="investigate_and_fix",
            values=values,
            next_nodes=next_nodes,
        )


def compile_l1_pr_graph(
    checkpointer: Any,
    *,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
) -> Any:
    """Compile the PR loop with durable checkpointing and optional interrupts."""
    from tripll.loops import require_graph

    require_graph(feature="L1 PR loop")
    from langgraph.types import RetryPolicy

    sg = build_l1_pr_graph()
    default_retry = RetryPolicy(max_attempts=5, initial_interval=0.5)
    sg.set_node_defaults(retry_policy=default_retry)
    return sg.compile(
        checkpointer=checkpointer,
        interrupt_before=list(interrupt_before or []),
        interrupt_after=list(interrupt_after or []),
    )


def shepherd_run(
    *,
    run_id: str,
    run_dir: Path,
    findings: list[dict[str, Any]] | None = None,
    phase: str = "investigate_and_fix",
) -> dict[str, Any] | list[dict[str, Any]]:
    """Run one PR shepherd step for *run_id* (CLI/API entry).

    ``deliver`` executes idempotent push/open actions. ``investigate_and_fix``
    compiles and invokes :func:`compile_l1_pr_graph` so investigate/fix nodes
    dispatch real adapters (D15 merge-gate interrupt — never auto-merge).
    """
    ctx: dict[str, Any] = {"run_id": run_id, "run_dir": str(run_dir)}
    exits = evaluate_pr_exits(ctx)
    if exits:
        first = exits[0]
        return {
            "state": "abandoned",
            "exit_id": first.exit_id,
            "exit_name": first.name,
            "abandon_run": first.abandon_run,
        }

    if phase == "merge":
        return park_at_merge_gate(run_dir=run_dir)

    if phase == "deliver":
        return _run_deliver_phase(run_id=run_id, run_dir=run_dir)

    if phase == "investigate_and_fix":
        loaded = (
            findings if findings is not None else load_open_findings(run_dir=run_dir, run_id=run_id)
        )
        return _invoke_pr_graph(run_id=run_id, run_dir=run_dir, findings=loaded)

    return run_pr_loop_step(findings=findings, phase=phase, run_dir=run_dir)
