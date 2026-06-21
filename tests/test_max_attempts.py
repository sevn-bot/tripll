"""Tests for ``max_attempts`` default == 5 and escalation banner.

Covers W1.4 of the test-creator-tests-first wave plan: the global
``max_attempts`` changes from 3 to 5, and the escalation banner reflects the
new value (``self.max_attempts`` instead of hardcoded ``"3"``).

Coverage matrix (W1.6):
  Unit:        Engine.__init__ default, _write_escalation banner text.
  Integration: engine 5-attempt retry loop, brief retry_policy.
  Edge cases:  Custom max_attempts override still works.
  Error:       Escalation file content matches parameterised count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.brief import render_json_brief
from tripll.engine import Engine
from tripll.graph import WaveNode
from tripll.pipeline import RunsRoot

from ._fakes import (
    AlwaysPassVerifier,
    FakeAdapter,
    FakeWorktreeManager,
)
from .hitl_helpers import approve_run_with_hitl

# ---------------------------------------------------------------------------
# W1.4 — Unit: Engine default max_attempts == 5
# ---------------------------------------------------------------------------


class TestEngineMaxAttemptsDefault:
    """Engine.__init__ default max_attempts is 5 (D1, design-note §9.4)."""

    def test_default_max_attempts_is_5(self, tmp_path: Path) -> None:
        rr = RunsRoot(tmp_path / "runs")
        engine = Engine(
            adapter=FakeAdapter(),
            runs_root=rr,
            repo_root=tmp_path,
            worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
            verifier=AlwaysPassVerifier(),
        )
        assert engine.max_attempts == 5


class TestEngineMaxAttemptsOverride:
    """Engine max_attempts can be overridden via constructor (already works)."""

    def test_custom_max_attempts_override(self, tmp_path: Path) -> None:
        """Explicit max_attempts override still works."""
        rr = RunsRoot(tmp_path / "runs")
        engine = Engine(
            adapter=FakeAdapter(),
            runs_root=rr,
            repo_root=tmp_path,
            worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
            verifier=AlwaysPassVerifier(),
            max_attempts=7,
        )
        assert engine.max_attempts == 7


# ---------------------------------------------------------------------------
# W1.4 — Unit: escalation banner uses self.max_attempts
# ---------------------------------------------------------------------------


class TestEscalationBannerParameterised:
    """_write_escalation banner reflects the configured max_attempts value."""

    def _make_engine(self, tmp_path: Path, max_attempts: int = 5) -> Engine:
        rr = RunsRoot(tmp_path / "runs")
        rr.init()
        return Engine(
            adapter=FakeAdapter(),
            runs_root=rr,
            repo_root=tmp_path,
            worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
            verifier=AlwaysPassVerifier(),
            max_attempts=max_attempts,
        )

    def test_banner_says_5_attempts(self, tmp_path: Path) -> None:
        """Default escalation banner mentions 5 attempts, not 3."""
        from tripll.engine import NodeResult

        engine = self._make_engine(tmp_path, max_attempts=5)
        run_id = "test-run"
        (engine.runs_root.run_dir(run_id)).mkdir(parents=True, exist_ok=True)
        results = {
            "p:W1": NodeResult("p:W1", "blocked", 5, "test failure"),
        }
        engine._write_escalation(run_id, ["p:W1"], results)
        content = (engine.runs_root.run_dir(run_id) / "escalation.md").read_text()
        assert "5 attempts exhausted" in content
        assert "3 attempts exhausted" not in content

    @pytest.mark.parametrize("attempts", [5, 7, 10])
    def test_banner_reflects_custom_attempts(self, tmp_path: Path, attempts: int) -> None:
        """Banner uses self.max_attempts regardless of the value (must not say '3')."""
        from tripll.engine import NodeResult

        engine = self._make_engine(tmp_path, max_attempts=attempts)
        run_id = f"test-run-{attempts}"
        (engine.runs_root.run_dir(run_id)).mkdir(parents=True, exist_ok=True)
        results = {
            "p:W1": NodeResult("p:W1", "blocked", attempts, "test failure"),
        }
        engine._write_escalation(run_id, ["p:W1"], results)
        content = (engine.runs_root.run_dir(run_id) / "escalation.md").read_text()
        assert f"{attempts} attempts exhausted" in content
        # Must not contain the old hardcoded '3 attempts exhausted'
        assert "3 attempts exhausted" not in content


# ---------------------------------------------------------------------------
# W1.4 — Integration: brief retry_policy reflects max_attempts=5
# ---------------------------------------------------------------------------


class TestBriefRetryPolicy:
    """render_json_brief retry_policy reflects the new default of 5."""

    def test_retry_policy_max_attempts_5(self) -> None:
        node = WaveNode(
            "demo:W1",
            "demo",
            "x.md",
            "W1",
            "demo",
            owned_paths=["src/demo/"],
        )
        brief = render_json_brief(node, run_id="r", branch="b", worktree_path="w")
        assert brief["retry_policy"] == {"max_attempts": 5, "on_5th_failure": "escalate"}

    def test_retry_policy_escalation_key_is_5th_not_3rd(self) -> None:
        """The escalation key should say 'on_5th_failure', not 'on_3rd_failure'."""
        node = WaveNode(
            "demo:W1",
            "demo",
            "x.md",
            "W1",
            "demo",
            owned_paths=["src/demo/"],
        )
        brief = render_json_brief(node, run_id="r", branch="b", worktree_path="w")
        policy = brief["retry_policy"]
        assert isinstance(policy, dict)
        assert "on_5th_failure" in policy
        assert "on_3rd_failure" not in policy


# ---------------------------------------------------------------------------
# W1.4 — Integration: engine runs 5 attempts before escalating
# ---------------------------------------------------------------------------


_MODE_B_PLAN = (
    "# Demo\n\n"
    "## Wave W0 — review gate\n\n"
    "- [ ] **W0.1** Review gate: confirm demo scope.\n\n"
    "## Files in scope\n\n| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
)


def _make_engine(tmp_path: Path, adapter: FakeAdapter, *, fail_verify: bool = False) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    verifier = AlwaysPassVerifier()
    if fail_verify:
        from ._fakes import AlwaysFailVerifier

        verifier = AlwaysFailVerifier()  # type: ignore[assignment]
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=verifier,
    )


def _seed_mode_b(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "demo-plan"
    src.mkdir(parents=True, exist_ok=True)
    (src / "demo-wave-plan.md").write_text(_MODE_B_PLAN)
    return src


class TestEngineRetryLoop5Attempts:
    """Engine retries up to 5 attempts (not 3) before escalating."""

    @pytest.mark.asyncio
    async def test_five_failures_then_escalate(self, tmp_path: Path) -> None:
        adapter = FakeAdapter(fail_times=99)
        engine = _make_engine(tmp_path, adapter)
        src = _seed_mode_b(engine.runs_root)
        started = await engine.start(src)
        approve_run_with_hitl(engine, started.run_id)
        result = await engine.resume(started.run_id)
        assert result.state == "failed"
        blocked = [nr for nr in result.nodes.values() if nr.state == "blocked"]
        assert blocked
        # Should be 5 attempts, not 3
        assert all(nr.attempts == 5 for nr in blocked)

    @pytest.mark.asyncio
    async def test_escalation_file_written_with_5(self, tmp_path: Path) -> None:
        adapter = FakeAdapter(fail_times=99)
        engine = _make_engine(tmp_path, adapter)
        src = _seed_mode_b(engine.runs_root)
        started = await engine.start(src)
        approve_run_with_hitl(engine, started.run_id)
        result = await engine.resume(started.run_id)
        esc_path = engine.runs_root.failed_dir / result.run_id / "escalation.md"
        assert esc_path.exists()
        content = esc_path.read_text()
        assert "5 attempts exhausted" in content
