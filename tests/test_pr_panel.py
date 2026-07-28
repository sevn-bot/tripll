"""Dashboard PR panel — merge gate UX (code-factory Q5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_ui_auth import AUTH_HEADER, _post_with_auth_and_csrf
from tripll.api._pr_panel import build_pr_panel
from tripll.api.app import create_app
from tripll.ledger import insert_run, insert_wave, open_ledger
from tripll.loops.l1_pr import MERGE_APPROVED_MARKER, park_at_merge_gate
from tripll.pipeline import RunsRoot


def _seed_run(rr: RunsRoot, run_id: str = "run-pr-ui") -> Path:
    run_dir = rr.processing_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open_ledger(run_dir / "ledger.db") as lc:
        insert_run(lc, run_id=run_id, slug="pr-slug", source_mode="A", input_path="/tmp/x")
        insert_wave(
            lc,
            node_id="p:W1",
            run_id=run_id,
            plan_id="p",
            wave_id="W1",
            lane="core",
        )
    return run_dir


def test_build_pr_panel_merge_gate_pending(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    park_at_merge_gate(run_dir=run_dir, ci_green=True, review_clean=True)
    view = build_pr_panel(run_dir=run_dir)
    assert view.merge_gate_pending is True
    assert view.can_approve is True
    assert view.state == "merge_gate_pending"
    assert view.ci_green is True
    assert view.review_clean is True


def test_build_pr_panel_merge_approved(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    park_at_merge_gate(run_dir=run_dir)
    (run_dir / MERGE_APPROVED_MARKER).write_text('{"approved": true}', encoding="utf-8")
    view = build_pr_panel(run_dir=run_dir)
    assert view.merge_approved is True
    assert view.can_approve is False
    assert view.state == "merge_approved"


def test_run_detail_renders_merge_gate_pending(tmp_path: Path) -> None:
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    run_dir = _seed_run(rr, "run-gate-pending")
    park_at_merge_gate(run_dir=run_dir, ci_green=True, review_clean=False)

    app = create_app(runs_root=rr.root)
    with TestClient(app) as client:
        r = client.get("/runs/run-gate-pending")
    assert r.status_code == 200
    assert "PR phase" in r.text
    assert "Merge gate pending" in r.text
    assert "badge-merge_gate_pending" in r.text
    assert "Approve merge gate" in r.text
    assert 'action="/runs/run-gate-pending/pr/approve-merge"' in r.text


def test_run_detail_renders_merge_approved(tmp_path: Path) -> None:
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    run_dir = _seed_run(rr, "run-gate-approved")
    park_at_merge_gate(run_dir=run_dir)
    (run_dir / MERGE_APPROVED_MARKER).write_text(json.dumps({"approved": True}), encoding="utf-8")

    app = create_app(runs_root=rr.root)
    with TestClient(app) as client:
        r = client.get("/runs/run-gate-approved")
    assert r.status_code == 200
    assert "Merge gate approved" in r.text
    assert "Approve merge gate" not in r.text


@pytest.fixture
def token_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TRIPLL_API_TOKEN", "test-token-secret")
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    _seed_run(rr, "run-pr-auth")
    park_at_merge_gate(run_dir=rr.processing_dir / "run-pr-auth")
    app = create_app(runs_root=rr.root)
    with TestClient(app) as tc:
        yield tc


def test_pr_approve_merge_form_requires_auth(token_client: TestClient) -> None:
    response = token_client.post("/runs/run-pr-auth/pr/approve-merge", data={})
    assert response.status_code in (401, 403)


def test_pr_approve_merge_form_requires_csrf(token_client: TestClient) -> None:
    response = token_client.post(
        "/runs/run-pr-auth/pr/approve-merge",
        data={},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 403


def test_pr_approve_merge_form_succeeds_with_csrf(
    token_client: TestClient,
    tmp_path: Path,
) -> None:
    response = _post_with_auth_and_csrf(token_client, "/runs/run-pr-auth/pr/approve-merge", {})
    assert response.status_code == 303
    assert "pr_msg=" in response.headers["location"]
    run_dir = tmp_path / "runs" / "processing" / "run-pr-auth"
    assert (run_dir / MERGE_APPROVED_MARKER).is_file()


def test_api_pr_approve_merge(token_client: TestClient, tmp_path: Path) -> None:
    rr = RunsRoot(tmp_path / "runs")
    run_dir = rr.processing_dir / "run-api-pr"
    run_dir.mkdir(parents=True, exist_ok=True)
    park_at_merge_gate(run_dir=run_dir)

    response = token_client.post(
        "/api/runs/run-api-pr/pr/approve-merge",
        headers=AUTH_HEADER,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"]["state"] == "merge_approved"
    assert (run_dir / MERGE_APPROVED_MARKER).is_file()


def test_api_pr_status_merge_gate_pending(token_client: TestClient, tmp_path: Path) -> None:
    rr = RunsRoot(tmp_path / "runs")
    run_dir = rr.processing_dir / "run-api-status"
    run_dir.mkdir(parents=True, exist_ok=True)
    park_at_merge_gate(run_dir=run_dir, ci_green=True, review_clean=True)

    response = token_client.get(
        "/api/runs/run-api-status/pr/status",
        headers=AUTH_HEADER,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "merge_gate_pending"
    assert body["merge_gate_pending"] is True


def test_api_pr_approve_merge_without_pending_returns_409(token_client: TestClient) -> None:
    response = token_client.post(
        "/api/runs/run-pr-auth/pr/approve-merge",
        headers=AUTH_HEADER,
    )
    assert response.status_code in (202, 409)
    if response.status_code == 202:
        retry = token_client.post(
            "/api/runs/run-pr-auth/pr/approve-merge",
            headers=AUTH_HEADER,
        )
        assert retry.status_code == 409
