"""Tests for tripll.cli — CLI smoke and contract checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest  # noqa: TC002 — runtime fixture decorators
from typer.testing import CliRunner

from tripll import __version__
from tripll.cli import app

runner = CliRunner()


def _init_runs_layout(runs: Path) -> None:
    """Create runs input/processing/processed/failed dirs without brownfield init."""
    from tripll.pipeline import RunsRoot

    RunsRoot(runs).init()


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(repo))
    runs = tmp_path / "runs"
    result = runner.invoke(app, ["init", "--runs-root", str(runs)])
    assert result.exit_code == 0
    assert "Brownfield init complete" in result.output
    assert (runs / "input").exists()
    assert (repo / "tripll.toml").is_file()
    assert (runs / "processing").exists()
    assert (runs / "processed").exists()
    assert (runs / "failed").exists()


def test_init_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(repo))
    runs = tmp_path / "runs"
    runner.invoke(app, ["init", "--runs-root", str(runs)])
    result = runner.invoke(app, ["init", "--runs-root", str(runs)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_all_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["status", "--runs-root", str(runs)])
        assert result.exit_code == 0
        assert "Runs root" in result.output
        assert "input/" in result.output
        assert "(empty)" in result.output


def test_status_watch_requires_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["status", "--watch", "--runs-root", str(runs)])
        assert result.exit_code == 2
        assert "requires a RUN_ID" in result.output


def test_status_watch_renders_orchestrator_awaiting_review() -> None:
    """status --watch shows AWAITING REVIEW when review gate is active (W3.6)."""
    from unittest.mock import patch

    from tripll.graph import OrchestratorConfig, RunGraph
    from tripll.ledger import insert_run, insert_wave, open_ledger
    from tripll.orchestrator_status import OrchestratorTurn, sync_orchestrator_status

    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        run_dir = runs / "processing" / "r1"
        run_dir.mkdir(parents=True)
        graph = RunGraph(
            run_id="r1",
            orchestrator=OrchestratorConfig(True, "p.md", "feature/x"),
        )
        sync_orchestrator_status(
            run_dir,
            graph,
            turn=OrchestratorTurn(
                "review_gate",
                "**AWAITING REVIEW** (W0.8) — approve before next wave",
            ),
        )
        with open_ledger(run_dir / "ledger.db") as lc:
            insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
            insert_wave(
                lc, node_id="core:W0", run_id="r1", plan_id="core", wave_id="W0", lane="core"
            )

        with patch("time.sleep", side_effect=KeyboardInterrupt):
            result = runner.invoke(app, ["status", "r1", "--watch", "--runs-root", str(runs)])
        assert result.exit_code == 0
        assert "AWAITING REVIEW" in result.output
        assert "── Orchestrator ──" in result.output


def test_status_watch_renders_event_table() -> None:
    from unittest.mock import patch

    from tripll.ledger import append_event, insert_run, insert_wave, open_ledger

    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        run_dir = runs / "processing" / "r1"
        run_dir.mkdir(parents=True)
        with open_ledger(run_dir / "ledger.db") as lc:
            insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
            insert_wave(
                lc, node_id="core:W1", run_id="r1", plan_id="core", wave_id="W1", lane="core"
            )
            append_event(
                lc,
                run_id="r1",
                node_id="core:W1",
                phase="running",
                last_action="editing src/x.py",
                input_tokens=1200,
                output_tokens=300,
                cost_usd=0.08,
            )
            append_event(lc, run_id="r1", node_id="core:W1", phase="done", cost_usd=0.12)

        # time.sleep is patched to break the watch loop after the first frame.
        with patch("time.sleep", side_effect=KeyboardInterrupt):
            result = runner.invoke(app, ["status", "r1", "--watch", "--runs-root", str(runs)])
        assert result.exit_code == 0
        assert "watching r1" in result.output
        assert "core:W1" in result.output
        assert "done" in result.output
        assert "editing src/x.py" in result.output


def test_status_watch_unknown_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["status", "nope", "--watch", "--runs-root", str(runs)])
        assert result.exit_code == 1
        assert "Run not found" in result.output


def test_list_runs_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["list-runs", "--runs-root", str(runs)])
        assert result.exit_code == 0
        assert "Pending input sets" in result.output
        assert "Active runs" in result.output


def test_delete_run_cmd() -> None:
    from tripll.pipeline import RunsRoot

    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        rr = RunsRoot(runs)
        rr.init()
        src = rr.input_dir / "s"
        src.mkdir()
        rid = rr.claim_input(src, run_id="cli-del-20260615-120000")
        result = runner.invoke(
            app,
            ["delete-run", rid, "--yes", "--runs-root", str(runs)],
        )
        assert result.exit_code == 0
        assert "Deleted:" in result.output
        assert rr.find_run_dir(rid) is None


def test_reset_run_restores_input_and_deletes_run() -> None:
    from tripll.pipeline import RunsRoot

    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        rr = RunsRoot(runs)
        rr.init()
        src = rr.input_dir / "my-set"
        src.mkdir()
        plan = src / "my-set-wave-plan.md"
        plan.write_text("# plan\n", encoding="utf-8")
        rid = rr.claim_input(src, run_id="my-set-20260618-120000")
        assert not src.exists()

        result = runner.invoke(
            app,
            ["reset-run", rid, "--runs-root", str(runs)],
        )
        assert result.exit_code == 0
        assert "Restored input set:" in result.output
        assert rr.find_run_dir(rid) is None
        restored = rr.input_dir / "my-set"
        assert restored.is_dir()
        assert (restored / "my-set-wave-plan.md").is_file()


def test_status_run_id_not_found() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["status", "no-such-run", "--runs-root", str(runs)])
        assert result.exit_code == 1


def test_status_seeded_run() -> None:
    """Seed a run directory + ledger directly, then check status shows wave states."""
    from tripll.ledger import insert_run, insert_wave, open_ledger
    from tripll.pipeline import RunsRoot

    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        rr = RunsRoot(runs)
        rr.init()
        run_id = "my-test-set-20260615-000000"
        rr.run_dir(run_id).mkdir(parents=True)
        with open_ledger(rr.ledger_path(run_id)) as lc:
            insert_run(lc, run_id=run_id, slug="my-test-set", source_mode="A", input_path="x")
            insert_wave(lc, node_id="p:W1", run_id=run_id, plan_id="p", wave_id="W1", lane="core")

        result = runner.invoke(app, ["status", run_id, "--runs-root", str(runs)])
        assert result.exit_code == 0
        assert "p:W1" in result.output
        assert "queued" in result.output


# ---------------------------------------------------------------------------
# run --dry-run
# ---------------------------------------------------------------------------


def test_run_dry_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        wave_set = Path(runs) / "input" / "my-set"
        wave_set.mkdir()
        (wave_set / "demo-wave-plan.md").write_text(
            "# Demo\n\n## Files in scope\n\n"
            "| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
        )

        result = runner.invoke(
            app,
            ["run", str(wave_set), "--dry-run", "--runs-root", str(runs)],
        )
        assert result.exit_code == 0
        assert "[dry-run]" in result.output
        assert "my-set" in result.output


def test_run_integrate_dry_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        wave_set = Path(runs) / "input" / "my-set"
        wave_set.mkdir()
        (wave_set / "demo-wave-plan.md").write_text(
            "# Demo\n\n## Files in scope\n\n"
            "| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
        )

        result = runner.invoke(
            app,
            ["run", str(wave_set), "--integrate", "--dry-run", "--runs-root", str(runs)],
        )
        assert result.exit_code == 0
        assert "[integrate]" in result.output
        assert "tripll/integrate/" in result.output


def test_run_integrate_deliver_dry_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        wave_set = Path(runs) / "input" / "my-set"
        wave_set.mkdir()
        (wave_set / "demo-wave-plan.md").write_text(
            "# Demo\n\n## Files in scope\n\n"
            "| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
        )

        result = runner.invoke(
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
        )
        assert result.exit_code == 0
        assert "[integrate]" in result.output
        assert "[deliver]" in result.output
        assert "idempotency_key=push:" in result.output
        assert "idempotency_key=open_pr:" in result.output
        assert "approve-merge" in result.output


def test_run_deliver_requires_integrate() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        wave_set = Path(runs) / "input" / "my-set"
        wave_set.mkdir()
        (wave_set / "demo-wave-plan.md").write_text(
            "# Demo\n\n## Files in scope\n\n"
            "| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
        )

        result = runner.invoke(
            app,
            ["run", str(wave_set), "--deliver", "--dry-run", "--runs-root", str(runs)],
        )
        assert result.exit_code == 1
        assert "--integrate" in result.output


def test_run_no_input_error() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["run", "--runs-root", str(runs)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# plan stub
# ---------------------------------------------------------------------------


def test_plan_prints_run_id_and_batches() -> None:
    with tempfile.TemporaryDirectory() as d:
        wave_set = Path(d) / "my-wave-folder"
        wave_set.mkdir()
        (wave_set / "demo-wave-plan.md").write_text(
            "# Demo\n\n## Files in scope\n\n"
            "| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
        )
        result = runner.invoke(app, ["plan", str(wave_set)])
        assert result.exit_code == 0
        assert "my-wave-folder" in result.output
        assert "Run-id" in result.output
        assert "Batch order" in result.output


def test_plan_missing_path_error() -> None:
    result = runner.invoke(app, ["plan", "/no/such/path"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# resume stub
# ---------------------------------------------------------------------------


def test_resume_missing_ledger_error() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["resume", "no-such-run", "--runs-root", str(runs)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# approve stub
# ---------------------------------------------------------------------------


def test_approve_writes_marker() -> None:
    from tripll.pipeline import RunsRoot

    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        rr = RunsRoot(runs)
        rr.init()
        rr.run_dir("my-run-id").mkdir(parents=True)
        result = runner.invoke(app, ["approve", "my-run-id", "--runs-root", str(runs)])
        assert result.exit_code == 0
        assert "my-run-id" in result.output
        assert (rr.run_dir("my-run-id") / "pre0-approved").exists()


def test_approve_missing_run_error() -> None:
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        _init_runs_layout(runs)
        result = runner.invoke(app, ["approve", "no-such-run", "--runs-root", str(runs)])
        assert result.exit_code == 1
