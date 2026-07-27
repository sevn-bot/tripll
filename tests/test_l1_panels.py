"""L1 dashboard panels — graph, findings, exits (pr-verifier follow-up)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tripll.api._l1_panels import build_l1_panels
from tripll.api.app import create_app
from tripll.graphstore import SqliteGraphStore
from tripll.ledger import append_event, insert_run, insert_wave, open_ledger
from tripll.pipeline import RunsRoot

_PROV = {
    "source": "test",
    "evidence": "tests/test_l1_panels.py:1",
    "extractor": "test",
    "extractor_version": "0",
    "confidence": 1.0,
    "extracted_at": "2026-07-25T00:00:00Z",
}


def _seed_graph_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteGraphStore(str(path))
    try:
        store.upsert_nodes(
            [
                {
                    "node_id": "code:Module:tripll.demo",
                    "layer": "code",
                    "kind": "Module",
                    "natural_key": "tripll.demo",
                    "repo": "tripll",
                    "props": "{}",
                    **_PROV,
                },
                {
                    "node_id": "finding:ci:ruff-f401",
                    "layer": "finding",
                    "kind": "Finding",
                    "natural_key": "ruff:F401:src/a.py",
                    "repo": "tripll",
                    "props": json.dumps(
                        {
                            "finding_id": "finding:ci:ruff-f401",
                            "kind": "ci_check",
                            "state": "open",
                            "rule_id": "ruff:F401",
                            "file": "src/a.py",
                            "severity": "error",
                        }
                    ),
                    **_PROV,
                },
            ]
        )
    finally:
        store.close()


def _seed_run(rr: RunsRoot, run_id: str = "run-l1") -> Path:
    run_dir = rr.processing_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _seed_graph_db(run_dir / ".tripll" / "graph.db")
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_run(lc, run_id=run_id, slug="l1-slug", source_mode="A", input_path="/tmp/x")
        insert_wave(
            lc,
            node_id="p:W1",
            run_id=run_id,
            plan_id="p",
            wave_id="W1",
            lane="core",
        )
        append_event(
            lc,
            run_id=run_id,
            node_id="p:W1",
            phase="running",
            last_action="editing",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.01,
        )
    return run_dir


def test_build_l1_panels_reads_graph_and_findings(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_graph_db(run_dir / ".tripll" / "graph.db")
    from tripll.ledger import WaveRow

    waves = [
        WaveRow(
            node_id="p:W1",
            run_id="r1",
            plan_id="p",
            wave_id="W1",
            lane="core",
            state="running",
            attempt_count=1,
            created_at="2026-07-25T00:00:00Z",
            updated_at="2026-07-25T00:00:00Z",
        )
    ]
    view = build_l1_panels(run_dir=run_dir, waves=waves, run_cost=1.25, repo_root=tmp_path)
    assert view.graph.available is True
    assert view.graph.node_count >= 1
    assert view.findings.available is True
    assert view.findings.total == 1
    assert "open" in view.findings.groups
    assert len(view.exits) >= 1


@pytest.fixture
def tmp_rr(tmp_path: Path) -> RunsRoot:
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    return rr


def test_run_detail_renders_l1_panels(tmp_rr: RunsRoot) -> None:
    _seed_run(tmp_rr, "run-l1-ui")
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as client:
        r = client.get("/runs/run-l1-ui")
    assert r.status_code == 200
    assert "Code factory L1" in r.text
    assert "Findings (1)" in r.text
    assert "Graph — wave W1" in r.text
    assert "Exits — caps" in r.text
    assert "Turn cap" in r.text
