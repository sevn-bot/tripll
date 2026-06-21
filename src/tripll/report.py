"""tripll.report — per-run ``report.md`` generation.

Renders a Markdown summary of run progress: batch status, every wave's state,
the active wave (when dispatching), escalations, and deferred/manual items.
``sync_report`` rebuilds from the SQLite ledger so ``report.md`` stays current
on resume, status, and during dispatch.

Exports:
    build_report — pure Markdown builder from a graph + node results.
    write_report — write ``report.md`` into a run directory.
    sync_report — refresh ``report.md`` from ledger + optional in-flight context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.engine import NodeResult
    from tripll.graph import Batch, RunGraph

_MANUAL_DEFERRED = "Cloud live dispatch + poll loop (deferred-manual; dispatch-only default D2)"
_IN_FLIGHT = frozenset({"dispatched", "running", "verifying"})


def _nodes_in_batch(graph: RunGraph, batch: Batch) -> list[str]:
    out: list[str] = []
    for wid in batch.wave_ids:
        for nid, node in graph.nodes.items():
            if node.wave_id == wid and nid not in out:
                out.append(nid)
    return out


def _batch_status(
    graph: RunGraph,
    batch: Batch,
    node_states: dict[str, str],
    *,
    pre0_approved: bool,
) -> str:
    if batch.is_human_gate:
        return "approved" if pre0_approved else "pending approval"
    nodes = _nodes_in_batch(graph, batch)
    if not nodes:
        return "—"
    states = [node_states.get(n, "queued") for n in nodes]
    if any(s == "blocked" for s in states):
        return "blocked"
    if any(s in _IN_FLIGHT for s in states):
        return "in progress"
    if all(s == "done" for s in states):
        return "done"
    if any(s == "done" for s in states):
        return "partial"
    return "pending"


def _orchestrator_section(run_dir: Path) -> str:
    """Build ``## Orchestrator`` block when ``orchestrator-status.md`` exists (W3)."""
    from tripll.orchestrator_status import read_latest, render_status_table

    status_path = run_dir / "orchestrator-status.md"
    if not status_path.is_file():
        return ""
    snap = read_latest(run_dir)
    if not snap.rows and not snap.turns:
        return ""
    parts = [
        "## Orchestrator",
        "",
        "Full status: [`orchestrator-status.md`](orchestrator-status.md)",
        "",
    ]
    if snap.rows:
        parts.append(render_status_table(snap.rows[:5]))
        parts.append("")
    return "\n".join(parts)


def build_report(
    graph: RunGraph,
    *,
    run_id: str,
    state: str,
    results: dict[str, NodeResult],
    run_location: str | None = None,
    current_node_id: str | None = None,
    pre0_approved: bool = False,
    updated_at: str | None = None,
    cost_usd: float | None = None,
    orchestrator_section: str = "",
) -> str:
    """Build the ``report.md`` body for a run.

    Args:
        graph (RunGraph): The parsed run graph.
        run_id (str): Run identifier.
        state (str): Run state (``active``, ``paused``, ``failed``, ``done``, …).
        results (dict[str, NodeResult]): node_id → wave status snapshot.
        run_location (str | None): ``processing`` / ``failed`` / ``processed`` folder name.
        current_node_id (str | None): Wave being dispatched right now.
        pre0_approved (bool): Whether the Pre-0 marker exists.
        updated_at (str | None): Human-readable last-update timestamp.
        orchestrator_section (str): Pre-rendered ``## Orchestrator`` block (W3).

    Returns:
        str: Markdown report text.

    Examples:
        >>> from tripll.graph import RunGraph
        >>> txt = build_report(RunGraph(run_id="r"), run_id="r", state="done", results={})
        >>> "# Run report — r" in txt
        True
    """
    node_states = {nid: nr.state for nid, nr in results.items()}
    done = [nid for nid, nr in results.items() if nr.state == "done"]
    escalated = [nid for nid, nr in results.items() if nr.state == "blocked"]
    impl_nodes = [
        nid
        for batch in graph.batches
        if not batch.is_human_gate
        for nid in _nodes_in_batch(graph, batch)
    ]
    impl_done = sum(1 for nid in impl_nodes if node_states.get(nid) == "done")

    loc = f" ({run_location}/)" if run_location else ""
    lines: list[str] = [
        f"# Run report — {run_id}",
        "",
        f"- **State:** {state}{loc}",
        f"- **Source mode:** {graph.source_mode}",
        f"- **Progress:** {impl_done}/{len(impl_nodes)} implementation waves done",
        f"- **Waves:** {len(graph.nodes)} total ({len(done)} done, {len(escalated)} blocked)",
    ]
    if updated_at:
        lines.append(f"- **Updated:** {updated_at}")
    if cost_usd is not None and cost_usd > 0:
        lines.append(f"- **Cost (USD):** ${cost_usd:.4f}")
    if current_node_id:
        cur_state = node_states.get(current_node_id, "active")
        lines.append(f"- **Current wave:** `{current_node_id}` — {cur_state}")
    lines.append("")

    lines += ["## Batches", ""]
    for batch in graph.batches:
        status = _batch_status(graph, batch, node_states, pre0_approved=pre0_approved)
        waves = ", ".join(batch.wave_ids) if batch.wave_ids else "—"
        kind = "human gate" if batch.is_human_gate else "batch"
        marker = (
            " **← active**"
            if current_node_id and current_node_id in _nodes_in_batch(graph, batch)
            else ""
        )
        lines.append(
            f"- **{batch.batch_id}** ({kind}, {status}): {batch.label} — waves {waves}{marker}"
        )

    lines += ["", "## Waves", ""]
    if graph.nodes:
        seen: set[str] = set()
        for batch in graph.batches:
            for node_id in _nodes_in_batch(graph, batch):
                if node_id in seen:
                    continue
                seen.add(node_id)
                nr = results.get(node_id)
                if nr is None:
                    lines.append(f"- `{node_id}` — queued (batch {batch.batch_id})")
                else:
                    suffix = f" — {nr.evidence}" if nr.evidence and nr.state == "blocked" else ""
                    lines.append(
                        f"- `{node_id}` — {nr.state} (attempts={nr.attempts}, batch {batch.batch_id}){suffix}"
                    )
    elif results:
        for node_id, nr in results.items():
            lines.append(f"- `{node_id}` — {nr.state} (attempts={nr.attempts})")
    else:
        lines.append("- (no waves registered)")

    lines += ["", "## Pre-0", ""]
    if pre0_approved:
        lines.append("- **Status:** approved — choices recorded in `pre0-decisions.md`")
    else:
        lines.append("- **Status:** pending — resolve gates in `pre0-decisions.md`, then `approve`")
        for gate in graph.pre0_gates:
            lines.append(f"  - {gate}")

    lines += ["", "## Escalated", ""]
    if escalated:
        for node_id in escalated:
            lines.append(f"- `{node_id}`: {results[node_id].evidence}")
    else:
        lines.append("- (none)")

    lines += ["", "## Deferred / manual prerequisites", ""]
    if not pre0_approved:
        for gate in graph.pre0_gates:
            lines.append(f"- {gate}")
    lines.append(f"- {_MANUAL_DEFERRED}")

    if orchestrator_section:
        lines += ["", orchestrator_section.rstrip(), ""]

    return "\n".join(lines) + "\n"


def write_report(
    run_dir: Path,
    graph: RunGraph,
    *,
    run_id: str,
    state: str,
    results: dict[str, NodeResult],
    run_location: str | None = None,
    current_node_id: str | None = None,
    pre0_approved: bool = False,
    updated_at: str | None = None,
    cost_usd: float | None = None,
    orchestrator_section: str = "",
) -> Path:
    """Write ``report.md`` into *run_dir* and return its path.

    Args:
        run_dir (Path): The run directory (must exist).
        graph (RunGraph): The parsed run graph.
        run_id (str): Run identifier.
        state (str): Run state.
        results (dict[str, NodeResult]): node_id → execution result.
        **kwargs: Forwarded to :func:`build_report` (``run_location``, ``current_node_id``, …).

    Returns:
        Path: The written ``report.md`` path.
    """
    path = run_dir / "report.md"
    path.write_text(
        build_report(
            graph,
            run_id=run_id,
            state=state,
            results=results,
            run_location=run_location,
            current_node_id=current_node_id,
            pre0_approved=pre0_approved,
            updated_at=updated_at,
            cost_usd=cost_usd,
            orchestrator_section=orchestrator_section,
        )
    )
    return path


def sync_report(
    run_dir: Path,
    graph: RunGraph,
    ledger_path: Path,
    *,
    run_id: str,
    current_node_id: str | None = None,
    partial_results: dict[str, NodeResult] | None = None,
    pre0_approved: bool = False,
) -> Path:
    """Rebuild ``report.md`` from the ledger (live status for operators).

    Args:
        run_dir (Path): Run directory containing ``report.md``.
        graph (RunGraph): Parsed execution graph.
        ledger_path (Path): SQLite ledger for the run.
        run_id (str): Run identifier.
        current_node_id (str | None): Wave currently dispatching.
        partial_results (dict[str, NodeResult] | None): In-memory results not yet in ledger.
        pre0_approved (bool): Whether Pre-0 was approved.

    Returns:
        Path: Written ``report.md`` path.
    """
    from tripll.engine import NodeResult
    from tripll.ledger import get_run, list_attempts, list_waves, open_ledger

    run_location = run_dir.parent.name
    with open_ledger(ledger_path) as lc:
        run_row = get_run(lc, run_id)
        ledger_waves = {w.node_id: w for w in list_waves(lc, run_id)}
        evidence: dict[str, str] = {}
        for w in ledger_waves.values():
            if w.state in ("blocked", "failed"):
                attempts = list_attempts(lc, run_id, w.node_id)
                evidence[w.node_id] = next(
                    (a.evidence for a in reversed(attempts) if a.evidence),
                    "",
                )

    results: dict[str, NodeResult] = dict(partial_results or {})
    for nid, w in ledger_waves.items():
        ev = evidence.get(nid, "")
        if nid not in results:
            results[nid] = NodeResult(nid, w.state, w.attempt_count, ev)
        elif not results[nid].evidence and ev:
            results[nid] = NodeResult(nid, results[nid].state, results[nid].attempts, ev)
    for nid in graph.nodes:
        if nid not in results:
            results[nid] = NodeResult(nid, "queued", 0, "")

    updated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    orch_section = _orchestrator_section(run_dir)
    return write_report(
        run_dir,
        graph,
        run_id=run_id,
        state=run_row.state,
        results=results,
        run_location=run_location,
        current_node_id=current_node_id,
        pre0_approved=pre0_approved,
        updated_at=updated_at,
        cost_usd=run_row.cost_usd,
        orchestrator_section=orch_section,
    )
