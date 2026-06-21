"""tripll.orchestrator_gate -- headless wave-orchestrator review-gate dispatch (W4).

Exports:
    GateDecision -- parsed proceed/stop outcome from gate agent text.
    parse_gate_result -- keyword heuristics for gate agent responses.
    dispatch_orchestrator_gate -- invoke wave-orchestrator adapter at a review gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.adapters.base import AgentAdapter
    from tripll.graph import OrchestratorConfig


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Parsed outcome from a headless orchestrator gate dispatch.

    Args:
        proceed (bool): True when heuristics indicate the run may continue.
        summary (str): One-line summary for orchestrator-status / ledger.
        raw_text (str): Full agent result text.
    """

    proceed: bool
    summary: str
    raw_text: str


def parse_gate_result(text: str) -> GateDecision:
    """Parse gate agent *text* for proceed/stop (keyword heuristics v2).

    Priority order:

    1. **Structured token** -- ``DECISION: APPROVE`` or ``DECISION: STOP``
       (case-insensitive, allows surrounding whitespace/markdown).  Checked first;
       unambiguous and recommended for gate agents.
    2. **Explicit negatives** -- word-boundary ``stop``, ``reject``, ``disapprove``,
       or phrases ``do not proceed``, ``do not approve``, ``blocked`` -> stop.
    3. **Explicit positives** -- word-boundary ``approve`` / ``approved`` (not preceded
       by ``dis``) or ``dispatch W<n>`` -> proceed.
    4. **Ambiguous** -- defaults to **stop** (fail closed).

    Args:
        text (str): Agent result markdown or plain text.

    Returns:
        GateDecision: Parsed proceed flag and summary line.

    Examples:
        >>> parse_gate_result("DECISION: APPROVE").proceed
        True
        >>> parse_gate_result("DECISION: STOP").proceed
        False
        >>> parse_gate_result("I disapprove of this.").proceed
        False
        >>> parse_gate_result("Changes approved.").proceed
        True
    """
    raw = (text or "").strip()
    lower = raw.lower()
    summary = raw.splitlines()[0][:240] if raw else "empty gate response"

    # 1. Structured token -- highest priority, unambiguous.
    if re.search(r"DECISION\s*:\s*APPROVE", raw, re.IGNORECASE):
        return GateDecision(proceed=True, summary=summary, raw_text=raw)
    if re.search(r"DECISION\s*:\s*STOP", raw, re.IGNORECASE):
        return GateDecision(proceed=False, summary=summary, raw_text=raw)

    # 2. Explicit negatives -- checked before positives so "disapprove" is safe.
    _stop_patterns = (
        r"\bstop\b",
        r"\breject\b",
        r"\bdisapprove\b",
        r"do not proceed",
        r"do not approve",
        r"\bblocked\b",
    )
    for pat in _stop_patterns:
        if re.search(pat, lower):
            return GateDecision(proceed=False, summary=summary, raw_text=raw)

    # 3. Explicit positives -- word-boundary approve/approved (not preceded by "dis").
    if re.search(r"(?<!dis)\bapproved?\b", lower):
        return GateDecision(proceed=True, summary=summary, raw_text=raw)
    if re.search(r"dispatch\s+W\d", raw, re.IGNORECASE):
        return GateDecision(proceed=True, summary=summary, raw_text=raw)

    # 4. Ambiguous -> fail closed.
    return GateDecision(proceed=False, summary=summary, raw_text=raw)


def _render_gate_brief(
    prompt: str,
    context: dict[str, object],
    *,
    orchestrator: OrchestratorConfig,
) -> dict[str, object]:
    wave_id = str(context.get("wave_id", ""))
    gate_label = str(context.get("gate_label", ""))
    wave_summary = str(context.get("wave_summary", ""))
    feature_branch = orchestrator.feature_branch or str(context.get("branch", ""))
    lines = [
        f"Orchestrator gate mode -- **{gate_label or wave_id}** complete.",
        "",
        prompt.strip(),
        "",
        f"Wave: {wave_id}",
        f"Branch: {feature_branch}",
    ]
    if wave_summary.strip():
        lines += ["", "Wave summary:", wave_summary.strip()]
    lines += [
        "",
        "Present operator summary, set AWAITING REVIEW, list sign-off items.",
        "Do **not** dispatch the next wave-runner.",
        "Reply with **approve** to continue or **STOP** if blockers remain.",
        "",
        "End your reply with exactly one of these lines:",
        "  DECISION: APPROVE",
        "  DECISION: STOP",
    ]
    return {
        "node_id": "orchestrator-gate",
        "wave_id": wave_id,
        "plan_worktree_path": str(context.get("plan_path", "")),
        "branch": feature_branch,
        "worktree_path": str(context.get("worktree_path", "")),
        "owned_paths": [],
        "forbidden_paths": [],
        "verify_targets": [],
        "prerequisite_waves": [],
        "workspace_scope": [],
        "agent_directives": [
            "Gate-only mode: summarise evidence; do not implement product code.",
            "Do not dispatch wave-runner.",
        ],
        "agent": orchestrator.agent_orchestrator,
        "gate_prompt": "\n".join(lines),
    }


async def dispatch_orchestrator_gate(
    run_dir: Path,
    prompt: str,
    context: dict[str, object],
    *,
    adapter: AgentAdapter,
    orchestrator: OrchestratorConfig,
    worktree_path: Path,
    timeout_s: int = 600,
) -> GateDecision:
    """Headless invoke ``wave-orchestrator`` at a review gate (W4.3).

    Writes gate log under ``run_dir/logs/orchestrator-gate.log`` and returns
    a :class:`GateDecision` from :func:`parse_gate_result`.

    Args:
        run_dir (Path): Run directory (``runs/.../<run-id>/``).
        prompt (str): Condensed gate brief (e.g. ``W0.8 complete -- present summary, STOP``).
        context (dict[str, object]): Gate context -- ``wave_id``, ``gate_label``,
            ``wave_summary``, ``worktree_path``, ``branch``, ``plan_path``.
        adapter (AgentAdapter): Backend adapter configured with
            ``agent=wave-orchestrator``.
        orchestrator (OrchestratorConfig): Active orchestrator config.
        worktree_path (Path): Worktree checkout for the adapter CLI.
        timeout_s (int): Wall-clock timeout for the gate dispatch.

    Returns:
        GateDecision: Parsed proceed/stop decision.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dispatch_orchestrator_gate)
        True
    """
    brief = _render_gate_brief(prompt, context, orchestrator=orchestrator)
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "orchestrator-gate.log"

    dispatch_brief = dict(brief)
    dispatch_brief["_prompt_override"] = str(brief.get("gate_prompt", prompt))

    result = await adapter.dispatch(
        dispatch_brief,
        worktree_path=worktree_path,
        log_path=log_path,
        timeout_s=timeout_s,
        log_header={
            "run_id": run_dir.name,
            "node_id": "orchestrator-gate",
            "backend": adapter.name,
        },
    )
    text = result.result_text or ""
    decision = parse_gate_result(text)
    if result.outcome != "done":
        return GateDecision(
            proceed=False,
            summary=f"gate dispatch {result.outcome}: {decision.summary}",
            raw_text=text,
        )
    return decision
