"""W1-W2 dashboard UI tests - run detail, nav chrome, forms."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.test_ui import _seed_profile, _seed_run
from tripll.api.app import create_app
from tripll.ledger import (
    append_event,
    end_attempt,
    insert_attempt,
    insert_run,
    insert_wave,
    open_ledger,
    transition_run,
    transition_wave,
)
from tripll.pipeline import RunsRoot
from tripll.profiles import control_plane_db_path, get_profile, open_profile_store


@pytest.fixture
def client(tmp_path: Path) -> TestClient:  # type: ignore[return]
    """TestClient with a fresh runs root (dev auth mode)."""
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    app = create_app(runs_root=rr.root)
    with TestClient(app) as tc:
        tc.app.state._test_rr = rr  # type: ignore[attr-defined]
        yield tc  # type: ignore[misc]


@pytest.fixture
def tmp_rr(client: TestClient) -> RunsRoot:
    """RunsRoot attached to the test client."""
    return client.app.state._test_rr  # type: ignore[attr-defined, no-any-return]


def test_run_detail_hydrates_event_fields(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} merges latest_events_by_node into wave rows on first paint."""
    _seed_run(tmp_rr, "run-hydrate")
    r = client.get("/runs/run-hydrate")
    assert r.status_code == 200
    assert "editing foo.py" in r.text
    assert "500→200" in r.text
    assert "$0.0200" in r.text
    assert "badge-running" in r.text


def test_run_detail_shows_run_header(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} renders run header with state, cost, and live badge."""
    _seed_run(tmp_rr, "run-header")
    r = client.get("/runs/run-header")
    assert r.status_code == 200
    assert "Run cost:" in r.text
    assert "run-header-meta" in r.text


def test_run_detail_includes_event_timeline(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} embeds #event-timeline with seeded events."""
    _seed_run(tmp_rr, "run-timeline")
    r = client.get("/runs/run-timeline")
    assert r.status_code == 200
    assert 'id="event-timeline"' in r.text
    assert "editing foo.py" in r.text


def test_timeline_fragment_returns_events(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id}/timeline returns timeline partial HTML."""
    _seed_run(tmp_rr, "run-tl-frag")
    r = client.get("/runs/run-tl-frag/timeline")
    assert r.status_code == 200
    assert "timeline-row" in r.text
    assert "editing foo.py" in r.text


def test_log_fragment_returns_tail(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id}/waves/{node}/log returns log tail via safe resolver."""
    run_dir = _seed_run(tmp_rr, "run-log", nodes=["p:W1"])
    logs = run_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "p_W1-attempt1.log").write_text("line one\nline two\n", encoding="utf-8")

    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_attempt(lc, run_id="run-log", node_id="p:W1", attempt_n=1, backend="claude_code")

    r = client.get("/runs/run-log/waves/p:W1/log")
    assert r.status_code == 200
    assert "line two" in r.text
    assert "log-content" in r.text


def test_api_wave_log_json(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /api/runs/{id}/waves/{node}/log returns JSON tail payload."""
    run_dir = _seed_run(tmp_rr, "run-api-log", nodes=["p:W1"])
    logs = run_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "p_W1-attempt1.log").write_text("api log line\n", encoding="utf-8")

    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_attempt(lc, run_id="run-api-log", node_id="p:W1", attempt_n=1, backend="claude_code")

    r = client.get("/api/runs/run-api-log/waves/p:W1/log")
    assert r.status_code == 200
    body = r.json()
    assert body["attempt_n"] == 1
    assert "api log line" in body["content"]


def test_api_wave_log_json_no_attempts(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Undispatched waves return a friendly message without filesystem paths."""
    _seed_run(tmp_rr, "run-no-log", nodes=["p:W0"])
    r = client.get("/api/runs/run-no-log/waves/p:W0/log")
    assert r.status_code == 200
    body = r.json()
    assert body["attempt_n"] is None
    assert body["available"] is False
    assert "not dispatched" in body["content"]
    assert "/logs/" not in body["content"]


def test_log_fragment_no_attempts(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Log fragment for gate-only waves shows empty-state copy, not a missing file path."""
    run_dir = tmp_rr.processing_dir / "run-gate-log"
    run_dir.mkdir(parents=True, exist_ok=True)
    with open_ledger(run_dir / "ledger.db") as lc:
        insert_run(
            lc,
            run_id="run-gate-log",
            slug="test-slug",
            source_mode="A",
            input_path="/tmp/test",
        )
        insert_wave(
            lc,
            node_id="p:W0",
            run_id="run-gate-log",
            plan_id="p",
            wave_id="W0",
            lane="core",
        )
    r = client.get("/runs/run-gate-log/waves/p:W0/log")
    assert r.status_code == 200
    assert "No agent log yet" in r.text
    assert "not dispatched" in r.text
    assert "/logs/" not in r.text


def _seed_failed_run_with_escalation(rr: RunsRoot, run_id: str) -> Path:
    """Seed a failed run with blocked waves and escalation.md reasons."""
    run_dir = rr.failed_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_run(lc, run_id=run_id, slug="test-slug", source_mode="A", input_path="/tmp/test")
        for node_id, wave_id, state in [
            ("p:W0", "W0", "done"),
            ("p:R1", "R1", "blocked"),
            ("p:R2", "R2", "blocked"),
        ]:
            insert_wave(
                lc,
                node_id=node_id,
                run_id=run_id,
                plan_id="p",
                wave_id=wave_id,
                lane="core",
            )
            transition_wave(lc, run_id, node_id, state)
        append_event(
            lc,
            run_id=run_id,
            node_id="p:W0",
            phase="done",
            last_action="Human gate completed",
        )
        append_event(
            lc,
            run_id=run_id,
            node_id="p:R1",
            phase="blocked",
            last_action="attempt 1 failed: error: unknown option '--add-dir'",
        )
        aid = insert_attempt(
            lc,
            run_id=run_id,
            node_id="p:R1",
            attempt_n=1,
            backend="cursor_local",
        )
        end_attempt(
            lc,
            aid,
            outcome="failed",
            evidence="error: unknown option '--add-dir'",
        )
        transition_run(lc, run_id, "failed")
    run_dir.joinpath("escalation.md").write_text(
        "# Escalation — run-fail\n\n"
        "Blocked waves (5 attempts exhausted):\n\n"
        "- p:R1 (1 attempts): no-progress escalation after 1 dispatch(es) produced no edits\n"
        "- p:R2 (0 attempts): dependency deadlock — 1 node(s) undrained but none are ready\n",
        encoding="utf-8",
    )
    return run_dir


def test_run_detail_shows_blocked_wave_failure_reasons(
    client: TestClient, tmp_rr: RunsRoot
) -> None:
    """Blocked waves surface escalation / attempt failure text in wave panels."""
    _seed_failed_run_with_escalation(tmp_rr, "run-fail-reasons")
    r = client.get("/runs/run-fail-reasons")
    assert r.status_code == 200
    assert "wave-status-detail" in r.text
    assert "unknown option" in r.text
    assert "add-dir" in r.text
    assert "dependency deadlock" in r.text
    assert "Human gate completed" in r.text


def test_worktree_fragment_shows_blocked_reason_without_worktree(
    client: TestClient, tmp_rr: RunsRoot
) -> None:
    """Worktree panel shows escalation reason when no worktree exists."""
    _seed_failed_run_with_escalation(tmp_rr, "run-wt-reason")
    r = client.get("/runs/run-wt-reason/waves/p:R2/worktree")
    assert r.status_code == 200
    assert "dependency deadlock" in r.text
    assert "Worktree not allocated yet" not in r.text


def test_log_fragment_blocked_without_attempts_shows_deadlock_reason(
    client: TestClient, tmp_rr: RunsRoot
) -> None:
    """Log panel for deadlock-blocked waves shows escalation text, not generic empty state."""
    _seed_failed_run_with_escalation(tmp_rr, "run-log-deadlock")
    r = client.get("/runs/run-log-deadlock/waves/p:R2/log")
    assert r.status_code == 200
    assert "dependency deadlock" in r.text
    assert "No agent log yet" not in r.text


def test_timeline_fragment_404_unknown(client: TestClient) -> None:
    """GET /runs/{id}/timeline returns 404 for unknown run."""
    r = client.get("/runs/missing-run/timeline")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# W2 — nav chrome, forms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "section"),
    [
        ("/", "Agents"),
        ("/agents", "Agents"),
        ("/settings", "Settings"),
    ],
)
def test_nav_renders_on_pages(client: TestClient, path: str, section: str) -> None:
    """Top nav (D8) renders on home, agents, and settings pages."""
    r = client.get(path)
    assert r.status_code == 200
    assert "top-nav" in r.text
    assert "Agents" in r.text
    assert "Runs" in r.text
    assert "Settings" in r.text
    assert 'href="/docs"' in r.text


def test_nav_renders_on_run_detail(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Top nav renders on run detail pages."""
    _seed_run(tmp_rr, "run-nav")
    r = client.get("/runs/run-nav")
    assert r.status_code == 200
    assert "top-nav" in r.text


def test_favicon_linked(client: TestClient) -> None:
    """base.html links the favicon and static asset is served."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/static/favicon.svg"' in r.text
    fav = client.get("/static/favicon.svg")
    assert fav.status_code == 200
    assert b"<svg" in fav.content


def test_launch_form_renders(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET / includes launch-run form with input sets and profiles."""
    _seed_profile(tmp_rr, "launch-profile")
    input_dir = tmp_rr.input_dir / "my-set"
    input_dir.mkdir(parents=True)
    r = client.get("/")
    assert r.status_code == 200
    assert 'action="/launch"' in r.text
    assert "my-set" in r.text
    assert "launch-profile" in r.text


def test_launch_form_redirects(client: TestClient, tmp_rr: RunsRoot, tmp_path: Path) -> None:
    """POST /launch spawns subprocess and redirects to matching live run."""
    _seed_profile(tmp_rr, "go")
    input_dir = tmp_path / "my-waves"
    input_dir.mkdir()

    run_dir = tmp_rr.processing_dir / "run-launched"
    run_dir.mkdir(parents=True)
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_run(
            lc,
            run_id="run-launched",
            slug="my-waves",
            source_mode="A",
            input_path=str(input_dir),
        )
    (run_dir / "engine.pid").write_text(str(os.getpid()), encoding="utf-8")

    with patch("tripll.api.ui.router.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=55555)
        with patch("tripll.api.ui.router.asyncio.sleep"):
            r = client.post(
                "/launch",
                data={"input_path": str(input_dir), "profile_id": "go"},
                follow_redirects=False,
            )
    assert r.status_code == 303
    assert r.headers["location"].endswith("/runs/run-launched")
    mock_popen.assert_called_once()


def test_agents_list_page(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /agents lists profiles with edit links."""
    _seed_profile(tmp_rr, "listed-profile")
    r = client.get("/agents")
    assert r.status_code == 200
    assert "listed-profile" in r.text
    assert "/agents/listed-profile/edit" in r.text


def test_create_agent_form_post(client: TestClient, tmp_rr: RunsRoot) -> None:
    """POST /agents/new creates a profile and redirects to /agents."""
    r = client.post(
        "/agents/new",
        data={
            "name": "UI Agent",
            "backend": "claude_code",
            "model": "claude-3-5-sonnet",
            "agent": "wave-plan-executor",
            "skills": '["skill-a"]',
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("/agents")

    db_path = control_plane_db_path(tmp_rr.root)
    with open_profile_store(db_path) as store:
        row = get_profile(store, "ui-agent")
    assert row.name == "UI Agent"
    assert row.skills == ["skill-a"]


def test_edit_agent_form_post(client: TestClient, tmp_rr: RunsRoot) -> None:
    """POST /agents/{id}/edit updates a profile."""
    _seed_profile(tmp_rr, "edit-me")
    r = client.post(
        "/agents/edit-me/edit",
        data={
            "name": "Renamed",
            "backend": "claude_code",
            "model": "new-model",
            "agent": "wave-plan-executor",
            "skills": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    db_path = control_plane_db_path(tmp_rr.root)
    with open_profile_store(db_path) as store:
        row = get_profile(store, "edit-me")
    assert row.name == "Renamed"
    assert row.model == "new-model"


def test_settings_form_get_and_post(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /settings shows config; POST updates env vars."""
    monkeypatch.delenv("TRIPLL_MAX_PARALLEL", raising=False)
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Max parallel" in r.text

    r2 = client.post(
        "/settings",
        data={
            "model_default": "test-model",
            "cost_budget_usd": "12.5",
            "max_parallel": "7",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert "saved=1" in r2.headers["location"]
    assert os.environ.get("TRIPLL_MAX_PARALLEL") == "7"
    assert os.environ.get("TRIPLL_DEFAULT_MODEL") == "test-model"


# ---------------------------------------------------------------------------
# W3 — attempts, wave tasks, worktree, SSE extensions
# ---------------------------------------------------------------------------


def test_run_detail_shows_attempt_history(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} renders attempt table and current attempt badge (W3.1)."""
    run_dir = _seed_run(tmp_rr, "run-attempts", nodes=["p:W1"])
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        from tripll.ledger import end_attempt, insert_attempt

        aid1 = insert_attempt(
            lc, run_id="run-attempts", node_id="p:W1", attempt_n=1, backend="claude_code"
        )
        end_attempt(lc, aid1, outcome="failed", evidence="tests red")
        insert_attempt(
            lc, run_id="run-attempts", node_id="p:W1", attempt_n=2, backend="claude_code"
        )

    r = client.get("/runs/run-attempts")
    assert r.status_code == 200
    assert "attempts-panel" in r.text
    assert "Attempt 2" in r.text or "attempt 2" in r.text
    assert "failed" in r.text


def test_tasks_fragment_renders_checklist(
    client: TestClient, tmp_rr: RunsRoot, tmp_path: Path
) -> None:
    """GET /runs/{id}/waves/{node}/tasks renders inferred checklist (W3.3)."""
    run_dir = _seed_run(tmp_rr, "run-tasks", nodes=["p:W1"])
    wt_dir = run_dir / "worktrees" / "core-w1"
    staged = wt_dir / "plan" / "tripll"
    staged.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "wave-plan-w0-slice.md"
    (staged / "demo-wave-W1.md").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    r = client.get("/runs/run-tasks/waves/p:W1/tasks")
    assert r.status_code == 200
    assert "wave-task-checklist" in r.text
    assert "W0.1" in r.text


def test_log_append_returns_new_bytes(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET .../log/append returns bytes after offset for live panel polling."""
    run_dir = _seed_run(tmp_rr, "run-log-append", nodes=["p:W1"])
    logs = run_dir / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / "p_W1-attempt1.log"
    log_path.write_text("alpha\n", encoding="utf-8")
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_attempt(
            lc, run_id="run-log-append", node_id="p:W1", attempt_n=1, backend="cursor_local"
        )

    r0 = client.get("/runs/run-log-append/waves/p:W1/log/append?offset=0")
    assert r0.status_code == 200
    data0 = r0.json()
    assert data0["text"] == "alpha\n"
    assert data0["offset"] == len(b"alpha\n")

    log_path.write_text("alpha\nbeta\n", encoding="utf-8")
    r1 = client.get(f"/runs/run-log-append/waves/p:W1/log/append?offset={data0['offset']}")
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["text"] == "beta\n"


def test_worktree_fragment_mocked_git(
    client: TestClient, tmp_rr: RunsRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /runs/{id}/waves/{node}/worktree returns git status summary (W3.4)."""
    from tripll.api._worktree_status import WorktreeStatus

    _seed_run(tmp_rr, "run-wt", nodes=["p:W1"])
    fake = WorktreeStatus(
        branch="wave/run-wt/core-w1",
        changed_count=1,
        changed_paths=["src/foo.py"],
        diff_stat_lines=[" src/foo.py | 2 +-"],
        head_sha="a" * 40,
    )
    monkeypatch.setattr(
        "tripll.api.ui.router.collect_worktree_status",
        lambda _path: fake,
    )
    monkeypatch.setattr(
        "tripll.api.ui.router.resolve_wave_worktree_path",
        lambda *_a, **_k: tmp_path / "wt",
    )

    r = client.get("/runs/run-wt/waves/p:W1/worktree")
    assert r.status_code == 200
    assert "src/foo.py" in r.text
    assert "wave/run-wt/core-w1" in r.text


def test_worktree_poll_stops_when_phase_done(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Done waves omit 5s htmx poll trigger (W3.4 / D5)."""
    run_dir = _seed_run(tmp_rr, "run-wt-done", nodes=["p:W1"], terminal=False)
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        from tripll.ledger import append_event

        append_event(lc, run_id="run-wt-done", node_id="p:W1", phase="done")

    r = client.get("/runs/run-wt-done")
    assert r.status_code == 200
    assert 'hx-trigger="load, every 5s"' not in r.text
    assert 'data-poll-worktree="false"' in r.text


def test_sse_payload_includes_attempt_n(tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE stream includes optional attempt_n on dispatched events (W3.2)."""
    run_dir = _seed_run(tmp_rr, "run-sse-attempt", nodes=["p:W1"], terminal=True)
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        from tripll.ledger import append_event

        append_event(
            lc,
            run_id="run-sse-attempt",
            node_id="p:W1",
            phase="dispatched",
            attempt_n=2,
        )

    monkeypatch.setenv("TRIPLL_SSE_POLL", "0.05")
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        r = tc.get("/api/runs/run-sse-attempt/events/stream")
        assert r.status_code == 200
        assert '"attempt_n": 2' in r.text


def test_api_worktree_json(
    client: TestClient, tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/runs/{id}/waves/{node}/worktree returns JSON schema (D5)."""
    from tripll.api._worktree_status import WorktreeStatus

    _seed_run(tmp_rr, "run-api-wt", nodes=["p:W1"])
    fake = WorktreeStatus(
        branch="main",
        changed_count=0,
        changed_paths=[],
        diff_stat_lines=[],
        head_sha="b" * 40,
    )
    monkeypatch.setattr(
        "tripll.api.app.collect_worktree_status",
        lambda _path: fake,
    )
    monkeypatch.setattr(
        "tripll.api.app.resolve_wave_worktree_path",
        lambda *_a, **_k: Path("/tmp/wt"),
    )

    r = client.get("/api/runs/run-api-wt/waves/p:W1/worktree")
    assert r.status_code == 200
    body = r.json()
    assert body["branch"] == "main"
    assert body["head_sha"] == "b" * 40


# ---------------------------------------------------------------------------
# W4 — batch timeline, pause banners, report embed
# ---------------------------------------------------------------------------


def test_run_detail_shows_quota_pause_banner(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} shows quota pause banner when marker file exists (W4.2, D10)."""
    run_dir = _seed_run(tmp_rr, "run-quota-pause")
    (run_dir / "quota-paused.md").write_text(
        "Session quota exceeded — resume after reset\nmore detail",
        encoding="utf-8",
    )
    r = client.get("/runs/run-quota-pause")
    assert r.status_code == 200
    assert "pause-banners" in r.text
    assert "banner-quota" in r.text
    assert "Session quota exceeded" in r.text
    assert "quota-paused.md" in r.text


def test_run_detail_includes_batch_timeline(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} embeds batch timeline section from graph.json (W4.1)."""
    import json

    run_dir = _seed_run(tmp_rr, "run-batch-ui", nodes=["core:W0", "core:W1"])
    graph = {
        "run_id": "run-batch-ui",
        "batches": [
            {"batch_id": "A", "label": "parallel", "wave_ids": ["W0", "W1"]},
        ],
        "nodes": {
            "core:W0": {"node_id": "core:W0", "wave_id": "W0"},
            "core:W1": {"node_id": "core:W1", "wave_id": "W1"},
        },
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")

    r = client.get("/runs/run-batch-ui")
    assert r.status_code == 200
    assert 'id="batch-timeline"' in r.text
    assert "batch-lane" in r.text


# ---------------------------------------------------------------------------
# W5 — orchestrator panel + feed
# ---------------------------------------------------------------------------


def _seed_orchestrator_panel_status(run_dir: Path, run_id: str) -> None:
    """Write orchestrator-status.md with in-progress wave + review gate (W5.1)."""
    from tripll.graph import OrchestratorConfig, RunGraph
    from tripll.orchestrator_status import (
        OrchestratorTurn,
        StatusRow,
        append_turn,
        sync_orchestrator_status,
    )

    sync_orchestrator_status(
        run_dir,
        RunGraph(
            run_id=run_id,
            orchestrator=OrchestratorConfig(
                enabled=True,
                prompt_path="p.md",
                feature_branch="feature/tripll-orchestrator-mode",
                serial_waves=["W0", "W1"],
            ),
        ),
        rows=[
            StatusRow(
                "W0", status="done", branch="feature/tripll-orchestrator-mode", commit="abc1234"
            ),
            StatusRow("W1", status="in progress", branch="feature/tripll-orchestrator-mode"),
        ],
        turn=OrchestratorTurn("wave_dispatched", "Dispatching wave-runner for **W1** (`p:W1`)"),
    )
    append_turn(
        run_dir,
        OrchestratorTurn(
            "review_gate",
            "**AWAITING REVIEW** (W0.8) — approve before next wave",
        ),
    )


def _seed_orchestrator_summary_status(run_dir: Path, run_id: str) -> None:
    """Write orchestrator-status.md with completed wave summary for header (W5.5)."""
    from tripll.graph import OrchestratorConfig, RunGraph
    from tripll.orchestrator_status import OrchestratorTurn, StatusRow, sync_orchestrator_status

    sync_orchestrator_status(
        run_dir,
        RunGraph(
            run_id=run_id,
            orchestrator=OrchestratorConfig(
                enabled=True,
                prompt_path="p.md",
                feature_branch="feature/tripll-orchestrator-mode",
                serial_waves=["W0", "W1"],
            ),
        ),
        rows=[
            StatusRow(
                "W0", status="done", branch="feature/tripll-orchestrator-mode", commit="abc1234"
            ),
            StatusRow("W1", status="pending", branch="feature/tripll-orchestrator-mode"),
        ],
        turn=OrchestratorTurn(
            "wave_complete",
            "**W0** complete",
            wave_summary="W0 design locked — orchestrator contracts approved.",
        ),
    )


def test_orchestrator_panel_has_status_table_headers(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id} orchestrator panel renders status table columns (W5.1)."""
    run_dir = _seed_run(tmp_rr, "run-orch-panel", nodes=["p:W0", "p:W1"])
    _seed_orchestrator_panel_status(run_dir, "run-orch-panel")
    r = client.get("/runs/run-orch-panel")
    assert r.status_code == 200
    assert "orchestrator-section" in r.text
    assert "Evidence / blockers" in r.text
    assert "Current wave:" in r.text
    assert "REVIEW GATE" in r.text or "AWAITING REVIEW" in r.text
    assert "Next action:" in r.text


def test_orchestrator_fragment_returns_feed(client: TestClient, tmp_rr: RunsRoot) -> None:
    """GET /runs/{id}/orchestrator returns panel + feed partial (W5.2, W5.3)."""
    run_dir = _seed_run(tmp_rr, "run-orch-frag", nodes=["p:W0"])
    _seed_orchestrator_panel_status(run_dir, "run-orch-frag")
    r = client.get("/runs/run-orch-frag/orchestrator")
    assert r.status_code == 200
    assert "orchestrator-feed" in r.text
    assert "badge-orch-review_gate" in r.text or "review_gate" in r.text


def test_run_header_shows_wave_summary_when_terminal(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Run header shows wave_summary one-liner when current wave terminal (W5.5)."""
    run_dir = _seed_run(tmp_rr, "run-orch-summary", nodes=["p:W0"], terminal=True)
    _seed_orchestrator_summary_status(run_dir, "run-orch-summary")
    r = client.get("/runs/run-orch-summary")
    assert r.status_code == 200
    assert "run-wave-summary" in r.text
    assert "W0 design locked" in r.text


def test_orchestrator_live_poll_trigger(client: TestClient, tmp_rr: RunsRoot) -> None:
    """Live runs poll orchestrator fragment every 2s (W5.4, D13)."""
    run_dir = _seed_run(tmp_rr, "run-orch-live", nodes=["p:W0"], terminal=False)
    (run_dir / "engine.pid").write_text(str(os.getpid()), encoding="utf-8")
    _seed_orchestrator_panel_status(run_dir, "run-orch-live")
    r = client.get("/runs/run-orch-live")
    assert r.status_code == 200
    assert 'hx-trigger="load, every 2s"' in r.text or 'hx-trigger="load, every 2.0s"' in r.text


def test_sse_delivers_orchestrator_phase_event(
    tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE stream includes phase=orchestrator events for client filter (W5.3, W5.6)."""
    run_dir = _seed_run(tmp_rr, "run-orch-sse", nodes=["p:W0"], terminal=True)
    _seed_orchestrator_panel_status(run_dir, "run-orch-sse")
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        from tripll.ledger import ORCHESTRATOR_NODE_ID, append_event

        append_event(
            lc,
            run_id="run-orch-sse",
            node_id=ORCHESTRATOR_NODE_ID,
            phase="orchestrator",
            last_action="AWAITING REVIEW (W0.8)",
            metadata='{"turn_type":"review_gate","excerpt":"AWAITING REVIEW"}',
        )

    monkeypatch.setenv("TRIPLL_SSE_POLL", "0.05")
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        r = tc.get("/api/runs/run-orch-sse/events/stream")
        assert r.status_code == 200
        assert '"phase": "orchestrator"' in r.text
        assert "review_gate" in r.text
