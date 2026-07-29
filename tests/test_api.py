"""Tests for W4 FastAPI control-plane (tripll.api).

Covers:
- GET /health — always 200.
- Agent/profile CRUD: create, list, get, patch, delete; reuse guarantee.
- GET /api/runs — lists runs from ledger.
- GET /api/runs/{id} — 404 on missing; detail on seeded run.
- POST /api/runs/{id}/pause — writes pause marker; 404 on missing run.
- POST /api/runs/{id}/inject — hotfix inject; 409 on lock; auth required.
- POST /api/runs/{id}/reconcile-graph — plan-edit reconcile; 409 on lock.
- GET /api/runs/{id}/injects — list inject artefacts and ledger events.
- POST /api/runs/{id}/approve and /resume — spawn stub (mocked).
- GET /api/runs/{id}/waves — returns all wave rows.
- GET /api/waves/{run_id}/{node_id} — 404 on missing wave; detail on seeded.
- GET /api/runs/{id}/events?after= — poll paging.
- GET /api/runs/{id}/events/stream — SSE yields seeded events then pauses.
- GET /api/backends — reflects adapter availability.
- GET /PUT /api/config — reads and mutates env vars.
- Auth: 401 without token when TRIPLL_API_TOKEN set; 200 with token.
- POST /api/runs — subprocess stub; 400 on missing profile/path.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tripll.api.app import create_app
from tripll.ledger import (
    append_event,
    insert_run,
    insert_wave,
    open_ledger,
    transition_run,
    transition_wave,
)
from tripll.pipeline import RunsRoot
from tripll.profiles import (
    control_plane_db_path,
    open_profile_store,
    upsert_profile,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _seed_run(
    rr: RunsRoot,
    run_id: str = "r1",
    *,
    terminal: bool = False,
) -> Path:
    """Create a minimal run directory + ledger under processing/.

    Args:
        rr: Active RunsRoot.
        run_id: Run identifier.
        terminal: If True, transition the run to ``done`` state so the SSE
            generator can auto-close after delivering seeded events.
    """
    run_dir = rr.processing_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "ledger.db"
    with open_ledger(ledger_path) as lc:
        insert_run(lc, run_id=run_id, slug="test", source_mode="A", input_path="/tmp/test")
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
            last_action="editing foo.py",
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.02,
        )
        append_event(lc, run_id=run_id, node_id="p:W1", phase="done", cost_usd=0.05)
        if terminal:
            transition_run(lc, run_id, "done")
    return run_dir


_INJECT_PLAN = (
    "# Demo\n\n"
    "## Wave W1 -- impl\n\n"
    "- [ ] **W1.1** Do thing.\n\n"
    "## Files in scope\n\n| Subsystem | Paths |\n|--|--|\n| Core | `src/tripll/` |\n"
)


def _seed_inject_ready_run(rr: RunsRoot, run_id: str = "run-inject") -> Path:
    """Paused run with one done wave and a Mode B plan for inject tests."""
    node_id = "demo:all-waves"
    run_dir = rr.processing_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "pause-requested.md").write_text("# pause\n", encoding="utf-8")
    (run_dir / "demo-wave-plan.md").write_text(_INJECT_PLAN, encoding="utf-8")
    with open_ledger(run_dir / "ledger.db") as lc:
        insert_run(
            lc,
            run_id=run_id,
            slug="test",
            source_mode="B",
            input_path=str(run_dir),
        )
        insert_wave(
            lc,
            node_id=node_id,
            run_id=run_id,
            plan_id="demo",
            wave_id="all-waves",
            lane="demo",
        )
        append_event(lc, run_id=run_id, node_id=node_id, phase="done")
        transition_wave(lc, run_id, node_id, "done")
        transition_run(lc, run_id, "paused")
    return run_dir


@pytest.fixture
def inject_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point TRIPLL_REPO_ROOT at the test temp dir for inject path checks."""
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path))


@pytest.fixture
def tmp_rr(tmp_path: Path) -> RunsRoot:
    """Configured and initialised RunsRoot in a temporary directory."""
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    return rr


@pytest.fixture(autouse=True)
def _fast_sse_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set SSE poll interval to 0.05s for all API tests (avoids 1s sleep in stream tests)."""
    monkeypatch.setenv("TRIPLL_SSE_POLL", "0.05")


@pytest.fixture
def client(tmp_rr: RunsRoot):  # type: ignore[no-untyped-def]
    """TestClient with no auth token configured (dev mode)."""
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def client_authed(tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """TestClient with TRIPLL_API_TOKEN set to 'test-token'."""
    monkeypatch.setenv("TRIPLL_API_TOKEN", "test-token")
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        yield tc


# ---------------------------------------------------------------------------
# 1. Health
# ---------------------------------------------------------------------------


def test_health_returns_200(client) -> None:  # type: ignore[no-untyped-def]
    """GET /health always returns 200 with status ok."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_no_auth_required_even_when_token_set(
    tmp_rr: RunsRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /health returns 200 even when auth token is configured.

    Note: health is not behind require_auth so it's always reachable.
    """
    monkeypatch.setenv("TRIPLL_API_TOKEN", "secret")
    app = create_app(runs_root=tmp_rr.root)
    with TestClient(app) as tc:
        r = tc.get("/health")
        # health is not protected — should still be 200.
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 2. Auth
# ---------------------------------------------------------------------------


def test_auth_401_without_token(client_authed) -> None:  # type: ignore[no-untyped-def]
    """Without a token header, protected endpoints return 401."""
    r = client_authed.get("/api/agents")
    assert r.status_code == 401


def test_auth_401_wrong_token(client_authed) -> None:  # type: ignore[no-untyped-def]
    """With an incorrect token, protected endpoints return 401."""
    r = client_authed.get("/api/agents", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_auth_200_correct_token(client_authed) -> None:  # type: ignore[no-untyped-def]
    """With the correct token, protected endpoints return 200."""
    r = client_authed.get("/api/agents", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200


def test_no_auth_mode_allows_all(client) -> None:  # type: ignore[no-untyped-def]
    """Without TRIPLL_API_TOKEN set, all protected endpoints are allowed."""
    r = client.get("/api/agents")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3. Profiles CRUD
# ---------------------------------------------------------------------------


def test_list_agents_empty(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/agents returns empty list when no profiles exist."""
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get_agent(client) -> None:  # type: ignore[no-untyped-def]
    """POST /api/agents creates a profile; GET /api/agents/{id} retrieves it."""
    body = {
        "name": "My Agent",
        "backend": "claude_code",
        "model": "claude-3-5-sonnet",
        "agent": "wave-plan-executor",
        "skills": ["skill-a"],
        "scope": {"key": "val"},
    }
    r = client.post("/api/agents", json=body)
    assert r.status_code == 201
    created = r.json()
    assert created["name"] == "My Agent"
    assert created["backend"] == "claude_code"
    pid = created["profile_id"]

    r2 = client.get(f"/api/agents/{pid}")
    assert r2.status_code == 200
    assert r2.json()["profile_id"] == pid


def test_create_agent_derives_id_from_name(client) -> None:  # type: ignore[no-untyped-def]
    """Without an explicit profile_id, the id is a slug of the name."""
    r = client.post("/api/agents", json={"name": "My Agent!", "backend": "claude_code"})
    assert r.status_code == 201
    assert r.json()["profile_id"] == "my-agent"


def test_create_agent_honours_explicit_profile_id(client) -> None:  # type: ignore[no-untyped-def]
    """An explicit profile_id is used verbatim (slugified), not derived from name."""
    r = client.post(
        "/api/agents",
        json={"name": "Display Name", "backend": "claude_code", "profile_id": "smoke-prof"},
    )
    assert r.status_code == 201
    assert r.json()["profile_id"] == "smoke-prof"
    assert client.get("/api/agents/smoke-prof").status_code == 200


def test_create_agent_explicit_id_collision_409(client) -> None:  # type: ignore[no-untyped-def]
    """Re-using an explicit profile_id returns 409 rather than silently renaming."""
    base = {"name": "X", "backend": "claude_code", "profile_id": "dup-id"}
    assert client.post("/api/agents", json=base).status_code == 201
    r = client.post("/api/agents", json=base)
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_create_agent_derived_id_collision_suffixes(client) -> None:  # type: ignore[no-untyped-def]
    """Name-derived ids de-duplicate with a numeric suffix instead of erroring."""
    r1 = client.post("/api/agents", json={"name": "Same", "backend": "claude_code"})
    r2 = client.post("/api/agents", json={"name": "Same", "backend": "cursor_local"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["profile_id"] == "same"
    assert r2.json()["profile_id"] == "same-1"


def test_list_agents_after_create(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/agents lists profiles after creation."""
    client.post("/api/agents", json={"name": "A", "backend": "claude_code"})
    client.post("/api/agents", json={"name": "B", "backend": "cursor_local"})
    r = client.get("/api/agents")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "A" in names
    assert "B" in names


def test_patch_agent(client) -> None:  # type: ignore[no-untyped-def]
    """PATCH /api/agents/{id} partially updates a profile."""
    r = client.post("/api/agents", json={"name": "Original", "backend": "claude_code"})
    pid = r.json()["profile_id"]

    r2 = client.patch(f"/api/agents/{pid}", json={"model": "claude-opus-4"})
    assert r2.status_code == 200
    updated = r2.json()
    assert updated["model"] == "claude-opus-4"
    # Other fields unchanged.
    assert updated["name"] == "Original"
    assert updated["backend"] == "claude_code"


def test_patch_agent_404(client) -> None:  # type: ignore[no-untyped-def]
    """PATCH /api/agents/{id} returns 404 for missing profile."""
    r = client.patch("/api/agents/no-such", json={"name": "X"})
    assert r.status_code == 404


def test_delete_agent(client) -> None:  # type: ignore[no-untyped-def]
    """DELETE /api/agents/{id} removes the profile; subsequent GET returns 404."""
    r = client.post("/api/agents", json={"name": "Delete Me", "backend": "claude_code"})
    pid = r.json()["profile_id"]

    r2 = client.delete(f"/api/agents/{pid}")
    assert r2.status_code == 204

    r3 = client.get(f"/api/agents/{pid}")
    assert r3.status_code == 404


def test_get_agent_404(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/agents/{id} returns 404 for missing profile."""
    r = client.get("/api/agents/nonexistent")
    assert r.status_code == 404


def test_profile_reuse_same_id_across_runs(tmp_rr: RunsRoot) -> None:
    """Profile with the same ID can be reused across multiple requests without duplication."""
    db_path = control_plane_db_path(tmp_rr.root)
    with open_profile_store(db_path) as store:
        upsert_profile(store, profile_id="reuse-me", name="R", backend="claude_code")
        upsert_profile(store, profile_id="reuse-me", name="R updated", backend="claude_code")
        from tripll.profiles import list_profiles

        profiles = list_profiles(store)
    assert len(profiles) == 1
    assert profiles[0].name == "R updated"


# ---------------------------------------------------------------------------
# 4. Runs endpoints
# ---------------------------------------------------------------------------


def test_list_runs_empty(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs returns empty list when no runs exist."""
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_runs_with_seeded_run(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs returns seeded runs."""
    _seed_run(tmp_rr, "run-001")
    r = client.get("/api/runs")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["run_id"] == "run-001"


def test_get_run_detail(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id} returns run detail for a seeded run."""
    _seed_run(tmp_rr, "run-detail")
    r = client.get("/api/runs/run-detail")
    assert r.status_code == 200
    data = r.json()
    assert data["run_id"] == "run-detail"
    assert data["state"] == "active"
    assert "is_live" in data


def test_get_run_detail_404(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id} returns 404 for unknown run."""
    r = client.get("/api/runs/no-such-run")
    assert r.status_code == 404


def test_pause_run_writes_marker(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/pause writes pause-requested.md marker."""
    _seed_run(tmp_rr, "run-pause")
    r = client.post("/api/runs/run-pause/pause")
    assert r.status_code == 202
    marker = tmp_rr.run_dir("run-pause") / "pause-requested.md"
    assert marker.exists()
    assert "Pause requested" in marker.read_text()


def test_pause_run_404(client) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/pause returns 404 for unknown run."""
    r = client.post("/api/runs/missing/pause")
    assert r.status_code == 404


def test_inject_api_applies_hotfix(
    client,
    tmp_rr: RunsRoot,
    inject_repo_root: None,
) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/inject applies a dry-run hotfix when run is paused."""
    _seed_inject_ready_run(tmp_rr, "run-inject-api")
    r = client.post(
        "/api/runs/run-inject-api/inject",
        json={
            "brief": "Fix null handling",
            "owned_paths": ["src/a.py"],
            "after": "all-waves",
            "dry_run": True,
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["dry_run"] is True
    assert body["node_id"] == "hotfix:HF-1"
    assert "task_id" in body


def test_inject_api_409_when_lock_held(
    client,
    tmp_rr: RunsRoot,
    inject_repo_root: None,
) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/inject returns 409 when inject.lock is held."""
    run_dir = _seed_inject_ready_run(tmp_rr, "run-inject-lock")
    (run_dir / "inject.lock").write_text("held\n", encoding="utf-8")
    r = client.post(
        "/api/runs/run-inject-lock/inject",
        json={
            "brief": "Fix",
            "owned_paths": ["src/a.py"],
            "after": "all-waves",
            "dry_run": False,
        },
    )
    assert r.status_code == 409
    assert "inject.lock" in r.json()["detail"]


def test_list_injects(
    client,
    tmp_rr: RunsRoot,
    inject_repo_root: None,
) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/injects lists artefacts after a dry-run inject."""
    _seed_inject_ready_run(tmp_rr, "run-inject-list")
    client.post(
        "/api/runs/run-inject-list/inject",
        json={
            "brief": "Fix",
            "owned_paths": ["src/a.py"],
            "after": "all-waves",
            "dry_run": True,
        },
    )
    r = client.get("/api/runs/run-inject-list/injects")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "run-inject-list"
    assert body["lock_held"] is False
    assert isinstance(body["artefacts"], list)
    assert isinstance(body["events"], list)


_RECONCILE_EXTRA_PLAN = """# Extra

## Files in scope

| Subsystem | Paths |
|--|--|
| Extra | `src/extra/` |
"""


def test_reconcile_graph_api_dry_run(
    client,
    tmp_rr: RunsRoot,
    inject_repo_root: None,
) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/reconcile-graph validates plan edits (dry-run)."""
    run_dir = _seed_inject_ready_run(tmp_rr, "run-reconcile-api")
    (run_dir / "extra-wave-plan.md").write_text(_RECONCILE_EXTRA_PLAN, encoding="utf-8")
    r = client.post(
        "/api/runs/run-reconcile-api/reconcile-graph",
        json={"dry_run": True},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["run_id"] == "run-reconcile-api"
    assert body["dry_run"] is True
    assert len(body["inserted"]) == 1
    assert "extra" in body["inserted"][0]


def test_reconcile_graph_api_409_when_lock_held(
    client,
    tmp_rr: RunsRoot,
    inject_repo_root: None,
) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/reconcile-graph returns 409 when inject.lock is held."""
    run_dir = _seed_inject_ready_run(tmp_rr, "run-reconcile-lock")
    (run_dir / "inject.lock").write_text("held\n", encoding="utf-8")
    r = client.post("/api/runs/run-reconcile-lock/reconcile-graph", json={"dry_run": True})
    assert r.status_code == 409
    assert "inject.lock" in r.json()["detail"]


def test_inject_api_requires_auth(
    client_authed,
    tmp_rr: RunsRoot,
    inject_repo_root: None,
) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/inject requires Bearer token when TRIPLL_API_TOKEN is set."""
    _seed_inject_ready_run(tmp_rr, "run-inject-auth")
    payload = {
        "brief": "Fix",
        "owned_paths": ["src/a.py"],
        "after": "all-waves",
        "dry_run": True,
    }
    r = client_authed.post("/api/runs/run-inject-auth/inject", json=payload)
    assert r.status_code == 401
    r = client_authed.post(
        "/api/runs/run-inject-auth/inject",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 202


def test_approve_run_spawns_subprocess(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/approve spawns tripll approve (subprocess mocked)."""
    _seed_run(tmp_rr, "run-approve")
    with patch("tripll.api.app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=12345)
        r = client.post("/api/runs/run-approve/approve")
    assert r.status_code == 202
    mock_popen.assert_called_once()
    argv = mock_popen.call_args[0][0]
    assert "approve" in argv
    assert "run-approve" in argv


def test_resume_run_spawns_subprocess(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/resume spawns tripll resume (subprocess mocked)."""
    _seed_run(tmp_rr, "run-resume")
    with patch("tripll.api.app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=99999)
        r = client.post("/api/runs/run-resume/resume")
    assert r.status_code == 202
    argv = mock_popen.call_args[0][0]
    assert "resume" in argv
    assert "run-resume" in argv


def test_launch_run_400_missing_profile(client, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs returns 400 when profile_id is not found."""
    r = client.post(
        "/api/runs",
        json={"input_path": str(tmp_path), "profile_id": "no-such-profile"},
    )
    assert r.status_code == 400
    assert "Profile not found" in r.json()["detail"]


def test_launch_run_400_missing_input_path(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs returns 400 when input_path does not exist."""
    # Create a valid profile first.
    db_path = control_plane_db_path(tmp_rr.root)
    with open_profile_store(db_path) as store:
        upsert_profile(store, profile_id="valid-p", name="VP", backend="claude_code")

    r = client.post(
        "/api/runs",
        json={"input_path": "/no/such/path", "profile_id": "valid-p"},
    )
    assert r.status_code == 400
    assert "Input path not found" in r.json()["detail"]


def test_launch_run_spawns_subprocess(client, tmp_rr: RunsRoot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs spawns tripll run as a detached subprocess."""
    db_path = control_plane_db_path(tmp_rr.root)
    with open_profile_store(db_path) as store:
        upsert_profile(store, profile_id="go", name="Go", backend="claude_code")

    input_dir = tmp_path / "my-waves"
    input_dir.mkdir()

    with patch("tripll.api.app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=55555)
        r = client.post(
            "/api/runs",
            json={"input_path": str(input_dir), "profile_id": "go"},
        )
    assert r.status_code == 202
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args
    argv = call_args[0][0]
    assert "run" in argv
    assert str(input_dir) in argv
    # Verify start_new_session is set for detached process.
    assert call_args[1].get("start_new_session") is True


# ---------------------------------------------------------------------------
# 5. Waves endpoints
# ---------------------------------------------------------------------------


def test_list_waves_for_run(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/waves returns wave rows."""
    _seed_run(tmp_rr, "run-waves")
    r = client.get("/api/runs/run-waves/waves")
    assert r.status_code == 200
    waves = r.json()
    assert len(waves) == 1
    assert waves[0]["node_id"] == "p:W1"
    assert waves[0]["wave_id"] == "W1"


def test_list_waves_404(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/waves returns 404 for unknown run."""
    r = client.get("/api/runs/no-run/waves")
    assert r.status_code == 404


def test_get_wave_detail(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/waves/{run_id}/{node_id} returns wave detail."""
    _seed_run(tmp_rr, "run-wave-detail")
    r = client.get("/api/waves/run-wave-detail/p:W1")
    assert r.status_code == 200
    wave = r.json()
    assert wave["node_id"] == "p:W1"
    assert wave["run_id"] == "run-wave-detail"
    assert wave["state"] == "queued"


def test_get_wave_detail_404_run(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/waves/{run_id}/{node_id} returns 404 when run not found."""
    r = client.get("/api/waves/no-run/p:W1")
    assert r.status_code == 404


def test_get_wave_detail_404_node(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/waves/{run_id}/{node_id} returns 404 when node not found."""
    _seed_run(tmp_rr, "run-no-node")
    r = client.get("/api/waves/run-no-node/no:such:node")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. Events — poll
# ---------------------------------------------------------------------------


def test_poll_events_returns_all(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/events returns all events for a run."""
    _seed_run(tmp_rr, "run-events")
    r = client.get("/api/runs/run-events/events")
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 2
    assert events[0]["phase"] == "running"
    assert events[1]["phase"] == "done"


def test_poll_events_after_cursor(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/events?after=N returns only events after cursor."""
    _seed_run(tmp_rr, "run-cursor")
    # Get all events to find first event_id.
    events = client.get("/api/runs/run-cursor/events").json()
    first_id = events[0]["event_id"]

    r = client.get(f"/api/runs/run-cursor/events?after={first_id}")
    assert r.status_code == 200
    paged = r.json()
    assert len(paged) == 1
    assert paged[0]["phase"] == "done"


def test_poll_events_404(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/events returns 404 for unknown run."""
    r = client.get("/api/runs/no-run/events")
    assert r.status_code == 404


def test_poll_events_after_all_returns_empty(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/events?after=<last_id> returns empty list."""
    _seed_run(tmp_rr, "run-past-end")
    events = client.get("/api/runs/run-past-end/events").json()
    last_id = events[-1]["event_id"]
    r = client.get(f"/api/runs/run-past-end/events?after={last_id}")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# 7. Events SSE stream
# ---------------------------------------------------------------------------


def test_sse_stream_yields_seeded_events(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """SSE stream for a run yields seeded events (two phase events in order).

    The run is seeded in ``done`` state so the SSE generator closes after
    delivering the two seeded events (terminal-state auto-close path).
    """
    _seed_run(tmp_rr, "run-sse", terminal=True)
    r = client.get("/api/runs/run-sse/events/stream")
    assert r.status_code == 200
    text = r.text
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    assert len(data_lines) >= 2, f"Expected >= 2 data lines, got: {data_lines}"
    import json as _json

    first_event = _json.loads(data_lines[0])
    assert first_event["phase"] == "running"
    assert first_event["node_id"] == "p:W1"
    second_event = _json.loads(data_lines[1])
    assert second_event["phase"] == "done"


def test_sse_stream_404_unknown_run(client) -> None:  # type: ignore[no-untyped-def]
    """SSE stream returns 404 for unknown run."""
    r = client.get("/api/runs/no-run/events/stream")
    assert r.status_code == 404


def test_sse_stream_id_field_present(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """SSE stream sets id: field on each event (enables Last-Event-ID reconnect).

    The run is seeded in ``done`` state so the generator closes naturally.
    """
    _seed_run(tmp_rr, "run-sse-id", terminal=True)
    r = client.get("/api/runs/run-sse-id/events/stream")
    assert r.status_code == 200
    id_lines = [line[3:].strip() for line in r.text.splitlines() if line.startswith("id:")]
    assert len(id_lines) >= 2, f"Expected >= 2 id: lines, got: {id_lines}"
    # id: field must be numeric (event_id).
    for id_val in id_lines:
        assert id_val.isdigit(), f"id: field should be numeric, got {id_val!r}"


# ---------------------------------------------------------------------------
# 8. Backends
# ---------------------------------------------------------------------------


def test_list_backends(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/backends returns all registered backends."""
    r = client.get("/api/backends")
    assert r.status_code == 200
    backends = r.json()
    names = {b["name"] for b in backends}
    assert "claude_code" in names
    assert "cursor_local" in names
    assert "cursor_cloud" in names
    for b in backends:
        assert "available" in b
        assert "detail" in b
        assert "streaming" in b


# ---------------------------------------------------------------------------
# 9. Config
# ---------------------------------------------------------------------------


def test_get_config_defaults(client) -> None:  # type: ignore[no-untyped-def]
    """GET /api/config returns config with default values."""
    r = client.get("/api/config")
    assert r.status_code == 200
    cfg = r.json()
    assert "model_default" in cfg
    assert "cost_budget_usd" in cfg
    assert "max_parallel" in cfg
    assert isinstance(cfg["max_parallel"], int)


def test_put_config_updates_env(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """PUT /api/config updates runtime env vars."""
    monkeypatch.delenv("TRIPLL_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("TRIPLL_COST_BUDGET_USD", raising=False)
    monkeypatch.delenv("TRIPLL_MAX_PARALLEL", raising=False)

    r = client.put(
        "/api/config",
        json={"model_default": "claude-opus-4", "cost_budget_usd": 25.0, "max_parallel": 5},
    )
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["model_default"] == "claude-opus-4"
    assert cfg["cost_budget_usd"] == pytest.approx(25.0)
    assert cfg["max_parallel"] == 5

    # Confirm env vars are actually updated.
    assert os.environ.get("TRIPLL_DEFAULT_MODEL") == "claude-opus-4"
    assert os.environ.get("TRIPLL_MAX_PARALLEL") == "5"


def test_put_config_partial_update(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """PUT /api/config with partial body only updates supplied fields."""
    monkeypatch.setenv("TRIPLL_MAX_PARALLEL", "3")
    r = client.put("/api/config", json={"model_default": "new-model"})
    assert r.status_code == 200
    cfg = r.json()
    # Only model_default changed; max_parallel retains its env value.
    assert cfg["model_default"] == "new-model"
    assert cfg["max_parallel"] == 3


# ---------------------------------------------------------------------------
# 10. Runs-root resolution regression (W6 path-doubling fix)
# ---------------------------------------------------------------------------


def test_create_app_runs_root_anchored_at_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_app() default runs root is anchored at the repo root, not CWD.

    Foreign target repos default to ``<repo_root>/.tripll/runs`` regardless of
    the process CWD.
    """
    from tripll.api.app import _resolve_runs_root as api_resolve
    from tripll.pipeline import default_runs_root
    from tripll.repo_root import resolve_repo_root

    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(fake_repo))
    monkeypatch.delenv("TRIPLL_RUNS", raising=False)

    api_rr = api_resolve(None)
    expected = default_runs_root(resolve_repo_root())
    assert api_rr.root == expected, f"API runs root {api_rr.root!r} != expected {expected!r}"


def test_create_app_runs_root_not_doubled_from_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_app() runs root must stay repo-anchored when CWD is a subdirectory."""
    import os

    from tripll.api.app import _resolve_runs_root as api_resolve
    from tripll.pipeline import default_runs_root

    fake_repo = tmp_path / "repo"
    nested = fake_repo / "packages" / "app"
    nested.mkdir(parents=True)
    (fake_repo / ".git").mkdir()

    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(fake_repo))
    monkeypatch.delenv("TRIPLL_RUNS", raising=False)
    old_cwd = Path.cwd()
    os.chdir(nested)
    try:
        rr = api_resolve(None)
    finally:
        os.chdir(old_cwd)

    expected = default_runs_root(fake_repo)
    assert rr.root == expected, f"Expected {expected!r}, got {rr.root!r}"


# ---------------------------------------------------------------------------
# HITL API
# ---------------------------------------------------------------------------

_HITL_PLAN = """# Plan

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| D1 | **Rich payload model** | **Build structured tree** + Markdown fast path. (Recommended) |
"""

_HITL_GATE = "demo: W0.7 Review gate; operator confirms renderer model before W1."


def _seed_hitl_run(rr: RunsRoot, run_id: str = "run-hitl") -> Path:
    """Seed a run directory with a pending Pre-0 HITL form."""
    from tripll import hitl

    run_dir = _seed_run(rr, run_id)
    (run_dir / "demo-wave-plan.md").write_text(_HITL_PLAN, encoding="utf-8")
    ctx = hitl.RunHitlContext(
        run_id=run_id,
        run_dir=run_dir,
        gates=[_HITL_GATE],
        plan_path=run_dir / "demo-wave-plan.md",
        decisions={"D1": ("Rich payload", "Structured tree + fast path")},
    )
    form = hitl.build_form(ctx)
    hitl.write_form(run_dir, form)
    (run_dir / "pre0-decisions.md").write_text("1. [ ] Pending gate\n", encoding="utf-8")
    return run_dir


def test_get_hitl_returns_form(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """GET /api/runs/{id}/hitl returns form and pending status."""
    _seed_hitl_run(tmp_rr, "run-hitl-get")
    r = client.get("/api/runs/run-hitl-get/hitl")
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True
    assert body["form"] is not None
    assert body["complete"] is False


def test_put_hitl_responses_saves_draft(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """PUT /api/runs/{id}/hitl/responses saves draft answers."""
    run_dir = _seed_hitl_run(tmp_rr, "run-hitl-put")
    from tripll import hitl

    form = hitl.load_form(run_dir)
    assert form is not None
    q = form.questions[0]
    opt = next(o for o in q.options if o.recommended)
    r = client.put(
        "/api/runs/run-hitl-put/hitl/responses",
        json={
            "status": "draft",
            "answers": [{"question_id": q.id, "option_id": opt.id, "notes": "ok"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["saved"] is True
    assert r.json()["complete"] is True


def test_submit_hitl_409_when_incomplete(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/hitl/submit returns 409 when answers are missing."""
    _seed_hitl_run(tmp_rr, "run-hitl-bad")
    r = client.post(
        "/api/runs/run-hitl-bad/hitl/submit",
        json={"status": "submitted", "answers": []},
    )
    assert r.status_code == 409


def test_approve_run_409_when_hitl_incomplete(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST /api/runs/{id}/approve returns 409 when HITL form is incomplete."""
    _seed_hitl_run(tmp_rr, "run-hitl-approve-block")
    r = client.post("/api/runs/run-hitl-approve-block/approve")
    assert r.status_code == 409
    assert "incomplete" in r.json()["detail"].lower()


def test_hitl_submit_and_approve(client, tmp_rr: RunsRoot) -> None:  # type: ignore[no-untyped-def]
    """POST submit + approve writes pre0-approved when responses are complete."""
    run_dir = _seed_hitl_run(tmp_rr, "run-hitl-flow")
    from .hitl_helpers import complete_hitl_responses

    complete_hitl_responses(run_dir, "run-hitl-flow")
    from tripll import hitl

    form = hitl.load_form(run_dir)
    assert form is not None
    responses = hitl.load_responses(run_dir)
    assert responses is not None
    payload = {
        "status": "submitted",
        "answers": [
            {
                "question_id": a.question_id,
                "option_id": a.option_id,
                "checked": a.checked,
                "notes": a.notes,
            }
            for a in responses.answers
        ],
    }
    r = client.post("/api/runs/run-hitl-flow/hitl/submit", json=payload)
    assert r.status_code == 200
    r = client.post("/api/runs/run-hitl-flow/hitl/approve")
    assert r.status_code == 202
    assert (run_dir / "pre0-approved").is_file()
