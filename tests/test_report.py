"""Tests for tripll.report — report.md generation."""

from __future__ import annotations

from pathlib import Path

from tripll.engine import NodeResult
from tripll.graph import Batch, RunGraph, WaveNode
from tripll.ledger import insert_run, insert_wave, open_ledger, transition_wave
from tripll.report import build_report, sync_report


def _graph() -> RunGraph:
    g = RunGraph(run_id="r")
    g.batches = [
        Batch("Pre-0", "human gate", is_human_gate=True, wave_ids=["W0"]),
        Batch("A", "first", lanes=["core"], wave_ids=["W0"]),
        Batch("B", "second", lanes=["core"], wave_ids=["W1"]),
    ]
    g.nodes = {
        "core:W0": WaveNode("core:W0", "core", "p", "W0", "core"),
        "ui:W0": WaveNode("ui:W0", "ui", "p", "W0", "ui"),
        "core:W1": WaveNode("core:W1", "core", "p", "W1", "core"),
    }
    g.pre0_gates = ["Decide telemetry schema", "Confirm CW owners"]
    return g


def test_report_lists_phases_and_waves() -> None:
    results = {
        "core:W0": NodeResult("core:W0", "done", 1),
        "ui:W0": NodeResult("ui:W0", "blocked", 3, "verify failed"),
        "core:W1": NodeResult("core:W1", "queued", 0),
    }
    text = build_report(
        _graph(),
        run_id="r",
        state="failed",
        results=results,
        pre0_approved=True,
    )
    assert "# Run report — r" in text
    assert "**State:** failed" in text
    assert "## Batches" in text
    assert "`core:W0` — done" in text


def test_report_escalated_section_shows_evidence() -> None:
    results = {"ui:W0": NodeResult("ui:W0", "blocked", 3, "verify failed")}
    text = build_report(_graph(), run_id="r", state="failed", results=results)
    assert "## Escalated" in text
    assert "`ui:W0`: verify failed" in text


def test_report_lists_deferred_manual_prereqs() -> None:
    text = build_report(_graph(), run_id="r", state="paused", results={})
    assert "## Deferred / manual prerequisites" in text
    assert "Decide telemetry schema" in text
    assert "Cloud live dispatch" in text


def test_report_pre0_approved_omits_gate_checklist_from_deferred() -> None:
    text = build_report(_graph(), run_id="r", state="active", results={}, pre0_approved=True)
    assert "## Pre-0" in text
    assert "approved" in text
    assert "Decide telemetry schema" not in text.split("## Deferred")[1]


def test_report_no_escalation_when_clean() -> None:
    results = {"core:W0": NodeResult("core:W0", "done", 1)}
    text = build_report(_graph(), run_id="r", state="done", results=results)
    assert "## Escalated\n\n- (none)" in text


def test_report_shows_current_wave() -> None:
    results = {
        "core:W0": NodeResult("core:W0", "done", 1),
        "core:W1": NodeResult("core:W1", "running", 1),
    }
    text = build_report(
        _graph(),
        run_id="r",
        state="active",
        results=results,
        current_node_id="core:W1",
        run_location="processing",
    )
    assert "**Current wave:** `core:W1`" in text
    assert "in progress" in text


def test_report_orchestrator_section_from_status_file(tmp_path: Path) -> None:
    from tripll.graph import OrchestratorConfig, RunGraph
    from tripll.orchestrator_status import OrchestratorTurn, StatusRow, sync_orchestrator_status

    run_dir = tmp_path / "processing" / "r"
    run_dir.mkdir(parents=True)
    graph = RunGraph(
        run_id="r",
        orchestrator=OrchestratorConfig(True, "p.md", "feature/orch"),
    )
    sync_orchestrator_status(
        run_dir,
        graph,
        rows=[StatusRow("W0", status="done", branch="feature/orch", commit="abc1234")],
        turn=OrchestratorTurn("bootstrap", "Run started"),
    )
    from tripll.report import _orchestrator_section

    section = _orchestrator_section(run_dir)
    text = build_report(
        _graph(),
        run_id="r",
        state="active",
        results={},
        orchestrator_section=section,
    )
    assert "## Orchestrator" in text
    assert "orchestrator-status.md" in text
    assert "| W0 | done |" in text


def test_sync_report_reads_ledger(tmp_path: Path) -> None:
    run_dir = tmp_path / "processing" / "r"
    run_dir.mkdir(parents=True)
    ledger_path = run_dir / "ledger.db"
    graph = _graph()
    with open_ledger(ledger_path) as lc:
        insert_run(lc, run_id="r", slug="r", source_mode="B", input_path=str(run_dir))
        insert_wave(
            lc,
            node_id="core:W0",
            run_id="r",
            plan_id="core",
            wave_id="W0",
            lane="core",
        )
        transition_wave(lc, "r", "core:W0", "done")

    sync_report(run_dir, graph, ledger_path, run_id="r", pre0_approved=True)
    text = (run_dir / "report.md").read_text()
    assert "`core:W0` — done" in text
    assert "**Updated:**" in text
