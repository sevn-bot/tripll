"""Tests for tripll.engine — scheduling helpers + end-to-end run policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.adapters.base import DispatchResult
from tripll.engine import Engine, GitWorktreeManager, can_run_concurrently, ready_nodes
from tripll.graph import WaveNode
from tripll.pipeline import RunsRoot
from tripll.worktrees import _git

from ._dev_eval import DEV_EVAL, copy_dev_eval_input
from ._fakes import (
    AlwaysFailVerifier,
    AlwaysPassVerifier,
    FakeAdapter,
    FakeWorktreeManager,
)
from .hitl_helpers import approve_run_with_hitl

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_EVAL = DEV_EVAL

_MODE_B_PLAN = (
    "# Demo\n\n"
    "## Wave W0 — review gate\n\n"
    "- [ ] **W0.1** Review gate: confirm demo scope.\n\n"
    "## Files in scope\n\n| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
)


# ---------------------------------------------------------------------------
# pure scheduling helpers
# ---------------------------------------------------------------------------


def test_ready_nodes_respects_deps() -> None:
    a = WaveNode("a", "a", "p", "W0", "a")
    b = WaveNode("b", "b", "p", "W1", "b", depends_on=["a"])
    assert [n.node_id for n in ready_nodes([a, b], set())] == ["a"]
    assert {n.node_id for n in ready_nodes([a, b], {"a"})} == {"b"}


def test_can_run_concurrently_disjoint() -> None:
    a = WaveNode("a", "a", "p", "W0", "a", owned_paths=["src/sevn/a/"])
    b = WaveNode("b", "b", "p", "W0", "b", owned_paths=["src/sevn/b/"])
    assert can_run_concurrently(a, b) is True


def test_can_run_concurrently_overlap_false() -> None:
    a = WaveNode("a", "a", "p", "W0", "a", owned_paths=["src/sevn/x/"])
    b = WaveNode("b", "b", "p", "W0", "b", owned_paths=["src/sevn/x/y.py"])
    assert can_run_concurrently(a, b) is False


def test_can_run_concurrently_both_late_cw_false(legacy_cw_hotspots: None) -> None:
    a = WaveNode("a", "a", "p", "W0", "a", owned_paths=["src/sevn/ui/dashboard/app.js"])
    b = WaveNode("b", "b", "p", "W0", "b", owned_paths=["infra/sevn.schema.json"])
    assert can_run_concurrently(a, b) is False


# ---------------------------------------------------------------------------
# engine fixtures
# ---------------------------------------------------------------------------


def _make_engine(tmp_path: Path, adapter: FakeAdapter, *, fail_verify: bool = False) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    verifier = AlwaysFailVerifier() if fail_verify else AlwaysPassVerifier()
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=verifier,
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# temp\n")
    _git(root, "add", "README.md")
    _git(
        root,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=test",
        "commit",
        "-q",
        "-m",
        "init",
    )


class MarkingAdapter(FakeAdapter):
    """Fake adapter that appends an attempt marker file in the worktree on each dispatch.

    W2 update: writes the marker under the first owned path listed in the brief so
    the no-progress guard (W2) detects real edits and does not trigger early escalation.
    Falls back to ``src/marker.txt`` when the brief lists no owned paths.
    """

    async def dispatch(
        self,
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: object = None,
    ) -> DispatchResult:
        self.calls += 1
        self.dispatched.append(str(brief.get("node_id", "?")))
        # Write under the first owned path so the W2 no-progress guard sees edits.
        owned_paths = brief.get("owned_paths")
        if owned_paths and isinstance(owned_paths, list) and owned_paths:
            marker_dir = worktree_path / str(owned_paths[0]).rstrip("/")
        else:
            marker_dir = worktree_path / "src"
        marker = marker_dir / "marker.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"{marker.read_text()}attempt{self.calls}\n"
            if marker.exists()
            else f"attempt{self.calls}\n"
        )
        argv = self.build_argv(brief, worktree_path)
        if self.calls <= self.fail_times:
            return DispatchResult(
                outcome="failed",
                result_text=(
                    f'{{"type":"result","result":"scripted failure {self.calls}","is_error":true}}'
                ),
                returncode=1,
                log_path=str(log_path),
                argv=argv,
            )
        return DispatchResult(
            outcome=self.final_outcome,
            result_text="ok",
            returncode=0,
            log_path=str(log_path),
            argv=argv,
        )


def _make_git_engine(
    tmp_path: Path,
    adapter: FakeAdapter,
    *,
    fail_verify: bool = False,
) -> tuple[Engine, Path]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    rr = RunsRoot(tmp_path / "runs")
    verifier = AlwaysFailVerifier() if fail_verify else AlwaysPassVerifier()
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=repo,
        worktree_manager=GitWorktreeManager(repo, rr),
        verifier=verifier,
    )
    return engine, repo


def _seed_mode_b(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "demo"
    src.mkdir(parents=True)
    (src / "demo-wave-plan.md").write_text(_MODE_B_PLAN)
    return src


# ---------------------------------------------------------------------------
# Pre-0 gate
# ---------------------------------------------------------------------------


async def test_start_stops_at_pre0(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path, FakeAdapter())
    src = _seed_mode_b(engine.runs_root)
    result = await engine.start(src)
    assert result.state == "paused"
    assert result.pre0_pending is True
    assert (engine.runs_root.run_dir(result.run_id) / "pre0-decisions.md").exists()
    assert (engine.runs_root.run_dir(result.run_id) / "hitl-form.json").exists()
    # Nothing dispatched before approval.
    assert engine.adapter.calls == 0


async def test_approve_then_resume_completes(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "done"
    assert (engine.runs_root.processed_dir / result.run_id).exists()
    assert not engine.runs_root.run_dir(result.run_id).exists()
    assert adapter.calls >= 1


async def test_resume_resets_interrupted_waves(tmp_path: Path) -> None:
    from tripll.ledger import list_waves, open_ledger, transition_wave

    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        node_id = list_waves(lc, rid)[0].node_id
        transition_wave(lc, rid, node_id, "running")

    adapter.calls = 0
    result = await engine.resume(rid)
    assert result.state == "done"
    assert adapter.calls >= 1


# ---------------------------------------------------------------------------
# Retry / escalate
# ---------------------------------------------------------------------------


async def test_quota_exhausted_pauses_run(tmp_path: Path) -> None:
    adapter = FakeAdapter(final_outcome="quota_exhausted")
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "paused"
    assert result.quota_pending is True
    assert adapter.calls == 1
    assert (engine.runs_root.run_dir(started.run_id) / "quota-paused.md").exists()
    assert started.run_id in engine.runs_root.list_processing()


async def test_fifth_failure_escalates_to_failed(tmp_path: Path) -> None:
    adapter = FakeAdapter(fail_times=99)  # always fails
    engine = _make_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "failed"
    assert (engine.runs_root.failed_dir / result.run_id).exists()
    assert (engine.runs_root.failed_dir / result.run_id / "escalation.md").exists()
    # Exactly 5 attempts per node (tests-first model: 4 retries then escalate).
    blocked = [nr for nr in result.nodes.values() if nr.state == "blocked"]
    assert blocked
    assert all(nr.attempts == 5 for nr in blocked)


async def test_verify_failure_escalates(tmp_path: Path) -> None:
    adapter = FakeAdapter()  # adapter says done, but verify fails
    engine = _make_engine(tmp_path, adapter, fail_verify=True)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "failed"


async def test_retry_preserves_checkpointed_work(tmp_path: Path) -> None:
    adapter = MarkingAdapter(fail_times=2)
    engine, repo = _make_git_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "done"

    branch = f"wave/{result.run_id}/demo-w0-final"
    # W2 update: MarkingAdapter now writes under the first owned path (src/sevn/demo/).
    marker = _git(repo, "show", f"{branch}:src/sevn/demo/marker.txt")
    assert marker.returncode == 0
    assert marker.stdout == "attempt1\nattempt2\nattempt3\n"

    log = _git(repo, "log", "--oneline", branch)
    assert log.returncode == 0
    assert log.stdout.count("tripll:") >= 3


async def test_blocked_run_keeps_worktree_and_commits(tmp_path: Path) -> None:
    adapter = MarkingAdapter(fail_times=99)
    engine, repo = _make_git_engine(tmp_path, adapter)
    src = _seed_mode_b(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "failed"

    run_dir = engine.runs_root.failed_dir / result.run_id
    wt_dirs = list((run_dir / "worktrees").glob("*"))
    assert len(wt_dirs) == 1
    # W2 update: MarkingAdapter now writes under the first owned path (src/sevn/demo/).
    # Tests-first model: 5 attempts before escalation, so 5 marker lines.
    assert (wt_dirs[0] / "src" / "sevn" / "demo" / "marker.txt").read_text() == (
        "attempt1\nattempt2\nattempt3\nattempt4\nattempt5\n"
    )

    branch = f"wave/{result.run_id}/demo-w0-final"
    log = _git(repo, "log", "--oneline", branch)
    assert log.returncode == 0
    assert log.stdout.count("tripll:") >= 3


# ---------------------------------------------------------------------------
# dev_eval end-to-end
# ---------------------------------------------------------------------------


async def test_dev_eval_e2e_pre0_then_processed(tmp_path: Path) -> None:
    if not (_DEV_EVAL / "parallel-wave.md").exists():
        pytest.skip("dev_eval set not present")
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    engine.runs_root.init()
    dest = copy_dev_eval_input(engine.runs_root, with_orchestrator=False)

    started = await engine.start(dest)
    assert started.state == "paused"

    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "done"
    assert (engine.runs_root.processed_dir / result.run_id).exists()
    # All 16 lanes reached done.
    assert len(result.nodes) == 16
    assert all(nr.state == "done" for nr in result.nodes.values())


async def test_resume_after_crash_skips_completed(tmp_path: Path) -> None:
    """Simulate a mid-flight crash: pre-mark some waves done, resume the rest."""
    from tripll.ledger import list_waves, open_ledger, transition_wave

    if not (_DEV_EVAL / "parallel-wave.md").exists():
        pytest.skip("dev_eval set not present")
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    engine.runs_root.init()
    dest = copy_dev_eval_input(engine.runs_root, with_orchestrator=False)

    started = await engine.start(dest)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id

    # Simulate the waves that completed before the crash.
    with open_ledger(engine.runs_root.ledger_path(rid)) as lc:
        waves = list_waves(lc, rid)
        precompleted = [w.node_id for w in waves[: len(waves) // 2]]
        for node_id in precompleted:
            transition_wave(lc, rid, node_id, "done")

    result = await engine.resume(rid)
    assert result.state == "done"
    # Only the not-yet-done waves were dispatched on resume.
    assert adapter.calls == len(waves) - len(precompleted)
    report = (engine.runs_root.processed_dir / rid / "report.md").read_text()
    assert "Deferred / manual prerequisites" in report


def test_make_verifier_toolchain_env(tmp_path: Path) -> None:
    from tripll.engine import MakeVerifier

    repo = tmp_path / "repo"
    repo.mkdir()
    verifier = MakeVerifier(repo_root=repo)
    env = verifier._toolchain_env()
    assert env["UV_PROJECT"] == str(repo.resolve())
    assert "VIRTUAL_ENV" not in env


def test_make_verifier_typecheck_scoped_on_real_worktree() -> None:
    from tripll.engine import MakeVerifier

    wt = (
        _REPO_ROOT
        / "wave-orchestrator/runs/failed/test1-telegram-rich-20260615-183315"
        / "worktrees/telegram-rich-inline-miniapps-w0"
    )
    if not wt.is_dir():
        pytest.skip("telegram W0 worktree not present")
    verifier = MakeVerifier(repo_root=_REPO_ROOT)
    ok, msg = verifier.verify(wt, ["make lint", "make typecheck"])
    assert ok, msg
