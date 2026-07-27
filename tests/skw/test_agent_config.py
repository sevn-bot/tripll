"""Tests for per-agent model parameter resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.agent_config import (
    AgentParams,
    apply_params_to_argv,
    merge_model_table,
    resolve_agent_id,
    resolve_agent_params,
    shell_export_params,
)


def test_merge_model_table_override_wins() -> None:
    merged = merge_model_table({"model": "auto"}, {"model": "opus-4", "thinking": "high"})
    assert merged["model"] == "opus-4"
    assert merged["thinking"] == "high"


def test_merge_model_table_max_token_out_wins() -> None:
    merged = merge_model_table(
        {"max_tokens": 1000},
        {"max_tokens": 2000, "max_token_out": 3000},
    )
    assert merged["max_tokens"] == 3000


def test_shell_export_extra_args() -> None:
    params = AgentParams(
        agent_id="wave-runner",
        model="auto",
        extra_args=("--verbose", "--flag=value"),
    )
    exports = shell_export_params(params)
    assert "SKW_EXTRA_ARGS=" in exports
    assert "--verbose" in exports
    assert "--flag=value" in exports


def test_shell_export_claude_effort() -> None:
    params = AgentParams(agent_id="reviewer", bin="claude", model="opus", thinking="high")
    exports = shell_export_params(params)
    assert "SKW_EFFORT='high'" in exports


def test_shell_export_clears_optional_vars_when_unset() -> None:
    params = AgentParams(agent_id="wave-runner", bin="cursor-agent", model="auto")
    exports = shell_export_params(params)
    assert "SKW_PLUGIN_DIR=''" in exports
    assert "SKW_EFFORT=''" in exports
    assert "SKW_EXTRA_ARGS=''" in exports


def test_apply_params_skips_effort_when_extra_args_include_it() -> None:
    params = AgentParams(
        agent_id="reviewer",
        bin="claude",
        model="opus",
        thinking="high",
        extra_args=("--effort", "medium"),
    )
    argv = apply_params_to_argv(["claude", "-p", "--model", "x"], params)
    assert argv.count("--effort") == 1
    assert "medium" in argv
    assert "high" not in argv


def test_resolve_global_model_from_skw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(KIT_ROOT)
    params = resolve_agent_params(kit_root=KIT_ROOT, stage="review")
    assert params.agent_id == "reviewer"
    assert params.model


def test_per_agent_override_in_wave_file() -> None:
    wave = KIT_ROOT / "waves" / "mission-control-control-plane-wave-plan.md"
    params = resolve_agent_params(
        kit_root=KIT_ROOT,
        stage="review",
        wave_data=__import__("tripll.skw.resolve_wave", fromlist=["load_wave_data"]).load_wave_data(
            wave
        ),
    )
    assert params.agent_id == "reviewer"
    assert params.thinking == "high"


def test_per_agent_wave_model_without_skw_model_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SKW_MODEL", raising=False)
    wave_data = {
        "pipeline": {
            "models": {"reviewer": {"model": "wave-reviewer-model"}},
        },
    }
    params = resolve_agent_params(kit_root=KIT_ROOT, stage="review", wave_data=wave_data)
    assert params.model == "wave-reviewer-model"


def test_skw_model_env_overrides_per_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKW_MODEL", "forced-global-model")
    wave_data = {
        "pipeline": {
            "models": {"reviewer": {"model": "wave-reviewer-model"}},
        },
    }
    params = resolve_agent_params(kit_root=KIT_ROOT, stage="review", wave_data=wave_data)
    assert params.model == "forced-global-model"


def test_apply_params_claude_effort() -> None:
    params = AgentParams(agent_id="reviewer", bin="claude", model="opus", thinking="high")
    argv = apply_params_to_argv(["claude", "-p", "--model", "x"], params)
    assert "--effort" in argv
    assert "high" in argv


def test_build_agent_argv_includes_prompt() -> None:
    from tripll.skw.agent_config import build_agent_argv

    params = AgentParams(agent_id="wave-runner", model="auto")
    argv = build_agent_argv(params, workspace="/tmp", output_fmt="text", prompt="hello")
    assert argv[-1] == "hello"


def test_cursor_auto_model_skips_effort_bracket() -> None:
    params = AgentParams(
        agent_id="reviewer",
        bin="cursor-agent",
        model="auto",
        thinking="high",
    )
    exports = shell_export_params(params)
    assert "SKW_MODEL='auto'" in exports
    assert "effort=" not in exports


def test_cursor_named_model_includes_effort_bracket() -> None:
    params = AgentParams(
        agent_id="reviewer",
        bin="cursor-agent",
        model="opus-4",
        thinking="high",
    )
    exports = shell_export_params(params)
    assert "effort=high" in exports


def test_model_flag_replaces_existing_effort_in_brackets() -> None:
    params = AgentParams(
        agent_id="reviewer",
        bin="cursor-agent",
        model="opus-4[effort=medium]",
        thinking="high",
    )
    exports = shell_export_params(params)
    assert "effort=high" in exports
    assert "effort=medium" not in exports


def test_model_flag_merges_effort_with_other_bracket_params() -> None:
    params = AgentParams(
        agent_id="reviewer",
        bin="cursor-agent",
        model="opus-4[foo=bar]",
        thinking="high",
    )
    argv = apply_params_to_argv(["cursor-agent", "-p", "--model", "x"], params)
    model_value = argv[argv.index("--model") + 1]
    assert model_value == "opus-4[foo=bar,effort=high]"


def test_resolve_agent_id_run_without_wave_data_defaults_wave_runner() -> None:
    assert resolve_agent_id(stage="run", wave_id="W1", wave_data=None) == "wave-runner"


def test_resolve_agent_id_run_uses_wave_role_when_data_present() -> None:
    from tripll.skw.resolve_wave import load_wave_data

    wave_data = load_wave_data(FIXTURES / "pipeline-three-wave.md")
    assert resolve_agent_id(stage="run", wave_id="W1", wave_data=wave_data) == "test-creator"
    assert resolve_agent_id(stage="run", wave_id="W2", wave_data=wave_data) == "wave-runner"


def test_plugin_dir_env_override_in_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKW_PLUGIN_DIR", "/tmp/custom-plugins")
    params = resolve_agent_params(kit_root=KIT_ROOT, stage="specify")
    assert params.plugin_dir == "/tmp/custom-plugins"


def test_build_agent_argv_flag_order() -> None:
    from tripll.skw.agent_config import build_agent_argv

    params = AgentParams(
        agent_id="reviewer",
        bin="claude",
        model="opus",
        thinking="high",
        perms="--force",
        plugin_dir="/tmp/plugins",
        extra_args=("--verbose",),
    )
    argv = build_agent_argv(params, workspace="/ws", output_fmt="text", prompt="hi")
    model_idx = argv.index("--model")
    verbose_idx = argv.index("--verbose")
    perms_idx = argv.index("--force")
    plugin_idx = argv.index("--plugin-dir")
    effort_idx = argv.index("--effort")
    assert model_idx < verbose_idx < perms_idx < plugin_idx < effort_idx < argv.index("hi")
