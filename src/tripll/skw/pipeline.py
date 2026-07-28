"""LangGraph pipeline builder and compiled JSON export (Wave W2).

``PipelineBuilder`` compiles the wave-file TOML graph into a LangGraph
``StateGraph`` and exports a JSON artifact derived from (not replacing) the
wave-file.

Pipeline JSON schema (locked W0.3)::

    {
      "slug": "<plan slug>",
      "base": "<git diff base>",
      "branch": "<feature branch>",
      "max_turns": <int>,
      "states": [
        {
          "id": "<wave id>",
          "agent": "<agent id>",
          "role": "impl" | "test-author",
          "depends_on": ["<wave id>", ...],
          "verify": ["make ...", ...],
          "review_gate": <bool>,
          "commit": <bool>
        }
      ]
    }

``commit`` — whether a ``commit_wave`` graph node follows the agent state (D9).

Exports:
    PipelineBuilder — compile wave-file → graph + JSON round-trip.
    cross_check_outcome — DONE vs CONTINUE after review cross-check.
    run_pipeline — multi-turn driver; recompiles graph each turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from tripll.skw.driver import run_agent as _driver_run_agent
from tripll.skw.git import commit_wave as _git_commit_wave
from tripll.skw.graph_nodes import (
    make_cross_check_node,
    make_review_node,
    make_validate_node,
    register_per_wave_nodes,
    run_remediation_turn,
    wire_review_edges,
    wire_wave_run_edges,
)
from tripll.skw.render import topo_sort
from tripll.skw.resolve_wave import agent_for_role, load_wave_data
from tripll.skw.runtime import is_pytest as _runtime_is_pytest
from tripll.skw.states import PipelineState
from tripll.skw.validate import load_skw_config
from tripll.skw.wave_model import WavePlan

__all__: list[str] = [
    "PipelineBuilder",
    "cross_check_outcome",
    "default_skw_checkpoint_path",
    "run_pipeline",
]


def _in_pytest() -> bool:
    """Return True under pytest (patchable via ``skw.pipeline._in_pytest`` in tests)."""
    return _runtime_is_pytest()


def run_agent(**kwargs: Any) -> int:
    """Dispatch agent CLI (patchable via ``skw.pipeline.run_agent`` in tests)."""
    return _driver_run_agent(**kwargs)


def commit_wave(**kwargs: Any) -> None:
    """Git commit for one wave (patchable via ``skw.pipeline.commit_wave`` in tests)."""
    return _git_commit_wave(**kwargs)


def cross_check_outcome(state: PipelineState) -> str:
    """Return ``DONE`` or ``CONTINUE`` from review verdict + new wave-files.

    Args:
        state (PipelineState): Graph state with ``verdict`` and ``new_wave_files``.

    Returns:
        str: ``DONE`` when verdict is pass with no new files; ``CONTINUE`` when
        ``changes_required``; raises when pass coincides with new files.

    Examples:
        >>> cross_check_outcome({"verdict": "pass", "new_wave_files": []})
        'DONE'
        >>> cross_check_outcome({"verdict": "changes_required", "new_wave_files": []})
        'CONTINUE'
    """
    verdict = state.get("verdict")
    new_files = state.get("new_wave_files") or []
    if verdict not in ("pass", "changes_required"):
        msg = f"unknown or missing verdict: {verdict!r}"
        raise ValueError(msg)
    if verdict == "pass" and new_files:
        msg = "pass verdict but new wave-file(s) appeared"
        raise ValueError(msg)
    if verdict == "pass":
        return "DONE"
    return "CONTINUE"


def _wave_titles(data: dict[str, Any]) -> dict[str, str]:
    return {plan.id: plan.title for plan in WavePlan.from_wave_data(data)}


def _wave_states_from_data(
    data: dict[str, Any],
    *,
    commit_enabled: bool,
) -> list[dict[str, Any]]:
    plans = WavePlan.from_wave_data(data)
    depends = {plan.id: plan.depends_on for plan in plans}
    plan_by_id = {plan.id: plan for plan in plans}
    order = topo_sort(depends)
    states: list[dict[str, Any]] = []
    for wid in order:
        plan = plan_by_id[wid]
        states.append(
            {
                "id": wid,
                "agent": agent_for_role(plan.role),
                "role": plan.role,
                "depends_on": plan.depends_on,
                "verify": plan.verify,
                "review_gate": plan.review_gate,
                "commit": commit_enabled,
            }
        )
    return states


@dataclass
class PipelineBuilder:
    """Compile wave-files into LangGraph pipelines."""

    slug: str
    base: str
    branch: str
    max_turns: int
    states: list[dict[str, Any]]
    kit_root: Path
    wave_file: Path | None = None
    wave_titles: dict[str, str] = field(default_factory=dict)
    git_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_wave_file(cls, wave_path: Path, kit_root: Path) -> PipelineBuilder:
        """Build a pipeline builder from a wave markdown file.

        Args:
            wave_path (Path): Path to the wave-file.
            kit_root (Path): Kit root directory.

        Returns:
            PipelineBuilder: Compiled builder instance.
        """
        wave_path = wave_path.resolve()
        data = load_wave_data(wave_path)
        git_config = load_skw_config(kit_root)
        commit_enabled = bool(git_config.get("git", {}).get("commit_per_wave", True))

        pipeline = data.get("pipeline", {})
        max_turns = 3
        if isinstance(pipeline, dict) and "max_turns" in pipeline:
            max_turns = int(pipeline["max_turns"])

        return cls(
            slug=str(data.get("slug", "")),
            base=str(data.get("base", "")),
            branch=str(data.get("branch", "")),
            max_turns=max_turns,
            states=_wave_states_from_data(data, commit_enabled=commit_enabled),
            kit_root=kit_root.resolve(),
            wave_file=wave_path,
            wave_titles=_wave_titles(data),
            git_config=git_config,
        )

    @classmethod
    def from_json(cls, payload: dict[str, Any], kit_root: Path | None = None) -> PipelineBuilder:
        """Restore a builder from compiled JSON.

        Args:
            payload (dict[str, Any]): Pipeline JSON artifact.
            kit_root (Path | None): Optional kit root override.

        Returns:
            PipelineBuilder: Restored builder instance.
        """
        root = kit_root.resolve() if kit_root else Path.cwd()
        return cls(
            slug=str(payload.get("slug", "")),
            base=str(payload.get("base", "")),
            branch=str(payload.get("branch", "")),
            max_turns=int(payload.get("max_turns", 3)),
            states=list(payload.get("states", [])),
            kit_root=root,
            git_config=load_skw_config(root),
        )

    def to_json(self) -> dict[str, Any]:
        """Serialize the compiled pipeline to JSON-compatible dict.

        Returns:
            dict[str, Any]: Pipeline JSON artifact.
        """
        return {
            "slug": self.slug,
            "base": self.base,
            "branch": self.branch,
            "max_turns": self.max_turns,
            "states": self.states,
        }

    def _state_by_id(self, wave_id: str) -> dict[str, Any] | None:
        for state in self.states:
            if state.get("id") == wave_id:
                return state
        return None

    def build_graph(self) -> StateGraph[PipelineState]:
        """Build the LangGraph ``StateGraph`` for this pipeline.

        Returns:
            StateGraph: Uncompiled graph with validate / wave / commit / review nodes.
        """
        graph: StateGraph[PipelineState] = StateGraph(PipelineState)
        wave_ids = [s["id"] for s in self.states]

        graph.add_node("validate", make_validate_node(self, wave_ids))
        register_per_wave_nodes(graph, self, wave_ids)
        graph.add_node("review", make_review_node(self))
        graph.add_node("cross_check", make_cross_check_node(self))

        graph.add_edge(START, "validate")
        wire_wave_run_edges(graph, self, wave_ids)

        def route_cross_check(state: PipelineState) -> str:
            cross_check_outcome(state)
            return END

        wire_review_edges(graph, route_cross_check)

        return graph

    def compile(
        self,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> Any:
        """Compile the graph with an optional checkpointer.

        Args:
            checkpointer (BaseCheckpointSaver | None): LangGraph checkpointer.

        Returns:
            CompiledStateGraph: Runnable compiled graph.
        """
        return self.build_graph().compile(checkpointer=checkpointer)


def default_skw_checkpoint_path() -> Path:
    """Return the default SQLite checkpoint path for skw pipeline runs.

    Returns:
        Path: ``<repo>/.tripll/skw-checkpoints.db`` (parent dirs created).
    """
    from tripll.repo_root import resolve_repo_root

    path = resolve_repo_root() / ".tripll" / "skw-checkpoints.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_pipeline_loop(
    wave_path: Path,
    kit_root: Path,
    *,
    saver: BaseCheckpointSaver[Any],
) -> PipelineState:
    """Execute the multi-turn skw pipeline with a bound checkpointer."""
    turn = 1
    current_wave_file = wave_path.resolve()
    history: list[dict[str, Any]] = []
    result: PipelineState = {}
    max_turns: int | None = None

    while True:
        builder = PipelineBuilder.from_wave_file(current_wave_file, kit_root)
        if max_turns is None:
            max_turns = builder.max_turns
        compiled = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": f"skw-run-{builder.slug}-turn-{turn}"}}
        result = compiled.invoke(
            {"wave_file": str(current_wave_file), "history": history, "turn": turn},
            config=config,
        )

        if result.get("__interrupt__"):
            return result

        history = list(result.get("history") or history)
        outcome = cross_check_outcome(result)

        if outcome == "DONE":
            return result

        next_turn = turn + 1
        assert max_turns is not None
        if next_turn > max_turns:
            msg = f"reached max_turns={max_turns} without clean pass"
            raise ValueError(msg)

        current_wave_file = run_remediation_turn(
            builder,
            wave_file=current_wave_file,
            waves_before=list(result.get("waves_before") or []),
        )
        turn = next_turn


def run_pipeline(
    wave_path: Path,
    kit_root: Path,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> PipelineState:
    """Run the full multi-turn pipeline, recompiling the graph each turn.

    Each turn compiles a fresh graph from the current wave-file so slug, branch,
    wave ids, and per-wave node structure match the active plan. The review →
    generate → validate_new loop runs in this driver between invocations.

    Defaults to durable ``SqliteSaver`` at :func:`default_skw_checkpoint_path`
    (``MemorySaver`` under pytest only).

    Args:
        wave_path (Path): Initial wave markdown file.
        kit_root (Path): Kit root directory.
        checkpointer (BaseCheckpointSaver[Any] | None): LangGraph checkpointer per turn.

    Returns:
        PipelineState: Final graph state (may include ``__interrupt__`` for review gate).
    """
    if checkpointer is not None:
        return _run_pipeline_loop(wave_path, kit_root, saver=checkpointer)
    if _in_pytest():
        from langgraph.checkpoint.memory import MemorySaver

        return _run_pipeline_loop(wave_path, kit_root, saver=MemorySaver())
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = default_skw_checkpoint_path()
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        return _run_pipeline_loop(wave_path, kit_root, saver=saver)
