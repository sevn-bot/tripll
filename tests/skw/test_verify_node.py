"""Regression tests for verify nodes between agent and commit (Fix-W1.4)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.skw._graph_helpers import invoke_pipeline_node
from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.pipeline import PipelineBuilder

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"
WAVE_IDS = ("W1", "W2", "Final")


@pytest.mark.parametrize("wave_id", WAVE_IDS)
def test_graph_exposes_verify_node_for_each_wave(wave_id: str) -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    graph = builder.build_graph()
    assert f"verify_{wave_id}" in graph.nodes


def test_verify_node_runs_compiled_make_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def _fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        check: bool = False,
        **kwargs: object,
    ) -> MagicMock:
        calls.append(cmd)
        mock = MagicMock()
        mock.returncode = 0
        return mock

    monkeypatch.setattr("tripll.skw.verify.subprocess.run", _fake_run)
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    state = {
        "wave_file": str(PIPELINE_FIXTURE),
        "history": [],
        "current_wave": "W1",
    }
    invoke_pipeline_node(builder, "verify_W1", state)

    assert calls
    joined = " ".join(calls[0])
    assert "make" in joined
    assert "spec-kit-wave" in joined or "test" in joined


def test_verify_failure_prevents_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    commit_called: list[str] = []

    def _fake_verify_run(*_args: object, **_kwargs: object) -> MagicMock:
        mock = MagicMock()
        mock.returncode = 1
        return mock

    def _fake_commit(**kwargs: object) -> None:
        commit_called.append(str(kwargs.get("wave_id", "")))

    monkeypatch.setattr("tripll.skw.verify.subprocess.run", _fake_verify_run)
    monkeypatch.setattr("tripll.skw.pipeline.commit_wave", _fake_commit)
    monkeypatch.setattr("tripll.skw.pipeline._in_pytest", lambda: False)

    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    state = {
        "wave_file": str(PIPELINE_FIXTURE),
        "history": [],
        "current_wave": "W1",
    }

    with pytest.raises(Exception, match=r"verify|non-zero|exit|failed"):
        invoke_pipeline_node(builder, "verify_W1", state)

    assert commit_called == []


def test_verify_node_honours_skw_dryrun(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(cmd)
        raise AssertionError("subprocess should not run in SKW_DRYRUN mode")

    monkeypatch.setenv("SKW_DRYRUN", "1")
    monkeypatch.setattr("tripll.skw.verify.subprocess.run", _fake_run)
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    invoke_pipeline_node(
        builder,
        "verify_W1",
        {
            "wave_file": str(PIPELINE_FIXTURE),
            "history": [],
            "current_wave": "W1",
        },
    )

    captured = capsys.readouterr()
    assert calls == []
    assert "[dry-run]" in captured.out or "make" in captured.out
