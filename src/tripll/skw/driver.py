"""Agent driver — render prompt then shell out via ``scripts/agent.sh`` (Wave W3).

W0 design lock (D1): LangGraph agent states render a stage prompt and dispatch
``cursor-agent`` / ``claude`` through the same argv contract as ``scripts/agent.sh``
— no LLM-in-Python coding agent. Honors ``SKW_AGENT_BIN``, ``SKW_DRYRUN``,
``SKW_MODEL``, ``SKW_PERMS``. Wave W4 wraps each dispatch in a Logfire span.

Exports:
    agent_for_role — map wave role → agent id.
    run_agent — render + subprocess driver with line streaming (W3).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from tripll.skw.agent_config import build_agent_argv, resolve_agent_params
from tripll.skw.logging import is_logging_active, log_debug, log_stream_line
from tripll.skw.render import render_prompt
from tripll.skw.resolve_wave import agent_for_role, load_wave_data, wave_role
from tripll.skw.runtime import is_dryrun, is_pytest
from tripll.skw.tracing import span

__all__: list[str] = ["AgentRunError", "agent_for_role", "run_agent"]


class AgentRunError(RuntimeError):
    """Agent subprocess returned a non-zero exit code."""

    def __init__(
        self,
        exit_code: int,
        *,
        stage: str = "",
        wave_id: str | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.stage = stage
        self.wave_id = wave_id
        detail = f"stage={stage}" if stage else "agent"
        if wave_id:
            detail = f"{detail} wave_id={wave_id}"
        super().__init__(f"agent exit {exit_code} ({detail})")


_STAGE_AGENTS = {
    "review": "reviewer",
    "generate": "post-review-wave-generator",
}


def _resolve_agent_name(
    *,
    stage: str,
    wave_data: dict[str, Any] | None,
    wave_id: str | None,
) -> str:
    if stage == "run" and wave_id and wave_data is not None:
        return agent_for_role(wave_role(wave_data, wave_id))
    return _STAGE_AGENTS.get(stage, stage)


def _resolve_role(*, stage: str, wave_data: dict[str, Any] | None, wave_id: str | None) -> str:
    if stage == "run" and wave_id and wave_data is not None:
        return wave_role(wave_data, wave_id)
    return stage


def _build_argv(
    prompt: str,
    *,
    workspace: str,
    kit_root: Path,
    stage: str,
    wave_data: dict[str, Any] | None,
    wave_id: str | None,
) -> list[str]:
    output_fmt = os.environ.get("SKW_OUTPUT_FMT", "stream-json")
    params = resolve_agent_params(
        kit_root=kit_root,
        stage=stage,
        wave_data=wave_data,
        wave_id=wave_id,
    )
    return build_agent_argv(
        params,
        workspace=workspace,
        output_fmt=output_fmt,
        prompt=prompt,
    )


def _print_dryrun(argv: list[str], label: str, prompt: str) -> None:
    """Print ``agent.sh``-compatible dry-run argv (no subprocess)."""
    basename = Path(label).name
    print(f"[dry-run] would exec ({basename}, prompt {len(prompt)} chars):")
    quoted = " ".join(shlex.quote(arg) for arg in argv[:-1])
    print(f"  {quoted} '<{basename} prompt, {len(prompt)} chars>'")


def _parse_tool_calls(lines: list[str]) -> list[dict[str, object]]:
    """Best-effort parse of tool-use events from cursor-agent stream lines."""
    calls: list[dict[str, object]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and any(
                key in payload for key in ("tool", "tool_name", "tool_call", "function_call")
            ):
                calls.append(payload)
            continue
        lowered = stripped.lower()
        if lowered.startswith("tool:") or lowered.startswith("[tool"):
            calls.append({"line": stripped})
    return calls


def _format_stream_line(raw: str) -> str | None:
    """Turn one ``stream-json`` event (or plain line) into a human-readable line.

    Returns ``None`` for noise events (system/user) so the live log stays readable.
    Falls back to the raw line when it is not JSON, so output is never swallowed.

    Args:
        raw (str): One line from the agent subprocess stdout.

    Returns:
        str | None: Display line, or ``None`` to skip.

    Examples:
        >>> _format_stream_line('{"type": "system"}') is None
        True
        >>> _format_stream_line("plain text")
        'plain text'
    """
    stripped = raw.strip()
    if not stripped:
        return None
    if not stripped.startswith("{"):
        return raw.rstrip("\r\n")
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return raw.rstrip("\r\n")
    if not isinstance(event, dict):
        return raw.rstrip("\r\n")

    etype = str(event.get("type", ""))
    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            texts = [
                c["text"]
                for c in content
                if isinstance(c, dict)
                and c.get("type") == "text"
                and isinstance(c.get("text"), str)
            ]
            joined = "".join(texts).strip()
            if joined:
                return joined
            tools = [
                f"[tool] {c.get('name', 'tool')}"
                for c in content
                if isinstance(c, dict) and c.get("type") == "tool_use"
            ]
            if tools:
                return "\n".join(tools)
    if etype in {"tool_use", "tool_call"}:
        return f"[tool] {event.get('name') or event.get('tool') or 'tool'}"
    if etype == "result":
        return f"[result] {event.get('subtype') or event.get('result') or 'done'}"
    if etype in {"text", "assistant_delta"} and isinstance(event.get("text"), str):
        return str(event["text"])
    if etype in {"system", "user"}:
        return None
    return f"· {etype}" if etype else None


def _stream_output(
    proc: subprocess.Popen[str], out: TextIO = sys.stdout
) -> tuple[int, str, list[str]]:
    assert proc.stdout is not None
    lines: list[str] = []
    for line in proc.stdout:
        lines.append(line)
        display = _format_stream_line(line)
        if display is None:
            continue
        if is_logging_active():
            log_stream_line(display)
        else:
            out.write(display + "\n")
            out.flush()
    return proc.wait(), "".join(lines), lines


def run_agent(
    *,
    wave_file: Path | str,
    kit_root: Path | str,
    stage: str = "run",
    wave_id: str | None = None,
) -> int:
    """Render one stage prompt and dispatch the headless agent CLI.

    Args:
        wave_file (Path | str): Active wave markdown file.
        kit_root (Path | str): Kit root directory.
        stage (str): ``run``, ``review``, or ``generate``.
        wave_id (str | None): Target wave id (required for ``run``).

    Returns:
        int: Subprocess exit code (0 on dry-run success).

    Examples:
        >>> run_agent(wave_file="w.md", kit_root=".", stage="run", wave_id="W0")  # doctest: +SKIP
        0
    """
    wave_path = Path(wave_file).resolve()
    root = Path(kit_root).resolve()

    if stage == "run" and not wave_id:
        msg = "wave_id is required for stage run"
        raise ValueError(msg)

    wave_data = load_wave_data(wave_path)

    prompt = render_prompt(wave_path, root, stage=stage, wave_id=wave_id)
    agent_name = _resolve_agent_name(stage=stage, wave_data=wave_data, wave_id=wave_id)
    role = _resolve_role(stage=stage, wave_data=wave_data, wave_id=wave_id)
    label = f"{agent_name}.md"

    span_name = f"driver.run_agent.{stage}"
    span_attrs: dict[str, object] = {
        "agent": agent_name,
        "stage": stage,
        "role": role,
        "prompt": prompt,
    }
    if wave_id:
        span_attrs["wave_id"] = wave_id

    with span(span_name, **span_attrs) as bag:
        if is_pytest() and not is_dryrun():
            bag["output"] = ""
            return 0

        workspace = os.environ.get("SKW_WORKSPACE") or str(root.parent)
        argv = _build_argv(
            prompt,
            workspace=workspace,
            kit_root=root,
            stage=stage,
            wave_data=wave_data,
            wave_id=wave_id,
        )
        bag["argv"] = argv

        if is_logging_active():
            log_debug(f"agent argv: {' '.join(shlex.quote(arg) for arg in argv[:-1])} '<prompt>'")
            log_debug(f"rendered prompt ({len(prompt)} chars):\n{prompt}")

        if is_dryrun():
            _print_dryrun(argv, label, prompt)
            bag["output"] = f"dry-run {label}"
            return 0

        start = time.perf_counter()
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        rc, output, raw_lines = _stream_output(proc)
        bag["output"] = output
        bag["duration_s"] = time.perf_counter() - start
        bag["exit_code"] = rc
        tool_calls = _parse_tool_calls(raw_lines)
        if tool_calls:
            bag["tool_calls"] = tool_calls
        if rc != 0:
            raise AgentRunError(rc, stage=stage, wave_id=wave_id)
        return rc
