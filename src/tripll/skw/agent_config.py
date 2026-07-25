"""Resolve per-agent model parameters from tripll.skw.toml, wave-file TOML, and env.

Exports:
    AgentParams — resolved model + generation parameters for one agent dispatch.
    VALID_THINKING — allowed thinking / effort values.
    merge_model_table — shallow merge of model parameter tables.
    resolve_agent_id — map pipeline stage + wave context → agent id.
    resolve_agent_params — full resolution for driver argv building.
    apply_params_to_argv — append CLI flags for cursor-agent / claude.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tripll.skw.resolve_wave import agent_for_role, load_wave_data, wave_role

__all__ = [
    "VALID_THINKING",
    "AgentParams",
    "apply_params_to_argv",
    "merge_model_table",
    "resolve_agent_id",
    "resolve_agent_params",
]

VALID_THINKING = frozenset({"low", "medium", "high", "xhigh", "max"})
_MODEL_KEYS = frozenset(
    {"model", "max_tokens", "max_token_out", "temperature", "thinking", "extra_args"}
)
_BRACKET_PARAM_RE = re.compile(r"^(.+)\[(.+)\]$")


@dataclass(frozen=True)
class AgentParams:
    """Resolved model parameters for one agent dispatch."""

    agent_id: str
    bin: str = "cursor-agent"
    model: str = "auto"
    max_tokens: int | None = None
    temperature: float | None = None
    thinking: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    perms: str = "--force"
    plugin_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / HTML artifacts.

        Returns:
            dict[str, Any]: JSON-compatible parameter map (omits empty optionals).

        Examples:
            >>> AgentParams(agent_id="wave-runner", model="auto").to_dict()["agent_id"]
            'wave-runner'
        """
        out: dict[str, Any] = {
            "agent_id": self.agent_id,
            "bin": self.bin,
            "model": self.model,
        }
        if self.max_tokens is not None:
            out["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.thinking:
            out["thinking"] = self.thinking
        if self.extra_args:
            out["extra_args"] = list(self.extra_args)
        if self.perms:
            out["perms"] = self.perms
        if self.plugin_dir:
            out["plugin_dir"] = self.plugin_dir
        return out

    def display_summary(self) -> str:
        """One-line human summary for diagrams.

        Returns:
            str: Compact parameter summary.

        Examples:
            >>> AgentParams(agent_id="x", model="opus", thinking="high").display_summary()
            'opus · thinking=high'
        """
        parts = [self.model]
        if self.max_tokens is not None:
            parts.append(f"max_tokens={self.max_tokens}")
        if self.temperature is not None:
            parts.append(f"temperature={self.temperature}")
        if self.thinking:
            parts.append(f"thinking={self.thinking}")
        return " · ".join(parts)


def merge_model_table(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """Merge optional model parameter tables (override wins).

    Args:
        base (dict[str, Any]): Lower-priority table.
        override (dict[str, Any] | None): Higher-priority table.

    Returns:
        dict[str, Any]: Merged copy.

    Examples:
        >>> merge_model_table({"model": "auto"}, {"model": "opus"})["model"]
        'opus'
    """
    merged = dict(base)
    if not override:
        return merged
    scalar_keys = sorted(_MODEL_KEYS - {"max_tokens", "max_token_out", "extra_args"})
    for key in scalar_keys:
        if key not in override:
            continue
        val = override[key]
        if val is None:
            continue
        if key == "temperature" and isinstance(val, (int, float)):
            merged[key] = float(val)
        elif key == "thinking" and isinstance(val, str) and val.strip():
            merged[key] = val.strip().lower()
        elif key == "model" and isinstance(val, str) and val.strip():
            merged[key] = val.strip()
    extra = override.get("extra_args")
    if isinstance(extra, list):
        merged["extra_args"] = [str(v) for v in extra if str(v).strip()]
    if "max_tokens" in override:
        val = override["max_tokens"]
        if isinstance(val, int):
            merged["max_tokens"] = val
    if "max_token_out" in override:
        val = override["max_token_out"]
        if isinstance(val, int):
            merged["max_tokens"] = val
    return merged


def _table_from_agent_cfg(agent_cfg: dict[str, Any]) -> dict[str, Any]:
    table: dict[str, Any] = {}
    for key in ("model", "max_tokens", "max_token_out", "temperature", "thinking"):
        if key in agent_cfg and agent_cfg[key] is not None:
            dest = "max_tokens" if key == "max_token_out" else key
            table[dest] = agent_cfg[key]
    extra = agent_cfg.get("extra_args")
    if isinstance(extra, list):
        table["extra_args"] = extra
    return table


def _per_agent_tables(parent: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    models = parent.get(key, {})
    if not isinstance(models, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for agent_id, table in models.items():
        if isinstance(agent_id, str) and isinstance(table, dict):
            out[agent_id] = table
    return out


def _wave_model_tables(
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    pipeline = data.get("pipeline", {})
    if not isinstance(pipeline, dict):
        return {}, {}, {}
    global_table = pipeline.get("model", {})
    if not isinstance(global_table, dict):
        global_table = {}
    by_agent = _per_agent_tables(pipeline, "models")
    by_stage: dict[str, dict[str, Any]] = {}
    for stage in ("run", "review", "generate"):
        stage_data = pipeline.get(stage, {})
        if isinstance(stage_data, dict):
            model_table = stage_data.get("model")
            if isinstance(model_table, dict):
                by_stage[stage] = model_table
    return global_table, by_agent, by_stage


def _skw_model_tables(skw_cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    agent = skw_cfg.get("agent", {})
    if not isinstance(agent, dict):
        return {}, {}
    global_table = _table_from_agent_cfg(agent)
    by_agent = _per_agent_tables(agent, "models")
    return global_table, by_agent


def resolve_agent_id(
    *,
    stage: str,
    wave_data: dict[str, Any] | None = None,
    wave_id: str | None = None,
) -> str:
    """Map a pipeline dispatch to the resolved agent id.

    Args:
        stage (str): ``run``, ``review``, ``generate``, or front-end stage id.
        wave_data (dict[str, Any] | None): Parsed wave-file TOML.
        wave_id (str | None): Target wave id for ``run`` stage.

    Returns:
        str: Agent id string.

    Examples:
        >>> resolve_agent_id(stage="review", wave_data={"pipeline": {"review": {"agent": "reviewer"}}})
        'reviewer'
    """
    if stage == "run":
        if wave_id and wave_data is not None:
            return agent_for_role(wave_role(wave_data, wave_id))
        return "wave-runner"
    if stage == "review":
        if wave_data:
            pipeline = wave_data.get("pipeline", {})
            if isinstance(pipeline, dict):
                review = pipeline.get("review", {})
                if isinstance(review, dict):
                    agent = review.get("agent")
                    if isinstance(agent, str) and agent.strip():
                        return agent.strip()
        return "reviewer"
    if stage == "generate":
        if wave_data:
            pipeline = wave_data.get("pipeline", {})
            if isinstance(pipeline, dict):
                generate = pipeline.get("generate", {})
                if isinstance(generate, dict):
                    agent = generate.get("agent")
                    if isinstance(agent, str) and agent.strip():
                        return agent.strip()
        return "post-review-wave-generator"
    if stage in {
        "wave-generator",
        "specify",
        "clarify",
        "plan",
        "orchestrator",
        "test-creator",
        "wave-runner",
        "reviewer",
        "post-review-wave-generator",
    }:
        return stage
    return stage


def resolve_agent_params(
    *,
    kit_root: Any,
    stage: str,
    wave_data: dict[str, Any] | None = None,
    wave_id: str | None = None,
    skw_cfg: dict[str, Any] | None = None,
) -> AgentParams:
    """Resolve model parameters for one agent dispatch.

    Resolution order (later tables override earlier):

    1. ``skw.toml`` ``[agent]`` global defaults
    2. ``skw.toml`` ``[agent.models.<agent_id>]``
    3. Wave-file ``[pipeline.model]`` (optional global for this plan)
    4. Wave-file ``[pipeline.models.<agent_id>]``
    5. Wave-file ``[pipeline.<stage>.model]`` (``run`` applies to ``wave-runner`` only)
    6. Env ``SKW_MODEL`` overrides ``model``; ``SKW_AGENT_BIN``, ``SKW_PERMS``, ``SKW_PLUGIN_DIR``

    Args:
        kit_root: Kit root (unused today; reserved for future kit-local overrides).
        stage (str): Pipeline stage.
        wave_data (dict[str, Any] | None): Parsed wave-file TOML.
        wave_id (str | None): Target wave id for ``run`` stage.
        skw_cfg (dict[str, Any] | None): Pre-loaded ``skw.toml`` config.

    Returns:
        AgentParams: Resolved parameters.

    Examples:
        >>> from pathlib import Path
        >>> from tripll.skw.validate import load_skw_config
        >>> cfg = load_skw_config(Path("."))
        >>> p = resolve_agent_params(kit_root=Path("."), stage="review", skw_cfg=cfg)
        >>> p.agent_id
        'reviewer'
    """
    _ = kit_root
    from tripll.skw.validate import load_skw_config

    cfg = (
        skw_cfg
        if skw_cfg is not None
        else load_skw_config(kit_root if hasattr(kit_root, "is_dir") else Path("."))
    )
    agent_cfg = cfg.get("agent", {}) if isinstance(cfg.get("agent"), dict) else {}
    agent_id = resolve_agent_id(stage=stage, wave_data=wave_data, wave_id=wave_id)

    skw_global, skw_by_agent = _skw_model_tables(cfg)
    merged = merge_model_table({}, skw_global)
    merged = merge_model_table(merged, skw_by_agent.get(agent_id))

    if wave_data is not None:
        wave_global, wave_by_agent, wave_by_stage = _wave_model_tables(wave_data)
        merged = merge_model_table(merged, wave_global)
        merged = merge_model_table(merged, wave_by_agent.get(agent_id))
        stage_table = wave_by_stage.get(stage)
        if stage_table and (stage != "run" or agent_id == "wave-runner"):
            merged = merge_model_table(merged, stage_table)

    model = str(merged.get("model") or agent_cfg.get("model") or "auto")
    max_tokens = merged.get("max_tokens")
    if not isinstance(max_tokens, int):
        max_tokens = None
    temperature = merged.get("temperature")
    temperature = None if not isinstance(temperature, (int, float)) else float(temperature)
    thinking = merged.get("thinking")
    if not isinstance(thinking, str) or not thinking.strip():
        thinking = None
    else:
        thinking = thinking.strip().lower()

    extra_args_raw = merged.get("extra_args", [])
    extra_args: tuple[str, ...] = ()
    if isinstance(extra_args_raw, list):
        extra_args = tuple(str(a) for a in extra_args_raw if str(a).strip())

    bin_name = str(os.environ.get("SKW_AGENT_BIN") or agent_cfg.get("bin") or "cursor-agent")
    perms = str(os.environ.get("SKW_PERMS") or agent_cfg.get("perms") or "--force")
    plugin_dir = str(os.environ.get("SKW_PLUGIN_DIR") or agent_cfg.get("plugin_dir") or "")

    env_model = os.environ.get("SKW_MODEL", "").strip()
    if env_model:
        model = env_model
    env_agent_model = os.environ.get(f"SKW_MODEL_{agent_id.upper().replace('-', '_')}", "").strip()
    if env_agent_model:
        model = env_agent_model

    return AgentParams(
        agent_id=agent_id,
        bin=bin_name,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking=thinking,
        extra_args=extra_args,
        perms=perms,
        plugin_dir=plugin_dir,
    )


def build_agent_argv(
    params: AgentParams,
    *,
    workspace: str,
    output_fmt: str,
    prompt: str,
) -> list[str]:
    """Build full agent CLI argv from resolved parameters.

    Args:
        params (AgentParams): Resolved agent parameters.
        workspace (str): Agent workspace directory.
        output_fmt (str): ``--output-format`` value.
        prompt (str): Rendered prompt text.

    Returns:
        list[str]: Complete argv including prompt as final argument.

    Examples:
        >>> argv = build_agent_argv(
        ...     AgentParams(agent_id="wave-runner", model="auto"),
        ...     workspace="/tmp",
        ...     output_fmt="text",
        ...     prompt="hi",
        ... )
        >>> argv[-1]
        'hi'
    """
    prefix: list[str] = [
        params.bin,
        "-p",
        "--output-format",
        output_fmt,
        "--workspace",
        workspace,
        "--model",
        params.model,
    ]
    if params.perms.strip():
        prefix.extend(params.perms.split())
    if params.plugin_dir.strip():
        prefix.extend(["--plugin-dir", params.plugin_dir])
    prefix = apply_params_to_argv(prefix, params)
    prefix.append(prompt)
    return prefix


def shell_export_params(params: AgentParams) -> str:
    """Emit shell ``export`` lines for ``agent.sh`` bootstrap.

    Args:
        params (AgentParams): Resolved parameters.

    Returns:
        str: Newline-separated export statements.

    Examples:
        >>> 'SKW_MODEL=' in shell_export_params(AgentParams(agent_id='x', model='auto'))
        True
    """
    lines = [
        f"SKW_AGENT_BIN={_shell_quote(params.bin)}",
        f"SKW_MODEL={_shell_quote(_model_flag_value(params))}",
        f"SKW_PERMS={_shell_quote(params.perms)}",
        f"SKW_PLUGIN_DIR={_shell_quote(params.plugin_dir)}",
    ]
    effort = params.thinking if params.thinking and params.bin == "claude" else ""
    lines.append(f"SKW_EFFORT={_shell_quote(effort)}")
    extra = shlex.join(params.extra_args) if params.extra_args else ""
    lines.append(f"SKW_EXTRA_ARGS={_shell_quote(extra)}")
    return "\n".join(lines)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _merge_bracket_effort(bracket_inner: str, thinking: str) -> str:
    """Merge ``effort=<thinking>`` into an existing bracket parameter list."""
    parts = [part.strip() for part in bracket_inner.split(",") if part.strip()]
    merged: list[str] = []
    replaced = False
    for part in parts:
        if part.startswith("effort="):
            merged.append(f"effort={thinking}")
            replaced = True
        else:
            merged.append(part)
    if not replaced:
        merged.append(f"effort={thinking}")
    return ",".join(merged)


def _model_flag_value(params: AgentParams) -> str:
    """Build ``--model`` value with optional cursor-agent bracket params."""
    model = params.model
    if params.bin != "cursor-agent" or not params.thinking:
        return model
    if params.thinking not in VALID_THINKING:
        return model
    match = _BRACKET_PARAM_RE.match(model)
    base = match.group(1) if match else model
    if base == "auto":
        return model
    if match:
        return f"{base}[{_merge_bracket_effort(match.group(2), params.thinking)}]"
    return f"{base}[effort={params.thinking}]"


def apply_params_to_argv(argv: list[str], params: AgentParams) -> list[str]:
    """Append model / effort / extra_args flags to an agent argv prefix.

    Args:
        argv (list[str]): Base argv without the prompt (must include ``--model`` placeholder slot).
        params (AgentParams): Resolved parameters.

    Returns:
        list[str]: Updated argv (prompt not appended).

    Examples:
        >>> p = AgentParams(agent_id="r", bin="claude", model="opus", thinking="high")
        >>> out = apply_params_to_argv(["claude", "-p", "--model", "x"], p)
        >>> "--effort" in out and "high" in out
        True
    """
    out = list(argv)
    model_idx = out.index("--model") if "--model" in out else -1
    model_value = _model_flag_value(params)
    if model_idx >= 0 and model_idx + 1 < len(out):
        out[model_idx + 1] = model_value
    else:
        out.extend(["--model", model_value])

    if params.extra_args:
        insert_at = len(out)
        for i, _ in enumerate(out):
            if i > 0 and out[i - 1] == "--model":
                insert_at = i + 1
                break
        out[insert_at:insert_at] = list(params.extra_args)

    if (
        params.bin == "claude"
        and params.thinking
        and params.thinking in VALID_THINKING
        and "--effort" not in out
    ):
        out.extend(["--effort", params.thinking])

    return out


def load_wave_data_optional(wave_path: Any) -> dict[str, Any] | None:
    """Load wave TOML when *wave_path* exists."""
    path = wave_path
    if path is None or not hasattr(path, "is_file") or not path.is_file():
        return None
    return load_wave_data(path)
