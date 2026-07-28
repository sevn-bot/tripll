"""E2E PR delivery path — fixture-repo walkthrough (Gap 1 AC, L2-W1/W2).

Proves the operator chain with stubbed GitHub and fake adapters (no live ``gh``):

``pr shepherd --phase deliver`` → ``findings sync`` → fix cycles →
``pr status`` ``merge_gate_pending`` → ``approve-merge`` → gated merge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tests._fakes import FakeAdapter
from tripll.cli import app
from tripll.github.findings import sync_findings_to_store, triage_finding
from tripll.github.sync import open_store
from tripll.graphstore import SqliteGraphStore
from tripll.loops.l1_pr import MERGE_APPROVED_MARKER, MERGE_GATE_MARKER, pr_status
from tripll.pipeline import RunsRoot

_FIXTURES = Path(__file__).parent / "fixtures" / "delivery"
_RUNNER = CliRunner()


def _seed_run(rr: RunsRoot, run_id: str = "delivery-e2e") -> Path:
    """Create a processing run dir with an empty graph store."""
    run_dir = rr.processing_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    db_path = run_dir / ".tripll" / "graph.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    SqliteGraphStore(str(db_path)).close()
    return run_dir


def _load_sample_finding(*, run_id: str) -> dict[str, Any]:
    raw = json.loads((_FIXTURES / "sample_open_finding.json").read_text(encoding="utf-8"))
    return {**raw, "run_id": run_id}


def _sync_open_finding(run_dir: Path, *, run_id: str) -> None:
    store = open_store(run_dir / ".tripll" / "graph.db")
    try:
        sync_findings_to_store([_load_sample_finding(run_id=run_id)], store, resolve_symbols=False)
    finally:
        store.close()


def _mark_finding_fixed(run_dir: Path, *, finding_id: str) -> None:
    store = open_store(run_dir / ".tripll" / "graph.db")
    try:
        from tripll.github.findings import finding_to_graph_nodes, list_findings_from_store

        rows = list_findings_from_store(store)
        target = next(r for r in rows if r.get("finding_id") == finding_id)
        updated = triage_finding(target, state="fixed")
        node, edges = finding_to_graph_nodes(updated)
        store.upsert_nodes([node])
        if edges:
            store.upsert_edges(edges)
    finally:
        store.close()


@pytest.mark.tier2
def test_poll_reloads_findings_from_store(tmp_path: Path) -> None:
    """After findings are fixed in the store, poll routes to merge gate (not re-fix)."""
    from tripll.loops.l1_pr import shepherd_run

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _sync_open_finding(run_dir, run_id="r1")

    fake = FakeAdapter()
    from tripll.loops import dispatch_bridge as dispatch_bridge_mod

    orig_invoke = dispatch_bridge_mod.invoke_loop_dispatches

    def recording_invoke(
        state: dict[str, object],
        dispatch_meta: list[dict[str, object]],
        *,
        node: str,
        adapter: object | None = None,
    ) -> list[object]:
        return orig_invoke(state, dispatch_meta, node=node, adapter=fake)

    with patch.object(dispatch_bridge_mod, "invoke_loop_dispatches", recording_invoke):
        first = shepherd_run(run_id="r1", run_dir=run_dir, phase="investigate_and_fix")
    assert fake.calls >= 2
    assert first.get("step") == "re_verify"

    _mark_finding_fixed(run_dir, finding_id="finding:ci:ruff-f401")

    second = shepherd_run(run_id="r1", run_dir=run_dir, phase="investigate_and_fix")
    assert second.get("step") == "merge_gate"
    status = pr_status(run_dir=run_dir)
    assert status["state"] == "merge_gate_pending"
    assert status["merge_gate_pending"] is True


@pytest.mark.tier2
def test_merge_gate_pending_on_first_shepherd_when_no_findings(tmp_path: Path) -> None:
    """Empty findings must park at merge gate on a single shepherd invoke."""
    from tripll.loops.l1_pr import shepherd_run

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = shepherd_run(
        run_id="r1",
        run_dir=run_dir,
        phase="investigate_and_fix",
        findings=[],
    )
    assert result.get("step") == "merge_gate"
    status = pr_status(run_dir=run_dir)
    assert status["merge_gate_pending"] is True


@pytest.mark.tier3
@pytest.mark.skipif(
    not __import__("tripll.loops", fromlist=["graph_available"]).graph_available(),
    reason="graph extra required",
)
def test_full_delivery_chain_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk the operator CLI chain: deliver → sync → fix → status → approve-merge."""
    runs = tmp_path / "runs"
    rr = RunsRoot(runs)
    rr.init()
    run_id = "delivery-e2e"
    run_dir = _seed_run(rr, run_id)
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path))

    action_log: list[str] = []
    fake = FakeAdapter()
    from tripll.loops import dispatch_bridge as dispatch_bridge_mod

    orig_invoke = dispatch_bridge_mod.invoke_loop_dispatches

    def _recording_invoke(
        state: dict[str, object],
        dispatch_meta: list[dict[str, object]],
        *,
        node: str,
        adapter: object | None = None,
    ) -> list[object]:
        return orig_invoke(state, dispatch_meta, node=node, adapter=fake)

    def _mock_sync(
        pr_number: int,
        store: Any,
        *,
        run_id: str = "local",
        repo_slug: str = "tripll",
    ) -> int:
        return sync_findings_to_store(
            [_load_sample_finding(run_id=run_id)],
            store,
            repo=repo_slug,
            resolve_symbols=False,
        )

    from tripll.github import pr as github_pr_mod

    orig_pr_action = github_pr_mod.run_pr_action

    def _counting_pr_action(
        action: str,
        *,
        idempotency_key: str,
        context: dict[str, object],
    ) -> dict[str, object]:
        result = orig_pr_action(action, idempotency_key=idempotency_key, context=context)
        if result.get("executed"):
            action_log.append(idempotency_key)
        return result

    with (
        patch.object(dispatch_bridge_mod, "invoke_loop_dispatches", _recording_invoke),
        patch("tripll.github.sync.sync_pr_findings", side_effect=_mock_sync),
        patch.object(github_pr_mod, "run_pr_action", _counting_pr_action),
    ):
        deliver = _RUNNER.invoke(
            app,
            ["pr", "shepherd", "--run", run_id, "--phase", "deliver", "--runs-root", str(runs)],
        )
        assert deliver.exit_code == 0
        assert '"phase": "deliver"' in deliver.output
        assert action_log == ["push:delivery-e2e", "open_pr:delivery-e2e"]

        sync = _RUNNER.invoke(
            app,
            [
                "findings",
                "sync",
                "--pr",
                "42",
                "--run-id",
                run_id,
                "--db",
                str(run_dir / ".tripll" / "graph.db"),
            ],
        )
        assert sync.exit_code == 0
        assert "synced 1 finding" in sync.output

        fix1 = _RUNNER.invoke(
            app,
            [
                "pr",
                "shepherd",
                "--run",
                run_id,
                "--phase",
                "investigate_and_fix",
                "--runs-root",
                str(runs),
            ],
        )
        assert fix1.exit_code == 0
        assert fake.calls >= 2

        _mark_finding_fixed(run_dir, finding_id="finding:ci:ruff-f401")

        fix2 = _RUNNER.invoke(
            app,
            [
                "pr",
                "shepherd",
                "--run",
                run_id,
                "--phase",
                "investigate_and_fix",
                "--runs-root",
                str(runs),
            ],
        )
        assert fix2.exit_code == 0
        assert '"step": "merge_gate"' in fix2.output

        status = _RUNNER.invoke(
            app,
            ["pr", "status", run_id, "--runs-root", str(runs)],
        )
        assert status.exit_code == 0
        assert '"state": "merge_gate_pending"' in status.output

        approve = _RUNNER.invoke(
            app,
            ["pr", "approve-merge", run_id, "--runs-root", str(runs)],
        )
        assert approve.exit_code == 0
        assert (run_dir / MERGE_GATE_MARKER).is_file()
        assert (run_dir / MERGE_APPROVED_MARKER).is_file()
        assert '"state": "merge_approved"' in approve.output

        from tripll.github import pr as github_pr

        with pytest.raises(ValueError, match="human approval"):
            github_pr.run_pr_action(
                "merge",
                idempotency_key="merge:delivery-e2e",
                context={"run_id": run_id, "run_dir": str(run_dir), "pr_number": 42},
            )

        merge_ok = orig_pr_action(
            "merge",
            idempotency_key="merge:delivery-e2e:approved",
            context={
                "run_id": run_id,
                "run_dir": str(run_dir),
                "pr_number": 42,
                "merge_approved": True,
            },
        )
        assert merge_ok["executed"] is True
        assert merge_ok.get("dry_run") is True

        deliver_replay = _RUNNER.invoke(
            app,
            ["pr", "shepherd", "--run", run_id, "--phase", "deliver", "--runs-root", str(runs)],
        )
        assert deliver_replay.exit_code == 0
        assert action_log.count("push:delivery-e2e") == 1
        assert action_log.count("open_pr:delivery-e2e") == 1


def test_merge_rejected_without_approval(tmp_path: Path) -> None:
    """Merge action must refuse without merge_approved in context (D15)."""
    from tripll.github import pr as github_pr

    with pytest.raises(ValueError, match="human approval"):
        github_pr.run_pr_action(
            "merge",
            idempotency_key="merge:no-approval",
            context={"run_id": "r1", "run_dir": str(tmp_path), "pr_number": 1},
        )
