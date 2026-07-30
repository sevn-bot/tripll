"""Pre-0 human gate helpers extracted from :mod:`tripll.engine`.

Exports:
    complete_human_gate_waves — mark human-gate waves done after Pre-0 approve.
    _resolve_grep_brief — default graph-packed briefs when kg extra is installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from tripll.engine_scheduling import human_gate_node_ids
from tripll.ledger import LedgerConnection, append_event, get_wave, transition_wave

if TYPE_CHECKING:
    from tripll.graph import RunGraph


def _resolve_grep_brief(grep_brief: bool | None) -> bool:
    """Default graph-packed briefs when the kg extra is installed (P2.3)."""
    if grep_brief is not None:
        return grep_brief
    from tripll.plan.code_graph import kg_extra_available

    return not kg_extra_available()


def complete_human_gate_waves(
    lc: LedgerConnection,
    run_id: str,
    graph: RunGraph,
    *,
    done: set[str],
    blocked: list[str],
    results: dict[str, Any],
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
    from tripll.engine import NodeResult

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
