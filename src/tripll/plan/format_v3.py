"""Parse and emit ``waveorch_format = 3`` wave plans."""

from __future__ import annotations

import io
import tomllib
from typing import Any

VALID_DEPENDS_REASONS = frozenset({"artifact", "contract", "gate"})
VALID_REFERENCE_KINDS = frozenset(
    {"screenshot", "html_crop", "spec_section", "skill_exemplar", "benchmark_task", "rubric_only"}
)
VALID_REFERENCE_COMPARISONS = frozenset({"blind_ab", "side_by_side", "rubric"})
VALID_REFERENCE_STOP_WHEN = frozenset({"reference_wins", "max_rounds", "operator"})
VALID_QUALITY_DECOMPOSITION = frozenset({"prescribed", "gauntlet"})


def _validate_reference_table(reference: dict[str, Any]) -> None:
    kind = reference.get("kind")
    if kind is not None and kind not in VALID_REFERENCE_KINDS:
        raise ValueError(
            f"waves.outcome.reference.kind must be one of {sorted(VALID_REFERENCE_KINDS)}"
        )
    comparison = reference.get("comparison")
    if comparison is not None and comparison not in VALID_REFERENCE_COMPARISONS:
        raise ValueError(
            "waves.outcome.reference.comparison must be one of "
            f"{sorted(VALID_REFERENCE_COMPARISONS)}"
        )
    stop_when = reference.get("stop_when")
    if stop_when is not None and stop_when not in VALID_REFERENCE_STOP_WHEN:
        raise ValueError(
            f"waves.outcome.reference.stop_when must be one of {sorted(VALID_REFERENCE_STOP_WHEN)}"
        )
    path = reference.get("path")
    if path is not None and not isinstance(path, str):
        raise ValueError("waves.outcome.reference.path must be a string")


def _validate_quality_gauntlet_table(quality: dict[str, Any]) -> None:
    decomposition = quality.get("decomposition")
    if decomposition is not None and decomposition not in VALID_QUALITY_DECOMPOSITION:
        raise ValueError(
            "waves.outcome.quality_gauntlet.decomposition must be one of "
            f"{sorted(VALID_QUALITY_DECOMPOSITION)}"
        )
    max_rounds = quality.get("max_rounds")
    if max_rounds is not None and not isinstance(max_rounds, int):
        raise ValueError("waves.outcome.quality_gauntlet.max_rounds must be an integer")
    sub_budget = quality.get("sub_budget_usd")
    if sub_budget is not None and not isinstance(sub_budget, (int, float)):
        raise ValueError("waves.outcome.quality_gauntlet.sub_budget_usd must be a number")


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
        if isinstance(outcome, dict):
            reference = outcome.get("reference")
            if reference is not None:
                if not isinstance(reference, dict):
                    raise ValueError("waves.outcome.reference must be a table")
                _validate_reference_table(reference)
            quality_gauntlet = outcome.get("quality_gauntlet")
            if quality_gauntlet is not None:
                if not isinstance(quality_gauntlet, dict):
                    raise ValueError("waves.outcome.quality_gauntlet must be a table")
                _validate_quality_gauntlet_table(quality_gauntlet)
        decomposition = entry.get("decomposition")
        if decomposition is not None and decomposition not in VALID_QUALITY_DECOMPOSITION:
            raise ValueError(
                f"waves.decomposition must be one of {sorted(VALID_QUALITY_DECOMPOSITION)}"
            )
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
        for key in ("id", "title", "role", "effort", "decomposition"):
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
            reference = outcome.get("reference")
            if isinstance(reference, dict) and reference:
                lines.append("")
                lines.append("  [waves.outcome.reference]")
                for key in ("kind", "path", "comparison", "stop_when"):
                    if key in reference and reference[key] is not None:
                        lines.append(f"  {key} = {_toml_quote(str(reference[key]))}")
            quality_gauntlet = outcome.get("quality_gauntlet")
            if isinstance(quality_gauntlet, dict) and quality_gauntlet:
                lines.append("")
                lines.append("  [waves.outcome.quality_gauntlet]")
                if "enabled" in quality_gauntlet:
                    lines.append(f"  enabled = {bool(quality_gauntlet['enabled'])}")
                for key in ("max_rounds", "sub_budget_usd"):
                    if key in quality_gauntlet and quality_gauntlet[key] is not None:
                        lines.append(f"  {key} = {quality_gauntlet[key]}")
                if quality_gauntlet.get("decomposition") is not None:
                    lines.append(
                        f"  decomposition = {_toml_quote(str(quality_gauntlet['decomposition']))}"
                    )
                if "smoothing" in quality_gauntlet:
                    lines.append(f"  smoothing = {bool(quality_gauntlet['smoothing'])}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
