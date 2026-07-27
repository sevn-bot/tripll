"""Read legacy v1/v2 wave plans and emit v3 in memory."""

from __future__ import annotations

import io
import tomllib
import warnings
from typing import TYPE_CHECKING, Any

from tripll.parse.plan_files import _slice_section
from tripll.parse.wave_plan_v1 import EXEC_GRAPH_HEADING, TRIPLL_FORMAT_MARKER, parse_wave_plan_v1

if TYPE_CHECKING:
    from pathlib import Path

_WARNED_PATHS: set[Path] = set()


def _warn_once(path: Path, message: str) -> list[str]:
    from pathlib import Path as PathCls

    resolved = PathCls(path).resolve()
    if resolved in _WARNED_PATHS:
        return []
    _WARNED_PATHS.add(resolved)
    warnings.warn(message, stacklevel=3)
    return [message]


def _v1_to_v3(path: Path, text: str) -> dict[str, Any]:
    from pathlib import Path as PathCls

    parsed = parse_wave_plan_v1(PathCls(path))
    slug = parsed.plan_id
    waves: list[dict[str, Any]] = []
    for spec in parsed.waves:
        depends_on = [{"wave": dep, "reason": "gate"} for dep in spec.depends_on]
        waves.append(
            {
                "id": spec.wave_id,
                "title": spec.title or spec.wave_id,
                "role": spec.role,
                "effort": spec.effort,
                "targets": list(parsed.owned_paths),
                "verify": list(spec.verify_targets),
                "depends_on": depends_on,
            }
        )
    return {
        "waveorch_format": 3,
        "title": parsed.title,
        "slug": slug,
        "base": "main",
        "pipeline": {},
        "waves": waves,
    }


def _v2_to_v3(raw: dict[str, Any]) -> dict[str, Any]:
    waves: list[dict[str, Any]] = []
    for wave in raw.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        entry = dict(wave)
        depends = entry.get("depends_on") or []
        if depends and isinstance(depends[0], dict):
            normalised = []
            for dep in depends:
                if not isinstance(dep, dict):
                    continue
                reason = dep.get("reason") or "contract"
                normalised.append(
                    {
                        "wave": dep.get("wave"),
                        "reason": reason,
                        "detail": dep.get("detail"),
                    }
                )
            entry["depends_on"] = normalised
        entry.setdefault("targets", [])
        entry.setdefault("verify", [])
        waves.append(entry)
    return {
        "waveorch_format": 3,
        "title": raw.get("title", ""),
        "slug": raw.get("slug", ""),
        "base": raw.get("base", "main"),
        "branch": raw.get("branch"),
        "pipeline": raw.get("pipeline") or {},
        "waves": waves,
    }


def _detect_format(text: str) -> int:
    import re

    head = text.lstrip()[:800]
    if "waveorch_format" in head:
        match = re.search(r"waveorch_format\s*=\s*(\d+)", head)
        if match:
            return int(match.group(1))
    if EXEC_GRAPH_HEADING in text or TRIPLL_FORMAT_MARKER in text:
        section = _slice_section(text, EXEC_GRAPH_HEADING)
        for line in (section or text).splitlines()[:5]:
            if TRIPLL_FORMAT_MARKER in line:
                match = re.search(r"tripll_format:\s*(\d+)", line, re.I)
                if match:
                    return int(match.group(1))
        return 1
    return 0


def read_legacy_plan(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read a v1 or v2 plan file and return a v3 dict plus warning messages."""
    from pathlib import Path as PathCls

    plan_path = PathCls(path)
    text = plan_path.read_text(encoding="utf-8")
    fmt = _detect_format(text)
    msgs: list[str] = []
    if fmt == 3:
        from tripll.plan.format_v3 import parse_plan_v3

        return parse_plan_v3(text), msgs
    if fmt == 2:
        raw = tomllib.load(io.BytesIO(text.encode("utf-8")))
        msgs.extend(
            _warn_once(
                plan_path,
                f"{plan_path.name}: waveorch_format=2 is deprecated; emitted v3 in memory",
            )
        )
        return _v2_to_v3(raw), msgs
    if fmt == 1:
        msgs.extend(
            _warn_once(
                plan_path,
                f"{plan_path.name}: tripll execution graph v1 is deprecated; emitted v3 in memory",
            )
        )
        return _v1_to_v3(plan_path, text), msgs
    raise ValueError(f"unsupported plan format in {plan_path}")


def reset_legacy_warnings() -> None:
    """Clear the warn-once cache (tests only)."""
    _WARNED_PATHS.clear()
