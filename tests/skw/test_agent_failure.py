"""Regression tests for agent failure propagation (Fix-W1.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from tests.skw._graph_helpers import copy_minimal_kit, invoke_pipeline_node
from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.pipeline import PipelineBuilder

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"


def _force_agent_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tripll.skw.pipeline._in_pytest", lambda: False)


def _mock_failing_agent(monkeypatch: pytest.MonkeyPatch, *, rc: int = 1) -> None:
    def _fail(**_kwargs: object) -> int:
        return rc

    monkeypatch.setattr("tripll.skw.pipeline.run_agent", _fail)


@pytest.mark.parametrize(
    ("node_name", "state"),
    [
        (
            "W1",
            {
                "wave_file": str(PIPELINE_FIXTURE),
                "wave_order": ["W1", "W2", "Final"],
                "history": [],
            },
        ),
        (
            "review",
            {
                "wave_file": str(PIPELINE_FIXTURE),
                "history": [],
                "turn": 1,
            },
        ),
    ],
)
def test_agent_nodes_abort_on_nonzero_exit(
    node_name: str,
    state: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_agent_dispatch(monkeypatch)
    _mock_failing_agent(monkeypatch, rc=42)
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)

    with pytest.raises(Exception, match=r"42|AgentRunError|exit|non-zero"):
        invoke_pipeline_node(builder, node_name, state)


def test_run_agent_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from tripll.skw import driver

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SKW_DRYRUN", raising=False)

    class _FakeProc:
        stdout = iter(["agent failed\n"])

        def wait(self) -> int:
            return 5

    monkeypatch.setattr(driver.subprocess, "Popen", lambda *_args, **_kwargs: _FakeProc())

    with pytest.raises(Exception, match=r"5|AgentRunError|exit|non-zero"):
        driver.run_agent(
            wave_file=PIPELINE_FIXTURE,
            kit_root=KIT_ROOT,
            stage="run",
            wave_id="W1",
        )


def test_run_remediation_turn_aborts_on_generate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tripll.skw.graph_nodes import run_remediation_turn

    kit_root, wave_file = copy_minimal_kit(tmp_path)

    def _fail(**_kwargs: object) -> int:
        return 99

    monkeypatch.setattr("tripll.skw.pipeline._in_pytest", lambda: False)
    monkeypatch.setattr("tripll.skw.pipeline.run_agent", _fail)
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=kit_root)

    with pytest.raises(Exception, match=r"99|AgentRunError|exit|non-zero"):
        run_remediation_turn(
            builder,
            wave_file=wave_file,
            waves_before=[],
        )


def test_compiled_graph_aborts_when_wave_agent_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_agent_dispatch(monkeypatch)
    _mock_failing_agent(monkeypatch, rc=99)
    monkeypatch.setattr("tripll.skw.pipeline.commit_wave", lambda **_kwargs: None)
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    compiled = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "agent-failure-test"}}

    with pytest.raises(Exception, match=r"99|AgentRunError|exit|non-zero"):
        compiled.invoke(
            {
                "wave_file": str(PIPELINE_FIXTURE),
                "history": [],
                "turn": 1,
            },
            config=config,
        )
