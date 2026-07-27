"""One-time operator setup — writes user config without storing credentials (W13).

Exports:
    AUTH_FIX_COMMANDS — backend → login command hint (R24).
    run_setup — interactive or non-interactive setup flow.
    write_user_config — merge-write ``~/.config/tripll/config.toml``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import typer

from tripll.adapters import BACKENDS, get_adapter
from tripll.config import load_config, user_config_path
from tripll.tracing.config import TracingConfig

__all__ = ["AUTH_FIX_COMMANDS", "run_setup", "write_user_config"]

AUTH_FIX_COMMANDS: dict[str, str] = {
    "claude_code": "claude login",
    "cursor_local": "cursor-agent login",
    "cursor_cloud": "Install tripll[cloud] and configure sevn.evolution.router",
}


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_config(data: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Written by `tripll setup` — routing and limits only (R24: no credentials).",
        "",
    ]
    if "default_provider" in data:
        lines.append(f"default_provider = {_toml_quote(str(data['default_provider']))}")
        lines.append("")

    providers = data.get("providers")
    if isinstance(providers, dict):
        for name, row in providers.items():
            if not isinstance(row, dict):
                continue
            lines.append(f"[providers.{name}]")
            if "max_parallel" in row:
                lines.append(f"max_parallel = {int(row['max_parallel'])}")
            if "default_model" in row:
                lines.append(f"default_model = {_toml_quote(str(row['default_model']))}")
            lines.append("")

    tracing = data.get("tracing")
    if isinstance(tracing, dict):
        lines.append("[tracing]")
        if "enabled" in tracing:
            lines.append(f"enabled = {'true' if tracing['enabled'] else 'false'}")
        sinks = tracing.get("sinks")
        if isinstance(sinks, list):
            sink_items = ", ".join(_toml_quote(str(s)) for s in sinks)
            lines.append(f"sinks = [{sink_items}]")
        if "retention_days" in tracing:
            lines.append(f"retention_days = {int(tracing['retention_days'])}")
        if "capture" in tracing:
            lines.append(f"capture = {_toml_quote(str(tracing['capture']))}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_user_config(data: dict[str, Any], *, path: Path | None = None) -> Path:
    """Merge-write user config — existing keys are preserved unless overridden.

    Args:
        data (dict[str, Any]): New tables to merge in.
        path (Path | None): Destination file (default user config path).

    Returns:
        Path: Written config file path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     p = Path(d) / "config.toml"
        ...     out = write_user_config({"default_provider": "cursor_local"}, path=p)
        ...     assert out == p
        ...     assert "cursor_local" in out.read_text()
    """
    dest = path or user_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if dest.is_file():
        with dest.open("rb") as handle:
            loaded = tomllib.load(handle)
        if isinstance(loaded, dict):
            existing = loaded

    merged = dict(existing)
    for key, value in data.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            row = dict(merged[key])
            row.update(value)
            merged[key] = row
        else:
            merged[key] = value

    dest.write_text(_render_config(merged), encoding="utf-8")
    return dest


def _probe_providers() -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    for name in BACKENDS:
        caps = get_adapter(name).capabilities()
        out[name] = (caps.available, caps.detail)
    return out


def _default_tracing_dict(cfg: TracingConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "sinks": list(cfg.sinks),
        "retention_days": cfg.retention_days,
        "capture": cfg.capture,
    }


def run_setup(
    *,
    non_interactive: bool = False,
    provider: str | None = None,
) -> Path:
    """Run ``tripll setup`` — detect backends and write user config.

    Args:
        non_interactive (bool): Skip prompts; use defaults and *provider*.
        provider (str | None): Default provider for non-interactive mode.

    Returns:
        Path: Written config file path.

    Raises:
        typer.Exit: When no provider is selected in non-interactive mode.

    Examples:
        >>> import tempfile
        >>> from unittest.mock import patch
        >>> with tempfile.TemporaryDirectory() as d, patch(
        ...     "tripll.onboard.setup.user_config_path",
        ...     return_value=__import__("pathlib").Path(d) / "config.toml",
        ... ):
        ...     p = run_setup(non_interactive=True, provider="cursor_local")
        ...     assert p.is_file()
    """
    probes = _probe_providers()
    cfg = load_config()

    for name, (available, detail) in probes.items():
        status = "available" if available else "unavailable"
        typer.echo(f"  {name}: {status} — {detail}")
        if not available and name in AUTH_FIX_COMMANDS:
            typer.echo(f"    fix: {AUTH_FIX_COMMANDS[name]}")

    if non_interactive:
        chosen = provider or cfg.default_provider
        if chosen not in BACKENDS:
            typer.echo(f"Unknown provider {chosen!r}.", err=True)
            raise typer.Exit(2)
    else:
        available_names = [n for n, (ok, _) in probes.items() if ok]
        if not available_names:
            typer.echo("No providers available. Install a backend CLI and re-run setup.", err=True)
            raise typer.Exit(1)
        default = (
            cfg.default_provider if cfg.default_provider in available_names else available_names[0]
        )
        typer.echo(f"Available providers: {', '.join(available_names)}")
        chosen = typer.prompt("Default provider", default=default)
        if chosen not in BACKENDS:
            typer.echo(f"Unknown provider {chosen!r}.", err=True)
            raise typer.Exit(2)

    providers_cfg: dict[str, Any] = {}
    for name in BACKENDS:
        row = cfg.providers[name]
        providers_cfg[name] = {
            "max_parallel": row.max_parallel,
            "default_model": row.default_model,
        }

    payload: dict[str, Any] = {
        "default_provider": chosen,
        "providers": providers_cfg,
        "tracing": _default_tracing_dict(cfg.tracing),
    }
    dest = write_user_config(payload)
    typer.echo(f"Wrote {dest}")
    return dest
