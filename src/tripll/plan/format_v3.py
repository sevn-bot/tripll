"""Parse and emit ``waveorch_format = 3`` wave plans."""

from __future__ import annotations

import io
import tomllib
from typing import Any

VALID_DEPENDS_REASONS = frozenset({"artifact", "contract", "gate"})


def parse_plan_v3(text: str) -> dict[str, Any]:
    """Parse a v3 plan TOML document into a normalised dict."""
    raw = tomllib.load(io.BytesIO(text.encode("utf-8")))
    if not isinstance(raw, dict):
        raise ValueError("plan root must be a TOML table")
    fmt = raw.get("waveorch_format")
    if fmt != 3:
        raise ValueError(f"expected waveorch_format = 3, got {fmt!r}")
    waves = raw.get("waves")
    if not isinstance(waves, list):
        raise ValueError("waves must be a list")
    normalised_waves: list[dict[str, Any]] = []
    for wave in waves:
        if not isinstance(wave, dict):
            raise ValueError("each wave must be a table")
        entry = dict(wave)
        depends = entry.get("depends_on")
        if depends is None:
            entry["depends_on"] = []
        elif not isinstance(depends, list):
            raise ValueError("waves.depends_on must be a list")
        targets = entry.get("targets")
        if targets is None:
            entry["targets"] = []
        elif not isinstance(targets, list):
            raise ValueError("waves.targets must be a list")
        verify = entry.get("verify")
        if verify is None:
            entry["verify"] = []
        elif not isinstance(verify, list):
            raise ValueError("waves.verify must be a list")
        outcome = entry.get("outcome")
        if outcome is not None and not isinstance(outcome, dict):
            raise ValueError("waves.outcome must be a table")
        normalised_waves.append(entry)
    raw["waves"] = normalised_waves
    raw["waveorch_format"] = 3
    return raw


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _emit_string_list(values: list[Any], *, indent: str) -> list[str]:
    if not values:
        return []
    return [f"{indent}{_toml_quote(str(v))}" for v in values]


def emit_plan_v3(plan: dict[str, Any]) -> str:
    """Emit a v3 plan as TOML text."""
    lines: list[str] = [
        "waveorch_format = 3",
        f"title = {_toml_quote(str(plan.get('title', '')))}",
        f"slug = {_toml_quote(str(plan.get('slug', '')))}",
        f"base = {_toml_quote(str(plan.get('base', 'main')))}",
    ]
    branch = plan.get("branch")
    if branch:
        lines.append(f"branch = {_toml_quote(str(branch))}")
    target_repo = plan.get("target_repo")
    if target_repo:
        lines.append(f"target_repo = {_toml_quote(str(target_repo))}")
    lines.append("")
    pipeline = plan.get("pipeline")
    if isinstance(pipeline, dict) and pipeline:
        lines.append("[pipeline]")
        for key in ("max_turns", "deadline", "budget_usd"):
            if key in pipeline:
                value = pipeline[key]
                if isinstance(value, str):
                    lines.append(f"{key} = {_toml_quote(value)}")
                else:
                    lines.append(f"{key} = {value}")
        lines.append("")
    for wave in plan.get("waves", []):
        if not isinstance(wave, dict):
            continue
        lines.append("[[waves]]")
        for key in ("id", "title", "role", "effort"):
            if key in wave and wave[key] is not None:
                lines.append(f"{key} = {_toml_quote(str(wave[key]))}")
        for list_key in ("targets", "verify"):
            values = wave.get(list_key) or []
            if values:
                lines.append(f"{list_key} = [")
                lines.extend(_emit_string_list(values, indent="  "))
                lines.append("]")
        for dep in wave.get("depends_on") or []:
            if not isinstance(dep, dict):
                continue
            lines.append("")
            lines.append("  [[waves.depends_on]]")
            if dep.get("wave"):
                lines.append(f"  wave = {_toml_quote(str(dep['wave']))}")
            if dep.get("reason"):
                lines.append(f"  reason = {_toml_quote(str(dep['reason']))}")
            if dep.get("detail"):
                lines.append(f"  detail = {_toml_quote(str(dep['detail']))}")
        outcome = wave.get("outcome")
        if isinstance(outcome, dict) and outcome:
            lines.append("")
            lines.append("  [waves.outcome]")
            for key in ("required", "forbidden", "evidence"):
                values = outcome.get(key) or []
                if values:
                    lines.append(f"  {key} = [")
                    lines.extend(_emit_string_list(values, indent="    "))
                    lines.append("  ]")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
