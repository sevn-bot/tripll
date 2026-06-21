"""Orchestrator mode W0 smoke — example input set + terminal/dashboard parity (Final.4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli import app
from tripll.graph import OrchestratorConfig, RunGraph
from tripll.orchestrator_status import OrchestratorTurn, StatusRow, sync_orchestrator_status
from tripll.parse.orchestrator_prompt import build_orchestrator_config
from tripll.pipeline import RunsRoot

_EXAMPLE_DIR = (
    Path(__file__).resolve().parents[1] / "docs" / "examples" / "orchestrator-mode-input-set"
)
_SET_NAME = "orchestrator-mode-smoke"
_FEATURE_BRANCH = "feature/tripll-orchestrator-mode"


@pytest.fixture
def example_input(tmp_path: Path) -> Path:
    """Copy tracked example set into a temp runs/input folder."""
    if not _EXAMPLE_DIR.is_dir():
        pytest.skip(f"example set missing: {_EXAMPLE_DIR}")
    dest = tmp_path / "runs" / "input" / _SET_NAME
    dest.mkdir(parents=True)
    for md in _EXAMPLE_DIR.glob("*.md"):
        if md.name == "README.md":
            continue
        shutil.copy(md, dest / md.name)
    return dest


def test_example_set_enables_orchestrator_config(example_input: Path) -> None:
    """Example input dir builds OrchestratorConfig with W0 serial slice."""
    cfg = build_orchestrator_config(example_input, slug="tripll-orchestrator-mode")
    assert isinstance(cfg, OrchestratorConfig)
    assert cfg.enabled is True
    assert cfg.feature_branch == _FEATURE_BRANCH
    assert cfg.serial_waves == ["W0"]
    assert cfg.review_gates.get("W0") == "W0.8"


def test_example_set_passes_validate(example_input: Path) -> None:
    """tripll validate accepts the W0 smoke input set."""
    runner = CliRunner()
    result = runner.invoke(app, ["validate", str(example_input)])
    assert result.exit_code == 0, result.output


def test_w0_status_table_parity_terminal_and_dashboard(tmp_path: Path, example_input: Path) -> None:
    """W0 row in orchestrator-status matches status --watch and dashboard panel."""
    from tripll.api._orchestrator_ui import build_orchestrator_view
    from tripll.ledger import insert_run, insert_wave, open_ledger

    rr = RunsRoot(tmp_path / "runs")
    rr.init()

    runner = CliRunner()
    plan_result = runner.invoke(app, ["plan", str(example_input), "--runs-root", str(rr.root)])
    assert plan_result.exit_code == 0, plan_result.output

    run_dir = rr.processing_dir / "smoke-w0"
    run_dir.mkdir(parents=True)
    graph = RunGraph(
        run_id="smoke-w0",
        orchestrator=OrchestratorConfig(
            enabled=True,
            prompt_path=str(example_input / "tripll-orchestrator-mode-orchestrator-prompt.md"),
            feature_branch=_FEATURE_BRANCH,
            serial_waves=["W0"],
            review_gates={"W0": "W0.8"},
        ),
    )
    (run_dir / "graph.json").write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    sync_orchestrator_status(
        run_dir,
        graph,
        rows=[
            StatusRow(
                "W0",
                status="done",
                branch=_FEATURE_BRANCH,
                commit="abc1234",
                evidence="design-note §8",
            ),
        ],
        turn=OrchestratorTurn(
            "review_gate",
            "**AWAITING REVIEW** (W0.8) — operator sign-off before W1",
        ),
    )

    with open_ledger(run_dir / "ledger.db") as lc:
        insert_run(
            lc,
            run_id="smoke-w0",
            slug=_SET_NAME,
            source_mode="B",
            input_path=str(example_input),
        )
        insert_wave(
            lc,
            node_id="tripll-orchestrator-mode-wave-plan:W0",
            run_id="smoke-w0",
            plan_id="tripll-orchestrator-mode-wave-plan",
            wave_id="W0",
            lane="default",
        )

    from tripll.cli import _orchestrator_watch_lines

    terminal_block = "\n".join(_orchestrator_watch_lines(run_dir))
    assert "| W0 |" in terminal_block
    assert _FEATURE_BRANCH in terminal_block
    assert "abc1234" in terminal_block

    view = build_orchestrator_view(run_dir, run_id="smoke-w0")
    assert view.enabled is True
    w0_rows = [r for r in view.rows if r.wave == "W0"]
    assert len(w0_rows) == 1
    assert w0_rows[0].status == "done"
    assert w0_rows[0].commit == "abc1234"
    assert w0_rows[0].branch == _FEATURE_BRANCH
    assert view.gate_notice is not None
    assert "AWAITING REVIEW" in view.gate_notice
