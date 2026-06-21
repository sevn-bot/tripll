"""Unit tests for orchestrator_status table rendering (W1.6)."""

from __future__ import annotations

from tripll.graph import OrchestratorConfig, RunGraph
from tripll.orchestrator_status import (
    OrchestratorTurn,
    StatusRow,
    append_turn,
    read_latest,
    render_status_table,
    sync_orchestrator_status,
)


def test_render_status_table_cursor_export_shape() -> None:
    md = render_status_table(
        [
            StatusRow(
                wave="W0 UI/UX lock + schemas",
                status="pending",
                branch="feature/tripll-dashboard-ui",
                commit="—",
                evidence="…",
            )
        ]
    )
    lines = md.splitlines()
    assert lines[0] == "| Wave | Status | Branch | Commit | Evidence / blockers |"
    assert lines[1] == "|------|--------|--------|--------|---------------------|"
    assert "W0 UI/UX lock" in lines[2]
    assert "`feature/tripll-dashboard-ui`" in lines[2]


def test_append_turn_and_read_latest(tmp_path) -> None:
    run = tmp_path / "run-1"
    run.mkdir()
    sync_orchestrator_status(
        run,
        RunGraph(
            run_id="run-1",
            orchestrator=OrchestratorConfig(
                enabled=True,
                prompt_path="p.md",
                feature_branch="feature/foo",
                serial_waves=["W0", "W1"],
            ),
        ),
        rows=[StatusRow("W0", status="pending", branch="feature/foo")],
        turn=OrchestratorTurn("bootstrap", "Created feature/foo from test-pre"),
    )
    snap = read_latest(run)
    assert snap.run_id == "run-1"
    assert snap.feature_branch == "feature/foo"
    assert len(snap.turns) == 1
    assert snap.turns[0].turn_type == "bootstrap"
    text = (run / "orchestrator-status.md").read_text()
    assert "## Status table" in text
    assert "## Turn log" in text
    assert "### Turn 1 — bootstrap" in text


def test_append_turn_increments_turn_number(tmp_path) -> None:
    run = tmp_path / "run-2"
    run.mkdir()
    append_turn(run, OrchestratorTurn("bootstrap", "start"))
    append_turn(run, OrchestratorTurn("wave_dispatched", "W0 dispatched"))
    snap = read_latest(run)
    assert [t.turn_n for t in snap.turns] == [1, 2]
    assert snap.turns[1].turn_type == "wave_dispatched"


def test_sync_orchestrator_status_in_memory_turns_skip_disk_read(tmp_path) -> None:
    """Engine hot loop passes rows+turns so prior turns are not re-parsed."""
    run = tmp_path / "run-fast"
    run.mkdir()
    graph = RunGraph(
        run_id="run-fast",
        orchestrator=OrchestratorConfig(
            enabled=True,
            prompt_path="p.md",
            feature_branch="feature/foo",
            serial_waves=["W0"],
        ),
    )
    rows = [StatusRow("W0", status="pending", branch="feature/foo")]
    turns: list[OrchestratorTurn] = []
    sync_orchestrator_status(
        run,
        graph,
        rows=rows,
        turns=turns,
        turn=OrchestratorTurn("bootstrap", "start"),
    )
    sync_orchestrator_status(
        run,
        graph,
        rows=rows,
        turns=turns,
        turn=OrchestratorTurn("wave_complete", "W0 done"),
    )
    assert len(turns) == 2
    snap = read_latest(run)
    assert [t.turn_type for t in snap.turns] == ["bootstrap", "wave_complete"]


def test_graph_orchestrator_serializes_in_to_dict() -> None:
    g = RunGraph(
        run_id="r",
        orchestrator=OrchestratorConfig(
            enabled=True,
            prompt_path="/tmp/p.md",
            feature_branch="feature/x",
            serial_waves=["W0", "W1"],
        ),
    )
    d = g.to_dict()
    assert "orchestrator" in d
    orch = d["orchestrator"]
    assert isinstance(orch, dict)
    assert orch["feature_branch"] == "feature/x"
    assert orch["serial_waves"] == ["W0", "W1"]
