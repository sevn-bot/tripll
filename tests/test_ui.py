"""Tests for W5 web dashboard (tripll.api.ui).

Covers:
- GET / returns 200 and lists seeded runs, profiles, and backends.
- GET /runs/{run_id} returns 200 and renders wave table with seeded node ids/phases.
- GET /runs/{run_id} 404 for unknown run.
- Approve / resume / pause buttons reference the correct API paths.
- Templates render without Jinja errors (no uncaught template exceptions).
- Static assets are served from /static/.
- Auth-token mode: GET / and GET /runs/{run_id} work in both dev and token modes.
- SSE URL in run_detail page uses token query param when token is configured.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tripll.api.app import create_app
from tripll.ledger import (
    append_event,
    insert_run,
    insert_wave,
    open_ledger,
    transition_run,
)
from tripll.pipeline import RunsRoot
from tripll.profiles import control_plane_db_path, open_profile_store, upsert_profile

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _seed_run(
    rr: RunsRoot,
    run_id: str = "r1",
    *,
    terminal: bool = False,
    nodes: list[str] | None = None,
) -> Path:
    """Create a minimal run directory + ledger with one or more waves.

    Args:
        rr: Active RunsRoot.
        run_id: Run identifier.
        terminal: Transition the run to ``done`` state.
        nodes: Wave node IDs to create (default: ``["p:W1"]``).

    Returns:
        Path: The run directory path.
    """
    if nodes is None:
        nodes = ["p:W1"]
    run_dir = rr.processing_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_run(lc, run_id=run_id, slug="test-slug", source_mode="A", input_path="/tmp/test")
        for node_id in nodes:
            parts = node_id.split(":")
            plan_id = parts[0]
            wave_id = parts[1] if len(parts) > 1 else node_id
            insert_wave(
                lc,
                node_id=node_id,
                run_id=run_id,
                plan_id=plan_id,
                wave_id=wave_id,
                lane="core",
            )
            append_event(
                lc,
                run_id=run_id,
                node_id=node_id,
                phase="running",
                last_action="editing foo.py",
                input_tokens=500,
                output_tokens=200,
                cost_usd=0.02,
            )
        if terminal:
            transition_run(lc, run_id, "done")
    return run_dir


def _seed_profile(rr: RunsRoot, profile_id: str = "test-profile") -> None:
    """Insert a test agent profile.

    Args:
        rr: Active RunsRoot.
        profile_id: Profile primary key.
    """
    db_path = control_plane_db_path(rr.root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open_profile_store(db_path) as store:
        upsert_profile(
            store,
            profile_id=profile_id,
            name="Test Profile",
            backend="claude_code",
            model="claude-3-5-sonnet",
            agent="wave-plan-executor",
        )


@pytest.fixture
def tmp_rr(tmp_path: Path) -> RunsRoot:
    """Configured and initialised RunsRoot in a temporary directory."""
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    return rr


@pytest.fixture
def client(tmp_rr: RunsRoot) -> TestClient:  # type: ignore[return]
    """TestClient with no auth token configured (dev mode)."""
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        yield tc  # type: ignore[misc]


@pytest.fixture
def client_authed(tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch) -> TestClient:  # type: ignore[return]
    """TestClient with TRIPLL_API_TOKEN set to 'test-token'."""
    monkeypatch.setenv("TRIPLL_API_TOKEN", "test-token")
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as tc:
        yield tc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 1. Dashboard home — GET /
# ---------------------------------------------------------------------------


def test_dashboard_home_returns_200(client: TestClient) -> None:
    """GET / returns 200 with HTML content-type."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_dashboard_home_lists_seeded_run(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / shows the seeded run ID in the page body."""
    _seed_run(tmp_rr, "run-ui-001")
    r = client.get("/")
    assert r.status_code == 200
    assert "run-ui-001" in r.text


def test_dashboard_home_links_to_run_detail(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / includes a link to /runs/{run_id} for each run."""
    _seed_run(tmp_rr, "run-link-test")
    r = client.get("/")
    assert r.status_code == 200
    assert "/runs/run-link-test" in r.text


def test_dashboard_home_shows_profiles(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / lists agent profiles when they exist."""
    _seed_profile(tmp_rr, "my-executor")
    r = client.get("/")
    assert r.status_code == 200
    assert "my-executor" in r.text
    assert "Test Profile" in r.text


def test_dashboard_home_shows_backends(client: TestClient) -> None:
    """GET / includes backend availability section with known backend names."""
    r = client.get("/")
    assert r.status_code == 200
    assert "claude_code" in r.text
    assert "cursor_local" in r.text


def test_dashboard_home_empty_state(client: TestClient) -> None:
    """GET / renders cleanly with no runs (no Jinja errors)."""
    r = client.get("/")
    assert r.status_code == 200
    # Should not raise template errors; basic structure present.
    assert "tripll" in r.text.lower()


# ---------------------------------------------------------------------------
# 2. Run detail — GET /runs/{run_id}
# ---------------------------------------------------------------------------


def test_run_detail_returns_200(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} returns 200 for a seeded run."""
    _seed_run(tmp_rr, "run-detail-001")
    r = client.get("/runs/run-detail-001")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_run_detail_404_unknown(client: TestClient) -> None:
    """GET /runs/{run_id} returns 404 for an unknown run."""
    r = client.get("/runs/no-such-run")
    assert r.status_code == 404


def test_run_detail_shows_run_id(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} renders the run_id in the page."""
    _seed_run(tmp_rr, "run-show-id")
    r = client.get("/runs/run-show-id")
    assert r.status_code == 200
    assert "run-show-id" in r.text


def test_run_detail_shows_wave_node_ids(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} shows seeded wave node IDs in the wave table."""
    _seed_run(tmp_rr, "run-waves", nodes=["plan:W1", "plan:W2"])
    r = client.get("/runs/run-waves")
    assert r.status_code == 200
    assert "plan:W1" in r.text
    assert "plan:W2" in r.text


def test_run_detail_shows_wave_phase(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} shows hydrated phase from latest event (D2)."""
    _seed_run(tmp_rr, "run-phase")
    r = client.get("/runs/run-phase")
    assert r.status_code == 200
    # Seeded event phase is "running"; hydration overrides initial "queued" wave state.
    assert "running" in r.text


def test_run_detail_wave_table_present(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} renders the waves table with expected column headers."""
    _seed_run(tmp_rr, "run-table")
    r = client.get("/runs/run-table")
    assert r.status_code == 200
    text = r.text
    assert "NODE ID" in text or "node_id" in text.lower() or "NODE" in text
    assert "PHASE" in text
    assert "CURRENT ACTION" in text
    assert "TOKENS" in text
    assert "COST" in text


# ---------------------------------------------------------------------------
# 3. Approve / resume / pause button wiring
# ---------------------------------------------------------------------------


def test_run_detail_approve_button_references_api(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} page includes approve button pointing to the API endpoint."""
    _seed_run(tmp_rr, "run-approve-btn")
    r = client.get("/runs/run-approve-btn")
    assert r.status_code == 200
    assert "/api/runs/run-approve-btn/approve" in r.text


def test_run_detail_resume_button_references_api(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} page includes resume button pointing to the API endpoint."""
    _seed_run(tmp_rr, "run-resume-btn")
    r = client.get("/runs/run-resume-btn")
    assert r.status_code == 200
    assert "/api/runs/run-resume-btn/resume" in r.text


def test_run_detail_pause_button_references_api(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} page includes pause button pointing to the API endpoint."""
    _seed_run(tmp_rr, "run-pause-btn")
    r = client.get("/runs/run-pause-btn")
    assert r.status_code == 200
    assert "/api/runs/run-pause-btn/pause" in r.text


def test_run_detail_buttons_use_htmx_post(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Approve / resume / pause buttons use hx-post (htmx POST attributes)."""
    _seed_run(tmp_rr, "run-htmx")
    r = client.get("/runs/run-htmx")
    assert r.status_code == 200
    assert "hx-post" in r.text


# ---------------------------------------------------------------------------
# 4. Static assets
# ---------------------------------------------------------------------------


def test_static_htmx_is_served(client: TestClient) -> None:
    """GET /static/htmx.min.js returns 200 (vendored htmx)."""
    r = client.get("/static/htmx.min.js")
    assert r.status_code == 200
    assert len(r.content) > 1000  # non-trivial file


def test_static_htmx_sse_is_served(client: TestClient) -> None:
    """GET /static/htmx-sse.js returns 200 (vendored htmx SSE extension)."""
    r = client.get("/static/htmx-sse.js")
    assert r.status_code == 200
    assert len(r.content) > 500


# ---------------------------------------------------------------------------
# 5. SSE live-update wiring in the page
# ---------------------------------------------------------------------------


def test_run_detail_embeds_sse_url(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} page embeds the SSE stream URL."""
    _seed_run(tmp_rr, "run-sse-url")
    r = client.get("/runs/run-sse-url")
    assert r.status_code == 200
    assert "/api/runs/run-sse-url/events/stream" in r.text


def test_run_detail_uses_eventsource_js(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} page uses EventSource for SSE (no server-side swap)."""
    _seed_run(tmp_rr, "run-eventsource")
    r = client.get("/runs/run-eventsource")
    assert r.status_code == 200
    assert "EventSource" in r.text


# ---------------------------------------------------------------------------
# 6. Auth-token mode
# ---------------------------------------------------------------------------


def test_dashboard_home_works_in_dev_mode(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / works without any token in dev mode."""
    _seed_run(tmp_rr, "run-dev")
    r = client.get("/")
    assert r.status_code == 200


def test_dashboard_home_works_with_token(client_authed: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / works even when TRIPLL_API_TOKEN is set (UI pages are public)."""
    _seed_run(tmp_rr, "run-authed-home")
    r = client_authed.get("/")
    assert r.status_code == 200


def test_run_detail_token_injected_in_sse_url(
    client_authed: TestClient, tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When token is set, run detail page injects token into SSE URL."""
    monkeypatch.setenv("TRIPLL_API_TOKEN", "test-token")
    _seed_run(tmp_rr, "run-token-sse")
    r = client_authed.get("/runs/run-token-sse")
    assert r.status_code == 200
    # The page JS should include ?token= in the SSE URL.
    assert "token" in r.text
    assert "test-token" in r.text


# ---------------------------------------------------------------------------
# 7. Auth dependency — ?token= query param accepted for SSE
# ---------------------------------------------------------------------------


def test_sse_accepts_token_query_param(tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE stream accepts ?token= query param when TRIPLL_API_TOKEN is set."""
    monkeypatch.setenv("TRIPLL_API_TOKEN", "secret-tok")
    _seed_run(tmp_rr, "run-tok-q", terminal=True)
    app = create_app(runs_root=tmp_rr.root)
    monkeypatch.setenv("TRIPLL_SSE_POLL", "0.05")
    with TestClient(app) as tc:
        # Without token — should 401.
        r_no = tc.get("/api/runs/run-tok-q/events/stream")
        assert r_no.status_code == 401

        # With token in query param — should 200.
        r_ok = tc.get("/api/runs/run-tok-q/events/stream?token=secret-tok")
        assert r_ok.status_code == 200


def test_sse_rejects_wrong_token_query_param(
    tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE stream rejects wrong ?token= value."""
    monkeypatch.setenv("TRIPLL_API_TOKEN", "real-tok")
    _seed_run(tmp_rr, "run-bad-tok", terminal=True)
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        r = tc.get("/api/runs/run-bad-tok/events/stream?token=wrong-tok")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 8. Back-navigation
# ---------------------------------------------------------------------------


def test_run_detail_has_back_link(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} page includes a link back to the dashboard."""
    _seed_run(tmp_rr, "run-back")
    r = client.get("/runs/run-back")
    assert r.status_code == 200
    # The back-link should point to /.
    assert 'href="/"' in r.text


# ---------------------------------------------------------------------------
# 9. Multiple waves
# ---------------------------------------------------------------------------


def test_run_detail_multi_wave_rows(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} renders one table row per wave."""
    _seed_run(tmp_rr, "run-multi", nodes=["plan:W1", "plan:W2", "plan:W3"])
    r = client.get("/runs/run-multi")
    assert r.status_code == 200
    text = r.text
    assert "plan:W1" in text
    assert "plan:W2" in text
    assert "plan:W3" in text


# ---------------------------------------------------------------------------
# 10. No subprocess calls in UI pages
# ---------------------------------------------------------------------------


def test_dashboard_home_does_not_spawn_subprocess(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / never spawns a subprocess (read-only page)."""
    _seed_run(tmp_rr, "run-no-proc")
    with patch("subprocess.Popen") as mock_popen:
        r = client.get("/")
    assert r.status_code == 200
    mock_popen.assert_not_called()


def test_run_detail_does_not_spawn_subprocess(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{run_id} never spawns a subprocess (read-only page)."""
    _seed_run(tmp_rr, "run-detail-no-proc")
    with patch("subprocess.Popen") as mock_popen:
        r = client.get("/runs/run-detail-no-proc")
    assert r.status_code == 200
    mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# 11. W4 fragment routes (batch timeline, report)
# ---------------------------------------------------------------------------


def test_w4_batch_timeline_fragment(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id}/batch-timeline renders swimlanes from graph.json (W4.1)."""
    import json

    run_dir = _seed_run(tmp_rr, "r-batch", nodes=["p:W0", "p:W1"])
    graph = {
        "run_id": "r-batch",
        "batches": [
            {"batch_id": "Pre-0", "label": "gate", "wave_ids": ["W0"], "is_human_gate": True},
            {"batch_id": "A", "label": "first", "wave_ids": ["W1"], "is_human_gate": False},
        ],
        "nodes": {
            "p:W0": {"node_id": "p:W0", "wave_id": "W0", "lane": "core"},
            "p:W1": {"node_id": "p:W1", "wave_id": "W1", "lane": "core"},
        },
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")

    r = client.get("/runs/r-batch/batch-timeline")
    assert r.status_code == 200
    assert "batch-timeline" in r.text
    assert "Pre-0" in r.text
    assert "badge-running" in r.text
    assert "graph.json" in r.text


def test_w4_report_fragment_404_when_missing(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id}/report returns 404 when report.md is absent (W4.4)."""
    _seed_run(tmp_rr, "r-no-report")
    r = client.get("/runs/r-no-report/report")
    assert r.status_code == 404


def test_w4_report_fragment_renders_markdown(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id}/report renders report.md as HTML (W4.3)."""
    run_dir = _seed_run(tmp_rr, "r-report")
    (run_dir / "report.md").write_text("# Run report\n\n- **State:** active\n", encoding="utf-8")
    r = client.get("/runs/r-report/report")
    assert r.status_code == 200
    assert "<h1>" in r.text
    assert "Run report" in r.text


def test_w3_worktree_fragment_not_stub(client: TestClient, tmp_rr: RunsRoot) -> None:
    """W3 worktree fragment is implemented (not 501)."""
    _seed_run(tmp_rr, "r1", nodes=["p:W1"])
    r = client.get("/runs/r1/waves/p:W1/worktree")
    assert r.status_code == 200
    assert "W0 stub" not in r.text


def test_w1_timeline_fragment_not_stub(client: TestClient, tmp_rr: RunsRoot) -> None:
    """W1 timeline fragment is implemented (not 501)."""
    _seed_run(tmp_rr, "r1")
    r = client.get("/runs/r1/timeline")
    assert r.status_code == 200
    assert "W0 stub" not in r.text


def test_w1_log_fragment_not_stub(client: TestClient, tmp_rr: RunsRoot) -> None:
    """W1 log fragment is implemented (not 501)."""
    run_dir = _seed_run(tmp_rr, "r1", nodes=["p:W1"])
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs" / "p_W1-attempt1.log").write_text("ok\n", encoding="utf-8")
    r = client.get("/runs/r1/waves/p:W1/log")
    assert r.status_code == 200
    assert "W0 stub" not in r.text
