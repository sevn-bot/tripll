"""LangGraph node factories for the SKW pipeline (Fix-W4).

Pure node callables and edge-wiring helpers accept a ``PipelineBuilder`` context.
``PipelineBuilder.build_graph()`` registers nodes from here and wires edges only.

Exports:
    make_validate_node — turn-open validation + ``waves_before`` snapshot.
    make_wave_node — per-wave agent run node factory.
    make_verify_node — per-wave verify Makefile targets node factory.
    make_commit_node — per-wave git commit node factory.
    make_review_gate_node — per-wave human review gate node factory.
    make_review_node — post-wave review agent node.
    make_cross_check_node — diff waves vs turn-open snapshot.
    run_remediation_turn — driver helper: generate agent + rescan + validate new file.
    register_per_wave_nodes — add wave / verify / commit / gate nodes to graph.
    wire_wave_run_edges — compile run→verify→commit→gate edges from states.
    wire_review_edges — review → cross_check → END (one turn per compile).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from tripll.skw.driver import AgentRunError
from tripll.skw.runtime import is_auto_approve
from tripll.skw.states import PipelineState
from tripll.skw.tracing import span, trace_node
from tripll.skw.turn_context import diff_new_waves, load_verdict, snapshot_waves
from tripll.skw.validate import validate_wave_file
from tripll.skw.verify import run_verify_targets

if TYPE_CHECKING:
    from tripll.skw.pipeline import PipelineBuilder

__all__: list[str] = [
    "make_commit_node",
    "make_cross_check_node",
    "make_review_gate_node",
    "make_review_node",
    "make_validate_node",
    "make_verify_node",
    "make_wave_node",
    "register_per_wave_nodes",
    "run_remediation_turn",
    "wire_review_edges",
    "wire_wave_run_edges",
]


def _run_agent_checked(**kwargs: object) -> None:
    """Dispatch ``run_agent`` and raise ``AgentRunError`` on non-zero exit."""
    from tripll.skw.pipeline import run_agent

    rc = run_agent(**kwargs)
    if rc != 0:
        raise AgentRunError(
            rc,
            stage=str(kwargs.get("stage", "")),
            wave_id=kwargs.get("wave_id"),  # type: ignore[arg-type]
        )


def _list_wave_plans(kit_root: Path) -> list[str]:
    return snapshot_waves(kit_root)


def _in_pytest() -> bool:
    from tripll.skw.pipeline import _in_pytest as pipeline_in_pytest

    return pipeline_in_pytest()


def make_validate_node(builder: PipelineBuilder, wave_ids: list[str]) -> Any:
    """Build the turn-open ``validate`` node."""

    def validate_node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            wave_file = state.get("wave_file") or (
                str(builder.wave_file) if builder.wave_file else ""
            )
            if not wave_file:
                msg = "wave_file missing from pipeline state"
                raise ValueError(msg)
            errors, _warnings = validate_wave_file(Path(wave_file), builder.kit_root)
            if errors:
                msg = f"validation failed: {'; '.join(errors)}"
                raise ValueError(msg)
            turn = state.get("turn", 1)
            waves_before = snapshot_waves(builder.kit_root)
            return {
                **state,
                "wave_file": wave_file,
                "wave_order": wave_ids,
                "turn": turn,
                "waves_before": waves_before,
            }

        return trace_node("pipeline.validate", _run, node="validate")

    return validate_node


def make_wave_node(builder: PipelineBuilder, wid: str) -> Any:
    """Build a per-wave agent run node."""
    wave_state = builder._state_by_id(wid)

    def node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            wave_file = state.get("wave_file") or (
                str(builder.wave_file) if builder.wave_file else ""
            )
            if wave_file and not _in_pytest():
                _run_agent_checked(
                    wave_file=wave_file,
                    kit_root=builder.kit_root,
                    stage="run",
                    wave_id=wid,
                )
            history = list(state.get("history") or [])
            history.append({"node": wid, "action": "run"})
            return {**state, "current_wave": wid, "history": history}

        verify = wave_state.get("verify", []) if wave_state else []
        return trace_node(
            f"pipeline.wave.{wid}",
            _run,
            node=wid,
            wave_id=wid,
            agent=wave_state.get("agent") if wave_state else None,
            role=wave_state.get("role") if wave_state else None,
            verify_targets=verify,
        )

    return node


def make_verify_node(builder: PipelineBuilder, wid: str) -> Any:
    """Build a per-wave verify Makefile targets node."""
    wave_state = builder._state_by_id(wid)

    def node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            verify = wave_state.get("verify", []) if wave_state else []
            run_verify_targets(
                targets=verify,
                kit_root=builder.kit_root,
                wave_id=wid,
            )
            history = list(state.get("history") or [])
            history.append({"node": f"verify_{wid}", "action": "verify"})
            return {**state, "history": history}

        return trace_node(
            f"pipeline.verify.{wid}",
            _run,
            node=f"verify_{wid}",
            wave_id=wid,
            verify_targets=wave_state.get("verify", []) if wave_state else [],
        )

    return node


def make_commit_node(builder: PipelineBuilder, wid: str) -> Any:
    """Build a per-wave git commit node."""
    wave_state = builder._state_by_id(wid)

    def node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            if wave_state and wave_state.get("commit") and not _in_pytest():
                title = builder.wave_titles.get(wid, wid)
                role = wave_state.get("role", "impl")
                from tripll.skw.paths import repo_root_for_kit
                from tripll.skw.pipeline import commit_wave

                repo_root = repo_root_for_kit(builder.kit_root)

                commit_wave(
                    wave_id=wid,
                    title=title,
                    slug=builder.slug,
                    role=role,
                    branch=builder.branch,
                    worktree=repo_root,
                    git_config=builder.git_config,
                )
            history = list(state.get("history") or [])
            history.append({"node": "commit_wave", "wave": wid})
            return {**state, "history": history}

        return trace_node(
            f"pipeline.commit.{wid}",
            _run,
            node=f"commit_{wid}",
            wave_id=wid,
            verify_targets=wave_state.get("verify", []) if wave_state else [],
        )

    return node


def make_review_gate_node(builder: PipelineBuilder, wid: str) -> Any:
    """Build a per-wave human review gate node."""

    def node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            auto = is_auto_approve()
            wave_state = builder._state_by_id(wid)
            if wave_state and wave_state.get("review_gate") and not auto:
                interrupt({"reason": f"review gate on {wid}"})
            return state

        return trace_node(
            f"pipeline.review_gate.{wid}",
            _run,
            node=f"review_gate_{wid}",
            wave_id=wid,
        )

    return node


def make_review_node(builder: PipelineBuilder) -> Any:
    """Build the post-wave review agent node."""

    def review_node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            wave_file = state.get("wave_file") or (
                str(builder.wave_file) if builder.wave_file else ""
            )
            if wave_file and not _in_pytest():
                _run_agent_checked(
                    wave_file=wave_file,
                    kit_root=builder.kit_root,
                    stage="review",
                )
            verdict = load_verdict(builder.kit_root, builder.slug)
            history = list(state.get("history") or [])
            history.append({"node": "review"})
            return {**state, "verdict": verdict, "history": history}

        return trace_node("pipeline.review", _run, node="review", agent="reviewer")

    return review_node


def make_cross_check_node(builder: PipelineBuilder) -> Any:
    """Build the cross-check node (diff waves vs turn-open snapshot)."""

    def cross_check_node(state: PipelineState) -> PipelineState:
        def _run() -> PipelineState:
            wave_file = state.get("wave_file", "")
            waves_before = state.get("waves_before") or []
            waves_after = _list_wave_plans(builder.kit_root)
            new_files = diff_new_waves(waves_before, waves_after, exclude=wave_file)
            history = list(state.get("history") or [])
            history.append({"node": "cross_check", "new_files": new_files})
            return {**state, "new_wave_files": new_files, "history": history}

        with span(
            "pipeline.cross_check",
            node="cross_check",
            verdict=state.get("verdict", ""),
        ) as bag:
            result = _run()
            bag["verdict"] = result.get("verdict", state.get("verdict", ""))
            bag["output"] = str(result.get("new_wave_files", []))
            return result

    return cross_check_node


def run_remediation_turn(
    builder: PipelineBuilder,
    *,
    wave_file: Path | str,
    waves_before: list[str],
) -> Path:
    """Run generate agent, rescan waves, validate new file; return path for next turn.

    Called by the Python driver between graph invocations so each turn recompiles
    from the current wave-file (fresh slug, branch, and wave ids).
    """
    wave_path = Path(wave_file)

    def _generate() -> list[str]:
        if not _in_pytest():
            _run_agent_checked(
                wave_file=wave_path,
                kit_root=builder.kit_root,
                stage="generate",
            )
        waves_after = _list_wave_plans(builder.kit_root)
        return diff_new_waves(waves_before, waves_after, exclude=str(wave_path))

    new_files = trace_node(
        "pipeline.generate",
        _generate,
        node="generate",
        agent="post-review-wave-generator",
    )

    def _validate() -> Path:
        if not new_files:
            msg = "expected a new wave-file after generate, none found"
            raise ValueError(msg)
        new_wave = new_files[0]
        new_path = builder.kit_root / new_wave
        errors, _warnings = validate_wave_file(new_path, builder.kit_root)
        if errors:
            msg = f"validation failed for new wave-file: {'; '.join(errors)}"
            raise ValueError(msg)
        return new_path

    return trace_node("pipeline.validate_new", _validate, node="validate_new")


def register_per_wave_nodes(
    graph: StateGraph[PipelineState],
    builder: PipelineBuilder,
    wave_ids: list[str],
) -> None:
    """Register per-wave run, verify, commit, and optional review-gate nodes.

    Args:
        graph (StateGraph): Graph under construction.
        builder (PipelineBuilder): Pipeline builder context.
        wave_ids (list[str]): Topo-sorted wave ids from ``builder.states``.
    """
    for wid in wave_ids:
        graph.add_node(wid, make_wave_node(builder, wid))
        graph.add_node(f"verify_{wid}", make_verify_node(builder, wid))
        graph.add_node(f"commit_{wid}", make_commit_node(builder, wid))
        wave_state = builder._state_by_id(wid)
        if wave_state and wave_state.get("review_gate"):
            graph.add_node(f"review_gate_{wid}", make_review_gate_node(builder, wid))


def wire_wave_run_edges(
    graph: StateGraph[PipelineState],
    builder: PipelineBuilder,
    wave_ids: list[str],
) -> None:
    """Wire validate → wave run → verify → commit → gate/next edges from states.

    Args:
        graph (StateGraph): Graph under construction.
        builder (PipelineBuilder): Pipeline builder (``review_gate`` per state).
        wave_ids (list[str]): Topo-sorted wave ids.
    """
    if wave_ids:
        graph.add_edge("validate", wave_ids[0])
    else:
        graph.add_edge("validate", "review")

    for idx, wid in enumerate(wave_ids):
        graph.add_edge(wid, f"verify_{wid}")
        graph.add_edge(f"verify_{wid}", f"commit_{wid}")
        wave_state = builder._state_by_id(wid)
        next_target = wave_ids[idx + 1] if idx + 1 < len(wave_ids) else "review"
        if wave_state and wave_state.get("review_gate"):
            gate_name = f"review_gate_{wid}"
            graph.add_edge(f"commit_{wid}", gate_name)
            graph.add_edge(gate_name, next_target)
        else:
            graph.add_edge(f"commit_{wid}", next_target)


def wire_review_edges(
    graph: StateGraph[PipelineState],
    route_cross_check: Callable[[PipelineState], str],
) -> None:
    """Wire review → cross_check → END for one compiled turn.

    Args:
        graph (StateGraph): Graph under construction.
        route_cross_check (Callable): Router after cross_check (always END; validates verdict).
    """
    graph.add_edge("review", "cross_check")
    graph.add_conditional_edges(
        "cross_check",
        route_cross_check,
        {END: END},
    )
