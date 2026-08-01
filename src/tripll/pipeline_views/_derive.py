"""tripll.pipeline_views._derive — build both views from one pipeline file.

Two complementary charts come out of the same
:class:`~tripll.pipeline_spec.PipelineSpec`, so they cannot drift apart:

* **execution** — steps are nodes (agents, system phases, human gates) and the
  declared transitions are edges, retries and feedback included.
* **state** — the artifact states are nodes and every edge is the step work that
  moves the pipeline from one state to the next.

Placement comes from the file when it supplies ``layer`` / ``column``, and is
derived from the transitions otherwise.

Exports:
    execution_view — build the step/control-transition view.
    state_view — build the state view whose edges are step work.
    VIEWS — view id → builder map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tripll.pipeline_views._layout import _derive_placement
from tripll.pipeline_views._model import (
    DetailCard,
    NodeDetail,
    PipelineView,
    ViewCluster,
    ViewEdge,
    ViewNode,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from tripll.pipeline_spec import (
        Answer,
        PipelineSpec,
        State,
        Step,
        Transition,
        TransitionStyle,
    )

__all__ = ["VIEWS", "execution_view", "state_view"]

# ---------------------------------------------------------------------------
# View 1 — steps are nodes (execution graph)
# ---------------------------------------------------------------------------


def _step_facts(step: Step, states: dict[str, State]) -> tuple[tuple[str, str], ...]:
    """Return the label/value rows describing how a step runs."""
    facts: list[tuple[str, str]] = []
    if step.harness:
        facts.append(("Harness", step.harness))
    if step.model:
        facts.append(("Model", step.model))
    if step.produces:
        facts.append(("Produces", states[step.produces].label))
    if step.wave:
        facts.append(("Wave", step.wave))
    return tuple(facts)


def execution_view(spec: PipelineSpec) -> PipelineView:
    """Build the execution view: steps as nodes, declared transitions as edges.

    Args:
        spec (PipelineSpec): Loaded pipeline file.

    Returns:
        PipelineView: Renderable view.

    Examples:
        >>> execution_view(load_pipeline_spec(Path("p.toml"))).view_id  # doctest: +SKIP
        'execution'
    """
    placed = all(step.layer is not None and step.column is not None for step in spec.steps)
    fallback = (
        {}
        if placed
        else _derive_placement(
            [step.step_id for step in spec.steps],
            [(step.step_id, t.to) for step in spec.steps for t in step.transitions],
        )
    )
    states = spec.state_map()
    nodes: list[ViewNode] = []
    for step in spec.steps:
        layer, column = fallback.get(step.step_id, (step.layer or 0, step.column or 0.0))
        nodes.append(
            ViewNode(
                node_id=step.step_id,
                label=step.label,
                kind=step.kind,
                layer=layer,
                column=column,
                note=step.note,
                detail=NodeDetail(
                    summary=step.summary,
                    facts=_step_facts(step, states),
                    params=step.params,
                ),
            )
        )
    edges = tuple(
        ViewEdge(
            source=step.step_id,
            target=transition.to,
            label=transition.label,
            note=transition.note,
            detail=transition.detail,
            style=transition.style,
            answer=transition.answer,
            bow=transition.bow,
        )
        for step in spec.steps
        for transition in step.transitions
    )
    members: dict[str, list[str]] = {cluster.cluster_id: [] for cluster in spec.clusters}
    for step in spec.steps:
        if step.cluster:
            members[step.cluster].append(step.step_id)
    clusters = tuple(
        ViewCluster(label=cluster.label, members=tuple(members[cluster.cluster_id]))
        for cluster in spec.clusters
        if members[cluster.cluster_id]
    )
    return PipelineView(
        view_id="execution",
        title=f"{spec.title} — execution graph (agent is node)",
        subtitle="Agents, system phases, and human gates are nodes; edges are control transitions",
        nodes=tuple(nodes),
        edges=edges,
        clusters=clusters,
        source=spec.source,
    )


# ---------------------------------------------------------------------------
# View 2 — states are nodes, step work is the edge
# ---------------------------------------------------------------------------


def _chain_note(works: Sequence[str]) -> str:
    """Join a chain of step names, eliding the middle when longer than two."""
    trimmed = [work for work in works if work]
    if not trimmed:
        return ""
    if len(trimmed) <= 2:
        return " → ".join(trimmed)
    return f"{trimmed[0]} → … → {trimmed[-1]}"


def _source_states(
    step_id: str,
    spec: PipelineSpec,
    incoming: dict[str, list[tuple[str, Transition]]],
    seen: frozenset[str],
) -> list[tuple[str, list[str]]]:
    """Walk back to the nearest state-producing ancestors of *step_id*.

    Returns:
        list[tuple[str, list[str]]]: ``(state_id, works)`` where *works* are the
        labels of the non-producing steps passed through, in flow order.
    """
    step = spec.step_map()[step_id]
    if step.produces:
        return [(step.produces, [])]
    out: list[tuple[str, list[str]]] = []
    for source_id, _transition in incoming.get(step_id, []):
        if source_id in seen:
            continue
        for state_id, works in _source_states(source_id, spec, incoming, seen | {step_id}):
            out.append((state_id, [*works, step.work_label]))
    return out


def _merge_parts(parts: Sequence[str], separator: str) -> str:
    """Join distinct label or note fragments, capping the list at two entries."""
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    if len(unique) <= 2:
        return separator.join(unique)
    return separator.join(unique[:2]) + separator + "…"


def _state_edge_label(step: Step, transition: Transition) -> str:
    """Return the primary label for a derived state edge.

    Forward work is named by the producing step's ``wave``; feedback and side
    paths are named by the transition that triggered them, which carries the
    reason (``failed → retry``) rather than the wave id.
    """
    if transition.style == "primary" and step.wave:
        return step.wave
    return transition.label or step.wave


@dataclass
class _EdgeParts:
    """Label, note, and hover-detail fragments collected for one state edge."""

    labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


def _derive_state_edges(spec: PipelineSpec) -> tuple[ViewEdge, ...]:
    """Derive one state-view edge per state transition, merging parallel steps."""
    incoming = spec.incoming()
    grouped: dict[tuple[str, str, TransitionStyle, Answer, str], _EdgeParts] = {}
    for step in spec.steps:
        if not step.produces:
            continue
        for source_id, transition in incoming.get(step.step_id, []):
            for state_id, works in _source_states(source_id, spec, incoming, frozenset()):
                if state_id == step.produces:
                    continue
                key = (
                    state_id,
                    step.produces,
                    transition.style,
                    transition.answer,
                    transition.bow,
                )
                parts = grouped.setdefault(key, _EdgeParts())
                parts.labels.append(_state_edge_label(step, transition))
                parts.notes.append(_chain_note([*works, step.work_label]))
                parts.details.append(transition.detail)
    return tuple(
        ViewEdge(
            source=source,
            target=target,
            label=_merge_parts(parts.labels, " / "),
            note=_merge_parts(parts.notes, ", "),
            detail=_merge_parts(parts.details, " "),
            style=style,
            answer=answer,
            bow=bow,  # type: ignore[arg-type]
        )
        for (source, target, style, answer, bow), parts in grouped.items()
    )


def state_view(spec: PipelineSpec) -> PipelineView:
    """Build the state view: artifact states as nodes, step work as edges.

    Each edge runs from the state a step consumed to the state it produces, and
    is labelled with the step's ``wave`` plus the agent (or chain of agents) that
    performs the work.

    Args:
        spec (PipelineSpec): Loaded pipeline file.

    Returns:
        PipelineView: Renderable view.

    Examples:
        >>> state_view(load_pipeline_spec(Path("p.toml"))).view_id  # doctest: +SKIP
        'state'
    """
    states = spec.state_map()
    edges = _derive_state_edges(spec)
    used = [
        state_id
        for state_id in states
        if any(state_id in (edge.source, edge.target) for edge in edges)
    ]
    placed = all(
        states[state_id].layer is not None and states[state_id].column is not None
        for state_id in used
    )
    fallback = (
        {} if placed else _derive_placement(used, [(edge.source, edge.target) for edge in edges])
    )
    producers: dict[str, list[Step]] = {}
    for step in spec.steps:
        if step.produces:
            producers.setdefault(step.produces, []).append(step)
    nodes: list[ViewNode] = []
    for state_id in used:
        state = states[state_id]
        layer, column = fallback.get(state_id, (state.layer or 0, state.column or 0.0))
        cards = tuple(
            DetailCard(
                name=step.label,
                summary=step.summary,
                facts=_step_facts(step, states),
                params=step.params,
            )
            for step in producers.get(state_id, [])
        )
        nodes.append(
            ViewNode(
                node_id=state_id,
                label=state.label,
                kind=state.kind,
                layer=layer,
                column=column,
                note=state.note,
                detail=NodeDetail(summary=state.note, cards=cards),
            )
        )
    clusters = tuple(
        ViewCluster(
            label=cluster.label,
            members=tuple(state_id for state_id in cluster.states if state_id in set(used)),
        )
        for cluster in spec.clusters
        if any(state_id in set(used) for state_id in cluster.states)
    )
    return PipelineView(
        view_id="state",
        title=f"{spec.title} — state graph (edge is agent work)",
        subtitle="Artifact states are nodes; each edge is the wave and agent that produces them",
        nodes=tuple(nodes),
        edges=edges,
        clusters=clusters,
        source=spec.source,
        col_pitch=392,
        row_pitch=196,
    )


VIEWS: dict[str, Callable[[PipelineSpec], PipelineView]] = {
    "execution": execution_view,
    "state": state_view,
}
