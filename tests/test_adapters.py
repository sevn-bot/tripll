"""Tests for tripll.adapters — argv builders, capability gates, fake adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.adapters import BACKENDS, get_adapter
from tripll.adapters.base import DispatchResult, run_streaming
from tripll.adapters.claude_code import (
    ClaudeCodeAdapter,
    collect_add_dirs,
    resolve_add_dir,
)
from tripll.adapters.cursor_cloud import CursorCloudAdapter
from tripll.adapters.cursor_local import CursorLocalAdapter
from tripll.adapters.stream_summary import summarize_stream_line
from tripll.cli import app

from ._fakes import FakeAdapter

runner = CliRunner()


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_has_three_backends() -> None:
    assert set(BACKENDS) == {"claude_code", "cursor_local", "cursor_cloud"}


def test_get_adapter_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_adapter("nope")


# ---------------------------------------------------------------------------
# claude_code
# ---------------------------------------------------------------------------


def test_claude_argv_exact(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    (wt / "plan" / "tripll").mkdir(parents=True)
    brief = {
        "node_id": "telemetry:W1",
        "wave_id": "W1",
        "plan_worktree_path": "/wt/plan/tripll/x-wave-plan.md",
        "branch": "wave/r/telemetry-w1",
        "worktree_path": "/wt",
        "owned_paths": ["src/a.py"],
        "forbidden_paths": ["src/b.py"],
        "verify_targets": ["make ci-affected"],
        "prerequisite_waves": [],
        "workspace_scope": ["plan/tripll"],
        "agent_directives": ["Do not commit."],
    }
    argv = ClaudeCodeAdapter().build_argv(brief, wt)
    assert argv[:7] == [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--agent",
        "wave-plan-executor",
        "--verbose",
    ]
    assert argv[7:9] == ["--add-dir", str(wt / "plan" / "tripll")]
    assert "--permission-mode" in argv
    assert "acceptEdits" in argv
    model_idx = argv.index("--model")
    assert argv[model_idx + 1] == "claude-sonnet-5"
    assert "Execute wave W1" in argv[-1]
    assert "Agent directives:" in argv[-1]


def test_claude_add_dir_maps_files_to_parent_directories(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    channels = wt / "src" / "sevn" / "channels"
    channels.mkdir(parents=True)
    (channels / "telegram.py").write_text("# stub\n")
    (wt / "docs" / "readmes").mkdir(parents=True)
    (wt / "docs" / "readmes" / "channels.md").write_text("# doc\n")
    (wt / "Makefile").write_text("ci:\n")

    assert resolve_add_dir(wt, "src/sevn/channels/telegram.py") == channels
    assert resolve_add_dir(wt, "docs/readmes/channels.md") == wt / "docs" / "readmes"
    assert resolve_add_dir(wt, "Makefile") == wt
    assert resolve_add_dir(wt, "tests/channels/test_telegram_rich*.py") == wt / "tests" / "channels"

    dirs = collect_add_dirs(
        wt,
        [
            "src/sevn/channels/telegram.py",
            "docs/readmes/channels.md",
            "Makefile",
            "plan/tripll",
        ],
    )
    assert wt in dirs
    assert channels in dirs
    assert wt / "docs" / "readmes" in dirs

    brief = {
        "wave_id": "R1",
        "workspace_scope": [
            "src/sevn/channels/telegram.py",
            "docs/readmes/channels.md",
            "Makefile",
        ],
    }
    argv = ClaudeCodeAdapter().build_argv(brief, wt)
    add_dirs = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--add-dir"]
    assert str(channels.resolve()) in add_dirs
    assert str((wt / "docs" / "readmes").resolve()) in add_dirs
    assert str(wt.resolve()) in add_dirs
    assert not any(p.endswith("telegram.py") for p in add_dirs)
    assert not any(p.endswith("channels.md") for p in add_dirs)


def test_claude_argv_verbose_always_present(tmp_path: Path) -> None:
    """D4: --verbose is always emitted with stream-json, even when verbose=False."""
    argv_default = ClaudeCodeAdapter().build_argv({"wave_id": "W1"}, tmp_path)
    argv_explicit = ClaudeCodeAdapter(verbose=True).build_argv({"wave_id": "W1"}, tmp_path)
    assert "--verbose" in argv_default
    assert "--verbose" in argv_explicit


def test_claude_argv_default_model() -> None:
    """D5: default build_argv uses claude-sonnet-5 when no override is set."""
    argv = ClaudeCodeAdapter().build_argv({"wave_id": "W1"}, Path("/wt"))
    model_idx = argv.index("--model")
    assert argv[model_idx + 1] == "claude-sonnet-5"


def test_claude_argv_with_model() -> None:
    argv = ClaudeCodeAdapter(model="claude-sonnet-4-6").build_argv({"wave_id": "W1"}, Path("/wt"))
    assert "--model" in argv
    assert "claude-sonnet-4-6" in argv


def test_claude_argv_per_wave_model_overrides_default() -> None:
    """Per-wave brief model wins over DEFAULT_MODEL (D5)."""
    brief = {"wave_id": "W1", "model": "claude-opus-4-5"}
    argv = ClaudeCodeAdapter().build_argv(brief, Path("/wt"))
    model_idx = argv.index("--model")
    assert argv[model_idx + 1] == "claude-opus-4-5"


def test_claude_argv_skip_permissions() -> None:
    argv = ClaudeCodeAdapter(skip_permissions=True).build_argv({}, Path("/wt"))
    assert "--dangerously-skip-permissions" in argv
    assert "--permission-mode" not in argv


def test_claude_parse_result_done() -> None:
    out = (
        '{"type":"result","result":"all good","is_error":false,'
        '"cost_usd":0.42,"usage":{"input_tokens":10,"output_tokens":5}}\n'
    )
    r = ClaudeCodeAdapter().parse_result(0, out)
    assert r.outcome == "done"
    assert r.result_text == "all good"
    assert r.cost_usd == 0.42
    assert r.input_tokens == 10
    assert r.output_tokens == 5


def test_claude_parse_result_failed_on_error_flag() -> None:
    out = '{"type":"result","result":"boom","is_error":true}\n'
    r = ClaudeCodeAdapter().parse_result(0, out)
    assert r.outcome == "failed"


def test_claude_parse_result_timeout() -> None:
    assert ClaudeCodeAdapter().parse_result(None, "x").outcome == "timed_out"


# ---------------------------------------------------------------------------
# cursor_local capability gate
# ---------------------------------------------------------------------------


def test_cursor_local_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tripll.adapters.cursor_local.shutil.which", lambda _: None)
    caps = CursorLocalAdapter().capabilities()
    assert caps.available is False
    assert "not installed" in caps.detail


def test_cursor_local_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tripll.adapters.cursor_local.resolve_cursor_cli", lambda: "agent")
    assert CursorLocalAdapter().capabilities().available is True


def test_cursor_local_argv() -> None:
    brief = {
        "wave_id": "W1",
        "plan_worktree_path": "/wt/plan/tripll/x-wave-plan.md",
        "branch": "b",
        "worktree_path": "/wt",
        "owned_paths": [],
        "forbidden_paths": [],
        "verify_targets": [],
        "prerequisite_waves": [],
    }
    argv = CursorLocalAdapter(model="auto").build_argv(brief, Path("/wt"))
    assert argv[0] in {"agent", "cursor-agent"}
    assert "--print" in argv
    assert "--verbose" in argv
    assert "--workspace" in argv
    assert "--add-dir" not in argv
    assert "--agent" not in argv
    assert "--model" in argv
    assert "auto" in argv
    assert "Execute wave W1" in argv[-1]


def test_cursor_local_argv_with_agent_wave_runner(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    (wt / "plan" / "tripll").mkdir(parents=True)
    brief = {
        "wave_id": "W1",
        "plan_worktree_path": str(wt / "plan" / "tripll" / "x-wave-plan.md"),
        "branch": "feature/x",
        "worktree_path": str(wt),
        "owned_paths": ["plan/tripll"],
        "forbidden_paths": [],
        "verify_targets": [],
        "prerequisite_waves": [],
        "workspace_scope": ["plan/tripll"],
        "agent": "wave-runner",
    }
    argv = CursorLocalAdapter(agent="wave-plan-executor").build_argv(brief, wt)
    assert "--add-dir" not in argv
    assert "--agent" not in argv
    ws_idx = argv.index("--workspace")
    assert argv[ws_idx + 1] == str(wt.resolve())
    assert "wave-runner" in argv[-1]
    assert "Use the wave-runner subagent workflow." in argv[-1]


def test_build_adapter_orchestrator_wave_runner_and_model_policy() -> None:
    from tripll.adapters import build_adapter
    from tripll.adapters.options import BackendOptions
    from tripll.graph import OrchestratorConfig

    cfg = OrchestratorConfig(
        True,
        "p.md",
        model_policy="inherit",
        agent_wave="wave-runner",
    )
    adapter = build_adapter(
        "cursor_local",
        options=BackendOptions(model="composer-2.5"),
        orchestrator=cfg,
    )
    assert isinstance(adapter, CursorLocalAdapter)
    assert adapter.agent == "wave-runner"
    assert adapter.model is None
    argv = adapter.build_argv({"wave_id": "W1", "agent": "wave-runner"}, Path("/wt"))
    assert "--agent" not in argv
    assert "wave-runner" in argv[-1]
    assert "--model" not in argv


def test_build_adapter_orchestrator_auto_model_for_cursor() -> None:
    from tripll.adapters import build_adapter
    from tripll.graph import OrchestratorConfig

    cfg = OrchestratorConfig(True, "p.md", model_policy="auto", agent_wave="wave-runner")
    adapter = build_adapter("cursor_local", orchestrator=cfg)
    assert isinstance(adapter, CursorLocalAdapter)
    assert adapter.model == "auto"
    argv = adapter.build_argv({"wave_id": "W1"}, Path("/wt"))
    assert "--model" in argv
    assert "auto" in argv


def test_parse_gate_result_heuristics() -> None:
    from tripll.orchestrator_gate import parse_gate_result

    assert parse_gate_result("Please approve to continue.").proceed is True
    assert parse_gate_result("dispatch W1 when ready").proceed is True
    assert parse_gate_result("STOP — blockers remain.").proceed is False
    # v2: disapprove is now correctly rejected (was fail-open in v1).
    assert parse_gate_result("I disapprove of this, do not continue.").proceed is False


async def test_dispatch_orchestrator_gate_stubbed(tmp_path: Path) -> None:
    from tripll.graph import OrchestratorConfig
    from tripll.orchestrator_gate import dispatch_orchestrator_gate

    class GateStubAdapter(FakeAdapter):
        name = "fake"

        async def dispatch(self, brief, **kwargs):  # type: ignore[no-untyped-def]
            return DispatchResult(
                outcome="done",
                result_text="Operator: approve to continue.",
                returncode=0,
            )

    cfg = OrchestratorConfig(True, "p.md", agent_orchestrator="wave-orchestrator")
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    decision = await dispatch_orchestrator_gate(
        run_dir,
        "W0.8 complete — present summary, STOP",
        {"wave_id": "W0", "gate_label": "W0.8"},
        adapter=GateStubAdapter(),
        orchestrator=cfg,
        worktree_path=tmp_path,
    )
    assert decision.proceed is True
    assert (run_dir / "logs" / "orchestrator-gate.log").parent.exists()


# ---------------------------------------------------------------------------
# cursor_cloud
# ---------------------------------------------------------------------------


def test_cursor_cloud_capabilities_reports_extra() -> None:
    caps = CursorCloudAdapter().capabilities()
    # sevn is not installed in the tripll venv → unavailable.
    assert caps.backend == "cursor_cloud"
    if not caps.available:
        assert "cloud extra" in caps.detail


def test_cursor_cloud_no_argv() -> None:
    assert CursorCloudAdapter().build_argv({}, Path("/wt")) == []


# ---------------------------------------------------------------------------
# fake adapter
# ---------------------------------------------------------------------------


async def test_fake_adapter_drives_to_done(tmp_path: Path) -> None:
    fake = FakeAdapter()
    result = await fake.dispatch(
        {"node_id": "telemetry:W1"},
        worktree_path=tmp_path,
        log_path=tmp_path / "a.log",
        timeout_s=10,
    )
    assert result.outcome == "done"
    assert fake.calls == 1


async def test_fake_adapter_fails_then_succeeds(tmp_path: Path) -> None:
    fake = FakeAdapter(fail_times=2)
    outcomes = [
        (
            await fake.dispatch(
                {"node_id": "n"},
                worktree_path=tmp_path,
                log_path=tmp_path / "a.log",
                timeout_s=10,
            )
        ).outcome
        for _ in range(3)
    ]
    assert outcomes == ["failed", "failed", "done"]


async def test_run_streaming_echo(tmp_path: Path) -> None:
    rc, out, quota = await run_streaming(
        ["echo", "hello"], cwd=tmp_path, log_path=tmp_path / "l.log", timeout_s=10
    )
    assert rc == 0
    assert "hello" in out
    assert quota is None


async def test_run_streaming_large_line(tmp_path: Path) -> None:
    rc, out, quota = await run_streaming(
        [sys.executable, "-c", "print('x' * 70000)"],
        cwd=tmp_path,
        log_path=tmp_path / "large.log",
        timeout_s=10,
    )
    assert rc == 0
    assert len(out) > 70000
    assert quota is None


def test_summarize_stream_line_milestones() -> None:
    assert summarize_stream_line('{"type":"system","subtype":"thinking_tokens"}') is None
    init = summarize_stream_line(
        '{"type":"system","subtype":"init","model":"claude-sonnet-4-6","cwd":"/wt"}'
    )
    assert init is not None
    assert "agent session started" in init
    task = summarize_stream_line(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Task",'
        '"input":{"subagent_type":"explore","description":"find modules"}}]}}'
    )
    assert task is not None
    assert "subagent explore" in task
    err = summarize_stream_line(
        '{"type":"user","message":{"content":[{"type":"tool_result","content":'
        '"Path contains traversal denied"}]}}'
    )
    assert err is not None
    assert "⚠" in err
    done = summarize_stream_line('{"type":"result","is_error":false,"result":"ok"}')
    assert done is not None
    assert "✓" in done


# ---------------------------------------------------------------------------
# run --dry-run prints argv
# ---------------------------------------------------------------------------


def test_run_dry_run_prints_claude_argv(tmp_path: Path) -> None:
    (tmp_path / "demo-wave-plan.md").write_text(
        "# Demo\n\n## Files in scope\n\n| Subsystem | Paths |\n|--|--|\n| Core | `src/sevn/demo/` |\n"
    )
    result = runner.invoke(app, ["run", str(tmp_path), "--backend", "claude_code", "--dry-run"])
    assert result.exit_code == 0
    assert "Exec argv" in result.output
    assert "claude" in result.output
    assert "stream-json" in result.output
