"""Tests for W2 cost/retry controls: default model, smarter retries, runaway guard."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from tripll.adapters.base import (
    DispatchResult,
    _count_assistant_event,
    run_streaming,
    runaway_limits_from_env,
)
from tripll.adapters.claude_code import DEFAULT_MODEL, ClaudeCodeAdapter
from tripll.engine import _MAX_NO_PROGRESS_DISPATCHES, Engine
from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.pipeline import RunsRoot
from tripll.worktrees import _git

from ._fakes import (
    AlwaysPassVerifier,
    FakeAdapter,
    FakeWorktreeManager,
)

# ---------------------------------------------------------------------------
# 1. Model defaults
# ---------------------------------------------------------------------------


def test_default_model_constant() -> None:
    """DEFAULT_MODEL is claude-sonnet-5 (P1 / MODEL-01)."""
    assert DEFAULT_MODEL == "claude-sonnet-5"


def test_claude_adapter_uses_default_model_when_no_brief_model() -> None:
    """ClaudeCodeAdapter.build_argv includes DEFAULT_MODEL when no per-wave model."""
    adapter = ClaudeCodeAdapter()
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        brief: dict[str, object] = {
            "wave_id": "W0",
            "plan_worktree_path": str(wt / "plan.md"),
            "branch": "main",
            "worktree_path": str(wt),
            "owned_paths": [],
            "forbidden_paths": [],
            "verify_targets": [],
            "node_id": "test:W0",
            "plan_file": "test.md",
            "prerequisite_waves": [],
            "workspace_scope": [],
            "agent_directives": [],
            "model": "",  # empty / not set
        }
        argv = adapter.build_argv(brief, wt)
    assert "--model" in argv
    idx = argv.index("--model")
    assert argv[idx + 1] == DEFAULT_MODEL, f"Expected {DEFAULT_MODEL!r}, got {argv[idx + 1]!r}"


def test_claude_adapter_per_wave_model_overrides_default() -> None:
    """A non-empty brief['model'] overrides DEFAULT_MODEL."""
    adapter = ClaudeCodeAdapter()
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        brief: dict[str, object] = {
            "wave_id": "W0",
            "plan_worktree_path": str(wt / "plan.md"),
            "branch": "main",
            "worktree_path": str(wt),
            "owned_paths": [],
            "forbidden_paths": [],
            "verify_targets": [],
            "node_id": "test:W0",
            "plan_file": "test.md",
            "prerequisite_waves": [],
            "workspace_scope": [],
            "agent_directives": [],
            "model": "claude-opus-4-5",  # explicit wave-level override
        }
        argv = adapter.build_argv(brief, wt)
    assert "--model" in argv
    idx = argv.index("--model")
    assert argv[idx + 1] == "claude-opus-4-5"


def test_claude_adapter_instance_model_overrides_default_model() -> None:
    """Adapter-level model override takes effect when brief has no model."""
    adapter = ClaudeCodeAdapter(model="claude-opus-4-5")
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        brief: dict[str, object] = {
            "wave_id": "W0",
            "plan_worktree_path": str(wt / "plan.md"),
            "branch": "main",
            "worktree_path": str(wt),
            "owned_paths": [],
            "forbidden_paths": [],
            "verify_targets": [],
            "node_id": "test:W0",
            "plan_file": "test.md",
            "prerequisite_waves": [],
            "workspace_scope": [],
            "agent_directives": [],
        }
        argv = adapter.build_argv(brief, wt)
    idx = argv.index("--model")
    assert argv[idx + 1] == "claude-opus-4-5"


def test_brief_model_beats_adapter_model() -> None:
    """Per-wave brief model wins over adapter-level model."""
    adapter = ClaudeCodeAdapter(model="claude-opus-4-5")
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        brief: dict[str, object] = {
            "wave_id": "W0",
            "plan_worktree_path": str(wt / "plan.md"),
            "branch": "main",
            "worktree_path": str(wt),
            "owned_paths": [],
            "forbidden_paths": [],
            "verify_targets": [],
            "node_id": "test:W0",
            "plan_file": "test.md",
            "prerequisite_waves": [],
            "workspace_scope": [],
            "agent_directives": [],
            "model": "claude-3-5-haiku",
        }
        argv = adapter.build_argv(brief, wt)
    idx = argv.index("--model")
    assert argv[idx + 1] == "claude-3-5-haiku"


# ---------------------------------------------------------------------------
# 2. Smarter retries — no-progress escalation
# ---------------------------------------------------------------------------


def _make_engine(
    tmp_path: Path,
    adapter: FakeAdapter,
    *,
    max_parallel: int = 4,
) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
        max_parallel=max_parallel,
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


def _make_git_engine(
    tmp_path: Path,
    adapter: FakeAdapter,
) -> tuple[Engine, Path]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    from tripll.engine import GitWorktreeManager

    rr = RunsRoot(tmp_path / "runs")
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=repo,
        worktree_manager=GitWorktreeManager(repo, rr),
        verifier=AlwaysPassVerifier(),
    )
    return engine, repo


def _seed_graph(engine: Engine, graph: RunGraph) -> str:
    """Write the graph into the runs root and ledger, return run_id."""
    import json

    rr = engine.runs_root
    rr.init()
    run_id = graph.run_id
    run_dir = rr.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    rr.briefs_dir(run_id).mkdir(parents=True, exist_ok=True)
    rr.logs_dir(run_id).mkdir(parents=True, exist_ok=True)
    rr.graph_path(run_id).write_text(json.dumps(graph.to_dict(), indent=2))

    from tripll.ledger import insert_run, insert_wave, open_ledger

    with open_ledger(rr.ledger_path(run_id)) as lc:
        insert_run(lc, run_id=run_id, slug=run_id, source_mode="A", input_path=str(run_dir))
        for node in graph.nodes.values():
            insert_wave(
                lc,
                node_id=node.node_id,
                run_id=run_id,
                plan_id=node.plan_id,
                wave_id=node.wave_id,
                lane=node.lane,
                initial_state="queued",
            )
    (run_dir / "pre0-approved").write_text("approved\n")
    return run_id


def _single_node_graph(run_id: str, owned_paths: list[str] | None = None) -> RunGraph:
    node = WaveNode(
        "p:W0",
        "p",
        "plan.md",
        "W0",
        "lane-a",
        owned_paths=owned_paths or ["src/a/"],
    )
    lane = Lane("lane-a", plans=["p"], owned_paths=owned_paths or ["src/a/"], waves=[node])
    batch = Batch("A", "batch-a", lanes=["lane-a"])
    return RunGraph(
        run_id=run_id,
        batches=[batch],
        lanes={"lane-a": lane},
        nodes={"p:W0": node},
    )


async def test_no_progress_escalates_after_one_dispatch_on_git_worktree(
    tmp_path: Path,
) -> None:
    """On a git worktree, if the agent writes nothing to owned paths, escalate early.

    The FakeAdapter never writes files → owned paths empty → no-progress fires
    after _MAX_NO_PROGRESS_DISPATCHES (1) dispatch.
    """

    class NoEditAdapter(FakeAdapter):
        """Fails every time AND writes nothing to the worktree."""

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
            # Deliberately write nothing.
            return DispatchResult(
                outcome="failed",
                result_text=(
                    '{"type":"result","result":"scripted failure — no edits","is_error":true}'
                ),
                returncode=1,
                log_path=str(log_path),
                argv=self.build_argv(brief, worktree_path),
            )

    adapter = NoEditAdapter()
    engine, _repo = _make_git_engine(tmp_path, adapter)
    graph = _single_node_graph("run-no-progress", owned_paths=["src/a/"])
    run_id = _seed_graph(engine, graph)

    result = await engine._drive(run_id, graph)

    # Should escalate to failed.
    assert result.state == "failed"
    # Exactly _MAX_NO_PROGRESS_DISPATCHES + 1 would mean the guard triggered
    # after the Nth no-progress attempt; we expect exactly 1 dispatch then
    # an early exit check that fires at the TOP of the next iteration.
    assert adapter.calls == _MAX_NO_PROGRESS_DISPATCHES
    # Evidence should mention no-progress
    blocked = [nr for nr in result.nodes.values() if nr.state == "blocked"]
    assert blocked
    assert any("no-progress" in nr.evidence for nr in blocked)


async def test_no_progress_guard_disabled_for_fake_worktree(tmp_path: Path) -> None:
    """No-progress guard must not trigger for FakeWorktreeManager (non-git dirs)."""
    # FakeAdapter fails twice then succeeds — should still complete.
    adapter = FakeAdapter(fail_times=2)
    engine = _make_engine(tmp_path, adapter)
    graph = _single_node_graph("run-fake-wt-no-guard", owned_paths=["src/a/"])
    run_id = _seed_graph(engine, graph)

    result = await engine._drive(run_id, graph)

    assert result.state == "done"
    assert adapter.calls == 3  # 2 fails + 1 success, guard did not fire early


async def test_progress_resets_no_progress_counter(tmp_path: Path) -> None:
    """An adapter that does write to owned paths on retry should NOT trigger no-progress."""

    class EditOnRetryAdapter(FakeAdapter):
        """Fails once (with edit), succeeds on second call."""

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
            # Always write to an owned path.
            (worktree_path / "src" / "a").mkdir(parents=True, exist_ok=True)
            (worktree_path / "src" / "a" / f"file{self.calls}.py").write_text(
                f"# attempt {self.calls}\n"
            )
            if self.calls < 2:
                return DispatchResult(
                    outcome="failed",
                    result_text=(
                        '{"type":"result","result":"first attempt fails","is_error":true}'
                    ),
                    returncode=1,
                    log_path=str(log_path),
                    argv=self.build_argv(brief, worktree_path),
                )
            return DispatchResult(
                outcome="done",
                result_text="ok",
                returncode=0,
                log_path=str(log_path),
                argv=self.build_argv(brief, worktree_path),
            )

    adapter = EditOnRetryAdapter()
    engine = _make_engine(tmp_path, adapter)
    graph = _single_node_graph("run-progress-resets", owned_paths=["src/a/"])
    run_id = _seed_graph(engine, graph)

    result = await engine._drive(run_id, graph)

    # Should succeed after 2 attempts — no-progress guard must not block.
    assert result.state == "done"
    assert adapter.calls == 2


# ---------------------------------------------------------------------------
# 3. Runaway guard — stream counters
# ---------------------------------------------------------------------------


def test_count_assistant_event_non_assistant() -> None:
    """Non-assistant events return (0, 0)."""
    assert _count_assistant_event('{"type":"system"}') == (0, 0)
    assert _count_assistant_event('{"type":"result"}') == (0, 0)
    assert _count_assistant_event("not json") == (0, 0)
    assert _count_assistant_event("") == (0, 0)


def test_count_assistant_event_with_tool_use() -> None:
    """Tool-use blocks in an assistant event are counted."""
    import json

    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "1", "name": "Read", "input": {}},
                {"type": "tool_use", "id": "2", "name": "Edit", "input": {}},
                {"type": "text", "text": "hello"},
            ],
            "usage": {"output_tokens": 42},
        },
    }
    tok, tools = _count_assistant_event(json.dumps(event))
    assert tok == 42
    assert tools == 2


def test_count_assistant_event_output_tokens() -> None:
    """Output tokens are extracted from usage.output_tokens."""
    import json

    event = {
        "type": "assistant",
        "message": {
            "content": [],
            "usage": {"output_tokens": 100, "input_tokens": 200},
        },
    }
    tok, tools = _count_assistant_event(json.dumps(event))
    assert tok == 100
    assert tools == 0


def test_runaway_limits_from_env_defaults() -> None:
    """Both limits default to 0 (disabled) when env vars are absent."""
    env = os.environ.copy()
    os.environ.pop("TRIPLL_MAX_OUTPUT_TOKENS", None)
    os.environ.pop("TRIPLL_MAX_TOOL_USES", None)
    try:
        assert runaway_limits_from_env() == (0, 0)
    finally:
        os.environ.update(env)


def test_runaway_limits_from_env_reads_values() -> None:
    """Env vars are parsed into (max_tokens, max_tools) ints."""
    os.environ["TRIPLL_MAX_OUTPUT_TOKENS"] = "50000"
    os.environ["TRIPLL_MAX_TOOL_USES"] = "200"
    try:
        assert runaway_limits_from_env() == (50000, 200)
    finally:
        os.environ.pop("TRIPLL_MAX_OUTPUT_TOKENS", None)
        os.environ.pop("TRIPLL_MAX_TOOL_USES", None)


def test_runaway_limits_invalid_values_default_to_zero() -> None:
    """Non-integer env var values are silently converted to 0."""
    os.environ["TRIPLL_MAX_OUTPUT_TOKENS"] = "notanumber"
    os.environ["TRIPLL_MAX_TOOL_USES"] = ""
    try:
        assert runaway_limits_from_env() == (0, 0)
    finally:
        os.environ.pop("TRIPLL_MAX_OUTPUT_TOKENS", None)
        os.environ.pop("TRIPLL_MAX_TOOL_USES", None)


async def test_run_streaming_max_output_tokens_triggers_kill(tmp_path: Path) -> None:
    """run_streaming kills the process when output token ceiling is exceeded.

    We emit a fake assistant JSONL event with 1000 output tokens and set
    max_output_tokens=500 so the guard triggers.
    """
    import json

    # Script: print one assistant event with 1000 output tokens, then loop.
    event = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [],
                "usage": {"output_tokens": 1000},
            },
        }
    )
    # Print the event then stall (sleep) so the guard has to kill it.
    script = (
        f"import sys, time; sys.stdout.write({event!r} + '\\n'); sys.stdout.flush(); time.sleep(60)"
    )
    log_file = tmp_path / "test.log"

    rc, _output, stop_reason = await run_streaming(
        ["python3", "-c", script],
        cwd=tmp_path,
        log_path=log_file,
        timeout_s=10,
        max_output_tokens=500,
        max_tool_uses=0,
    )

    # Process was killed by the guard; rc will be a negative signal code on POSIX.
    assert rc != 0
    assert stop_reason is not None
    assert stop_reason.startswith("runaway guard:")
    assert "output tokens" in stop_reason
    assert "1000" in stop_reason


async def test_run_streaming_max_tool_uses_triggers_kill(tmp_path: Path) -> None:
    """run_streaming kills the process when tool-use count ceiling is exceeded."""
    import json

    # Each assistant event has 2 tool_use blocks; ceiling is 3 → triggers on second event.
    event = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "1", "name": "Read", "input": {}},
                    {"type": "tool_use", "id": "2", "name": "Edit", "input": {}},
                ],
                "usage": {"output_tokens": 10},
            },
        }
    )
    # Print the event 3 times then stall.
    script = (
        f"import sys, time\n"
        f"for _ in range(3):\n"
        f"    sys.stdout.write({event!r} + '\\n'); sys.stdout.flush()\n"
        f"time.sleep(60)\n"
    )
    log_file = tmp_path / "test.log"

    rc, _output, stop_reason = await run_streaming(
        ["python3", "-c", script],
        cwd=tmp_path,
        log_path=log_file,
        timeout_s=10,
        max_output_tokens=0,
        max_tool_uses=3,  # 4th tool-use triggers (3 tools after 1.5 events → fires)
    )

    # Process was killed by the guard; rc will be a negative signal code on POSIX.
    assert rc != 0
    assert stop_reason is not None
    assert stop_reason.startswith("runaway guard:")
    assert "tool-use" in stop_reason


async def test_run_streaming_no_guard_when_limits_zero(tmp_path: Path) -> None:
    """When both limits are 0 (disabled), run_streaming completes normally."""
    import json

    # Emit lots of tokens — should complete without guard firing.
    event = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": "1", "name": "Read", "input": {}}],
                "usage": {"output_tokens": 100000},
            },
        }
    )
    script = f"import sys; sys.stdout.write({event!r} + '\\n')"
    log_file = tmp_path / "test.log"

    rc, _output, stop_reason = await run_streaming(
        ["python3", "-c", script],
        cwd=tmp_path,
        log_path=log_file,
        timeout_s=10,
        max_output_tokens=0,
        max_tool_uses=0,
    )

    assert rc == 0
    assert stop_reason is None


async def test_runaway_guard_result_is_failed_not_quota(tmp_path: Path) -> None:
    """AgentAdapter.dispatch maps a runaway guard kill to outcome='failed', not 'quota_exhausted'."""

    # Fake adapter that simulates a runaway stream response.
    class RunawayStreamAdapter(FakeAdapter):
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
            # Simulate the stop_reason being a runaway guard message.
            return DispatchResult(
                outcome="failed",
                result_text=(
                    '{"type":"result","result":"runaway guard: output tokens 1001 '
                    'exceeded ceiling 1000","is_error":true}'
                ),
                returncode=None,
                log_path=str(log_path),
                argv=self.build_argv(brief, worktree_path),
            )

    adapter = RunawayStreamAdapter()
    engine = _make_engine(tmp_path, adapter)
    graph = _single_node_graph("run-runaway-failed")
    run_id = _seed_graph(engine, graph)

    result = await engine._drive(run_id, graph)

    # Runaway → failed (not quota_paused)
    assert result.state == "failed"
    blocked = [nr for nr in result.nodes.values() if nr.state == "blocked"]
    assert blocked
    # Evidence should contain the runaway reason.
    assert any("runaway" in nr.evidence for nr in blocked)
