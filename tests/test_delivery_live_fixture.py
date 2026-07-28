"""Live fixture-repo E2E walkthrough — Gap 1 manual AC (post #35).

Exercises operator runbook §8 on ``tests/fixtures/delivery/minimal-repo/``:
``run --integrate --deliver`` dry-run, git-backed integrate+deliver after a
completed run, and the full post-deliver CLI chain (stubbed GitHub, TRIPLL_PR_DRY_RUN).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tests._fakes import AlwaysPassVerifier, FakeAdapter
from tests.fixtures.delivery.bootstrap import bootstrap_minimal_repo, copy_delivery_smoke_input
from tests.hitl_helpers import approve_run_with_hitl
from tests.test_delivery_e2e import _load_sample_finding, _mark_finding_fixed, _seed_run
from tests.test_engine import MarkingAdapter
from tripll.cli import app
from tripll.engine import Engine, GitWorktreeManager
from tripll.github.findings import sync_findings_to_store
from tripll.loops.l1_pr import MERGE_APPROVED_MARKER, MERGE_GATE_MARKER, integration_branch_for_run
from tripll.pipeline import RunsRoot

_RUNNER = CliRunner()


def _init_runs_layout(runs: Path) -> None:
    RunsRoot(runs).init()


@pytest.mark.tier2
def test_fixture_repo_run_integrate_deliver_dry_run(tmp_path: Path) -> None:
    """Step 1 (offline): dry-run integrate+deliver against fixture wave plan."""
    repo = bootstrap_minimal_repo(tmp_path / "fixture")
    runs = tmp_path / "runs"
    _init_runs_layout(runs)
    wave_set = copy_delivery_smoke_input(runs / "input" / "delivery-smoke")

    result = _RUNNER.invoke(
        app,
        [
            "run",
            str(wave_set),
            "--integrate",
            "--deliver",
            "--dry-run",
            "--runs-root",
            str(runs),
        ],
        env={"TRIPLL_REPO_ROOT": str(repo)},
    )
    assert result.exit_code == 0, result.output
    assert "[integrate]" in result.output
    assert "[deliver]" in result.output
    assert "idempotency_key=push:" in result.output
    assert "idempotency_key=open_pr:" in result.output
    assert "approve-merge" in result.output


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_fixture_repo_integrate_deliver_after_git_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 1 (local git): completed run → integrate branch → deliver (dry-run push/open)."""
    repo = bootstrap_minimal_repo(tmp_path / "fixture")
    runs = tmp_path / "runs"
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(repo))
    monkeypatch.setenv("TRIPLL_HUMAN_GATES", "auto_accept")
    monkeypatch.chdir(repo)
    # Linear dispatch path — l1_outer verify uses processing/ paths (out of scope here).
    monkeypatch.setattr("tripll.loops.graph_available", lambda: False)

    adapter = MarkingAdapter()
    rr = RunsRoot(runs)
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=repo,
        worktree_manager=GitWorktreeManager(repo, rr),
        verifier=AlwaysPassVerifier(),
    )
    rr.init()
    src = copy_delivery_smoke_input(rr.input_dir / "delivery-smoke")

    started = await engine.start(src)
    if started.pre0_pending:
        approve_run_with_hitl(engine, started.run_id)
        result = await engine.resume(started.run_id)
    else:
        result = started
    assert result.state == "done"

    from tripll.cli import _run_integration

    _run_integration(rr, result.run_id, deliver=True)

    integrate_branch = integration_branch_for_run(result.run_id)
    proc = __import__("subprocess").run(
        ["git", "rev-parse", "--verify", f"refs/heads/{integrate_branch}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.tier3
@pytest.mark.skipif(
    not __import__("tripll.loops", fromlist=["graph_available"]).graph_available(),
    reason="graph extra required",
)
def test_fixture_repo_operator_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runbook section 8 steps 1-6 on fixture TRIPLL_REPO_ROOT (stubbed gh, TRIPLL_PR_DRY_RUN)."""
    repo = bootstrap_minimal_repo(tmp_path / "fixture")
    runs = tmp_path / "runs"
    rr = RunsRoot(runs)
    rr.init()
    run_id = "delivery-fixture"
    run_dir = _seed_run(rr, run_id)
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(repo))

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
        repo_slug: str = "delivery-fixture",
    ) -> int:
        finding = _load_sample_finding(run_id=run_id)
        finding = {
            **finding,
            "file": "src/demo/__init__.py",
            "run_id": run_id,
        }
        return sync_findings_to_store([finding], store, repo=repo_slug, resolve_symbols=False)

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
        # Step 1 (deliver phase): push + open_pr
        deliver = _RUNNER.invoke(
            app,
            ["pr", "shepherd", "--run", run_id, "--phase", "deliver", "--runs-root", str(runs)],
        )
        assert deliver.exit_code == 0
        assert action_log == [f"push:{run_id}", f"open_pr:{run_id}"]

        # Step 2: findings sync
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

        # Step 3: shepherd fix cycle
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

        # Step 4: pr status
        status = _RUNNER.invoke(
            app,
            ["pr", "status", run_id, "--runs-root", str(runs)],
        )
        assert status.exit_code == 0
        assert '"state": "merge_gate_pending"' in status.output

        # Step 5: approve-merge
        approve = _RUNNER.invoke(
            app,
            ["pr", "approve-merge", run_id, "--runs-root", str(runs)],
        )
        assert approve.exit_code == 0
        assert (run_dir / MERGE_GATE_MARKER).is_file()
        assert (run_dir / MERGE_APPROVED_MARKER).is_file()

        # Step 6: merge gated without approval; succeeds when approved (dry-run)
        from tripll.github import pr as github_pr

        with pytest.raises(ValueError, match="human approval"):
            github_pr.run_pr_action(
                "merge",
                idempotency_key=f"merge:{run_id}",
                context={"run_id": run_id, "run_dir": str(run_dir), "pr_number": 42},
            )

        merge_ok = orig_pr_action(
            "merge",
            idempotency_key=f"merge:{run_id}:approved",
            context={
                "run_id": run_id,
                "run_dir": str(run_dir),
                "pr_number": 42,
                "merge_approved": True,
            },
        )
        assert merge_ok["executed"] is True
        assert merge_ok.get("dry_run") is True

        # Deliver replay is idempotent
        deliver_replay = _RUNNER.invoke(
            app,
            ["pr", "shepherd", "--run", run_id, "--phase", "deliver", "--runs-root", str(runs)],
        )
        assert deliver_replay.exit_code == 0
        assert action_log.count(f"push:{run_id}") == 1
        assert action_log.count(f"open_pr:{run_id}") == 1
