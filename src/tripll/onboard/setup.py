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
    "claude_code": "claude login  (or headless: claude setup-token → export CLAUDE_CODE_OAUTH_TOKEN)",
    "cursor_local": "cursor-agent login",
    "cursor_cloud": "Install tripll[cloud] and configure sevn.evolution.router",
}

_MANAGED_TOP_LEVEL_KEYS = frozenset({"default_provider", "providers", "tracing"})


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_scalar(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return f"{key} = {'true' if value else 'false'}"
    if isinstance(value, int):
        return f"{key} = {value}"
    if isinstance(value, float):
        return f"{key} = {value}"
    if isinstance(value, str):
        return f"{key} = {_toml_quote(value)}"
    if isinstance(value, list):
        items = ", ".join(
            _toml_quote(str(item)) if isinstance(item, str) else str(item) for item in value
        )
        return f"{key} = [{items}]"
    raise TypeError(f"unsupported TOML scalar for {key!r}: {type(value)!r}")


def _render_table(prefix: str, row: dict[str, Any], lines: list[str]) -> None:
    lines.append(f"[{prefix}]")
    for sub_key in sorted(row):
        sub_value = row[sub_key]
        if isinstance(sub_value, dict):
            raise TypeError(f"nested tables under {prefix}.{sub_key} are not supported")
        lines.append(_render_scalar(sub_key, sub_value))
    lines.append("")


def _render_extra_top_level(data: dict[str, Any], lines: list[str]) -> None:
    extras = [(key, data[key]) for key in sorted(data) if key not in _MANAGED_TOP_LEVEL_KEYS]
    for key, value in extras:
        if isinstance(value, dict):
            continue
        lines.append(_render_scalar(key, value))
        lines.append("")
    for key, value in extras:
        if isinstance(value, dict):
            _render_table(key, value, lines)


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
        for name in sorted(providers):
            row = providers[name]
            if isinstance(row, dict):
                _render_table(f"providers.{name}", row, lines)

    tracing = data.get("tracing")
    if isinstance(tracing, dict):
        _render_table("tracing", tracing, lines)

    _render_extra_top_level(data, lines)
    return "\n".join(lines).rstrip() + "\n"


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge *patch* into *base*, recursing one level for nested dict values."""
    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            row = dict(existing)
            row.update(value)
            merged[key] = row
        else:
            merged[key] = value
    return merged


def write_user_config(data: dict[str, Any], *, path: Path | None = None) -> Path:
    """Merge-write user config — existing keys are preserved unless overridden."""
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
            merged[key] = _deep_merge_dict(merged[key], value)
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
    """Run ``tripll setup`` — detect backends and write user config."""
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
