"""Makefile next-step hint computation (Wave W6).

Reads compiled pipeline order + wave-file checkbox state and returns the next
manual ``make`` target (``test-creator-run``, ``wave-runner-run``, ``reviewer-run``,
``post-review-wave-generator-run``, or ``PASS``).

Exports:
    compute_next_step — emit next ``make`` command string (W6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tripll.skw.markdown_sections import wave_complete
from tripll.skw.pipeline import PipelineBuilder

__all__: list[str] = ["compute_next_step"]

_ROLE_TO_TARGET = {
    "test-author": "test-creator-run",
    "impl": "wave-runner-run",
}


def _wave_path_arg(wave_path: Path, kit_root: Path) -> str:
    try:
        return str(wave_path.resolve().relative_to(kit_root.resolve()))
    except ValueError:
        return str(wave_path)


def _make_cmd(target: str, wave_arg: str, wave_id: str | None = None) -> str:
    parts = [f"make {target}", f"WAVE={wave_arg}"]
    if wave_id:
        parts.append(f"WAVE_ID={wave_id}")
    return " ".join(parts)


def _make_cmd_for_state(state: dict[str, Any], wave_arg: str) -> str:
    role = str(state.get("role", "impl"))
    target = _ROLE_TO_TARGET.get(role, "wave-runner-run")
    wave_id = str(state.get("id", ""))
    return _make_cmd(target, wave_arg, wave_id or None)


def _read_verdict(wave_path: Path, builder: PipelineBuilder) -> str | None:
    slug = builder.slug
    if not slug:
        return None
    candidates = [
        wave_path.parent / f"{slug}.review-result.json",
        builder.kit_root / "waves" / f"{slug}.review-result.json",
    ]
    for result_path in candidates:
        if not result_path.is_file():
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        verdict = payload.get("verdict")
        if isinstance(verdict, str):
            return verdict
    return None


def _all_impl_waves_complete(text: str, builder: PipelineBuilder) -> bool:
    for state in builder.states:
        if state.get("role") != "impl":
            continue
        wid = state.get("id")
        if isinstance(wid, str) and not wave_complete(text, wid):
            return False
    return True


def compute_next_step(
    *,
    wave_file: Path | str,
    kit_root: Path | str,
    wave_id: str | None = None,
    all_impl_complete: bool = False,
    verdict: str | None = None,
    plan_complete: bool = False,
) -> str:
    """Return the next manual ``make`` command for one wave-file.

    Args:
        wave_file (Path | str): Path to the wave markdown file.
        kit_root (Path | str): Kit root directory.
        wave_id (str | None): Wave id just completed (skip checkbox scan for next id).
        all_impl_complete (bool): All impl waves finished — suggest ``reviewer-run``.
        verdict (str | None): Review verdict override (``changes_required`` → generator).
        plan_complete (bool): Plan fully done — return ``PASS``.

    Returns:
        str: Next ``make …`` command or ``PASS``.

    Examples:
        >>> from pathlib import Path
        >>> root = Path("spec-kit-wave")
        >>> wave = root / "tests/fixtures/pipeline-three-wave.md"
        >>> hint = compute_next_step(wave_file=wave, kit_root=root)
        >>> "test-creator-run" in hint and "WAVE_ID=W1" in hint
        True
    """
    wave_path = Path(wave_file).resolve()
    root = Path(kit_root).resolve()
    builder = PipelineBuilder.from_wave_file(wave_path, root)
    wave_arg = _wave_path_arg(wave_path, root)

    if plan_complete:
        return "PASS"

    effective_verdict = verdict if verdict is not None else _read_verdict(wave_path, builder)
    if effective_verdict == "changes_required":
        return _make_cmd("post-review-wave-generator-run", wave_arg)

    if all_impl_complete:
        return _make_cmd("reviewer-run", wave_arg)

    order = [str(state["id"]) for state in builder.states if isinstance(state.get("id"), str)]
    text = wave_path.read_text(encoding="utf-8")

    if wave_id is not None:
        if wave_id not in order:
            msg = f"unknown wave id {wave_id!r}"
            raise ValueError(msg)
        idx = order.index(wave_id)
        if idx + 1 < len(order):
            next_state = builder.states[idx + 1]
            return _make_cmd_for_state(next_state, wave_arg)
        if _all_impl_waves_complete(text, builder):
            return _make_cmd("reviewer-run", wave_arg)
        return "PASS"

    for state in builder.states:
        wid = state.get("id")
        if not isinstance(wid, str):
            continue
        if not wave_complete(text, wid):
            return _make_cmd_for_state(state, wave_arg)

    if effective_verdict == "pass":
        return "PASS"
    return _make_cmd("reviewer-run", wave_arg)
