"""HTML control-plane auth parity — SEC-01, SEC-05, SEC-06, R4, R5, R6 (W1.1, W1.3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tripll.api.app import create_app
from tripll.ledger import insert_run, open_ledger
from tripll.pipeline import RunsRoot
from tripll.profiles import control_plane_db_path, open_profile_store, upsert_profile

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "src" / "tripll" / "api" / "ui" / "templates"

MUTATING_POSTS: list[tuple[str, dict[str, str] | None]] = [
    ("/launch", {"input_path": "ignorelocal/plan.md"}),
    ("/agents/new", {"name": "test", "backend": "claude_code"}),
    ("/agents/edit-id/edit", {"name": "test", "backend": "claude_code"}),
    ("/settings", {"default_backend": "claude_code"}),
]

PAGE_GETS = ["/", "/agents", "/agents/new", "/agents/edit-id/edit", "/settings", "/runs/run-1"]

AUTH_HEADER = {"Authorization": "Bearer test-token-secret"}


def _seed_auth_page_fixtures(rr: RunsRoot) -> None:
    """Seed profile + run paths exercised by ``PAGE_GETS`` auth tests."""
    db_path = control_plane_db_path(rr.root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open_profile_store(db_path) as store:
        upsert_profile(
            store,
            profile_id="edit-id",
            name="Edit Me",
            backend="claude_code",
            model="claude-sonnet-5",
            agent="wave-plan-executor",
        )
    run_dir = rr.processing_dir / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    with open_ledger(run_dir / "ledger.db") as lc:
        insert_run(
            lc,
            run_id="run-1",
            slug="run-1",
            source_mode="A",
            input_path="/tmp/run-1",
        )


@pytest.fixture
def token_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Dashboard with ``TRIPLL_API_TOKEN`` enforced."""
    monkeypatch.setenv("TRIPLL_API_TOKEN", "test-token-secret")
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    _seed_auth_page_fixtures(rr)
    app = create_app(runs_root=rr.root)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def open_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Dashboard with auth disabled (R4 open dev mode)."""
    monkeypatch.delenv("TRIPLL_API_TOKEN", raising=False)
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    app = create_app(runs_root=rr.root)
    with TestClient(app) as tc:
        yield tc


@pytest.mark.tier1
@pytest.mark.parametrize(("path", "payload"), MUTATING_POSTS)
def test_mutating_post_requires_token(
    token_client: TestClient,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    response = token_client.post(path, data=payload or {})
    assert response.status_code in (401, 403)


@pytest.mark.tier1
@pytest.mark.parametrize(("path", "payload"), MUTATING_POSTS)
@pytest.mark.xfail(reason="green after W3: mutating HTML POST auth with bearer", strict=False)
def test_mutating_post_succeeds_with_token(
    token_client: TestClient,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    response = token_client.post(path, data=payload or {}, headers=AUTH_HEADER)
    assert response.status_code not in (401, 403)


@pytest.mark.tier1
@pytest.mark.parametrize("path", PAGE_GETS)
def test_page_shell_requires_token(token_client: TestClient, path: str) -> None:
    response = token_client.get(path)
    assert response.status_code in (401, 403)


@pytest.mark.tier1
@pytest.mark.parametrize("path", PAGE_GETS)
def test_page_shell_succeeds_with_token(token_client: TestClient, path: str) -> None:
    response = token_client.get(path, headers=AUTH_HEADER)
    assert response.status_code == 200


@pytest.mark.tier1
def test_post_with_token_but_no_csrf_rejected(token_client: TestClient) -> None:
    response = token_client.post(
        "/settings",
        data={"default_backend": "claude_code"},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 403


@pytest.mark.tier1
def test_open_mode_without_token(open_client: TestClient) -> None:
    """R4: unset token keeps dev behaviour unchanged."""
    assert os.environ.get("TRIPLL_API_TOKEN", "").strip() == ""
    response = open_client.get("/")
    assert response.status_code == 200


@pytest.mark.tier1
def test_token_transport_no_query_except_eventsource() -> None:
    """R6: ``?token=`` only on EventSource URLs, not htmx GET links."""
    offenders: list[str] = []
    for path in TEMPLATE_ROOT.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if "?token=" not in line and "token=" not in line:
                continue
            if "EventSource" in line or "sseUrl" in line:
                continue
            if "encodeURIComponent(token)" in line:
                continue
            if (
                "?token=" in line
                or 'hx-get="/runs/{{ run_id }}/orchestrator{% if api_token %}?token=' in line
            ):
                rel = f"{path.relative_to(REPO_ROOT)}:{line_no}"
                offenders.append(rel)
    assert offenders == []


@pytest.mark.tier1
def test_base_html_emits_token_via_tojson(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tokens containing ``"`` or ``<`` must produce valid JS (SEC-04)."""
    tricky = 'say-"hello"-<script>'
    monkeypatch.setenv("TRIPLL_API_TOKEN", tricky)
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    app = create_app(runs_root=rr.root)
    with TestClient(app) as client:
        response = client.get("/", headers={"Authorization": f"Bearer {tricky}"})
    assert response.status_code == 200
    assert "Bearer {{ api_token }}" not in response.text
    assert "tojson" in (TEMPLATE_ROOT / "base.html").read_text(encoding="utf-8")
    assert "\\u003cscript\\u003e" in response.text
