"""Run-id path traversal guards — SEC-02 (W1.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tripll.api.app import create_app
from tripll.pipeline import RunsRoot

TRAVERSAL_IDS = [
    "../outside",
    "../../etc/passwd",
    "/absolute/outside",
    "run-id/../../../outside",
    "run\u0000id",
]


@pytest.fixture
def runs_root(tmp_path: Path) -> RunsRoot:
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    safe = rr.processing_dir / "safe-run"
    safe.mkdir(parents=True)
    (safe / "ledger.db").write_bytes(b"")
    return rr


@pytest.mark.tier1
@pytest.mark.parametrize("run_id", TRAVERSAL_IDS)
def test_find_run_dir_rejects_traversal(runs_root: RunsRoot, run_id: str) -> None:
    result = runs_root.find_run_dir(run_id)
    assert result is None


@pytest.mark.tier1
def test_find_run_dir_resolved_path_contained(runs_root: RunsRoot) -> None:
    run_id = "safe-run"
    found = runs_root.find_run_dir(run_id)
    assert found is not None
    resolved = found.resolve()
    for parent in (
        runs_root.processing_dir,
        runs_root.processed_dir,
        runs_root.failed_dir,
    ):
        try:
            resolved.relative_to(parent.resolve())
            return
        except ValueError:
            continue
    pytest.fail(f"resolved run dir escaped runs tree: {resolved}")


@pytest.mark.tier1
def test_find_run_dir_rejects_symlink_escape(runs_root: RunsRoot, tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    link_name = runs_root.processing_dir / "symlink-run"
    link_name.symlink_to(outside, target_is_directory=True)
    found = runs_root.find_run_dir("symlink-run")
    if found is None:
        return
    resolved = found.resolve()
    for parent in (
        runs_root.processing_dir,
        runs_root.processed_dir,
        runs_root.failed_dir,
    ):
        try:
            resolved.relative_to(parent.resolve())
            pytest.fail("symlink escape allowed")
        except ValueError:
            continue


@pytest.mark.tier1
def test_api_run_lookup_rejects_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIPLL_API_TOKEN", raising=False)
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    app = create_app(runs_root=rr.root)
    with TestClient(app) as client:
        response = client.get("/api/runs/..%2F..%2Foutside")
    assert response.status_code in (400, 404, 422)
