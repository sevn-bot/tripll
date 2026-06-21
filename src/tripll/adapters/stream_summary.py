"""tripll.adapters.stream_summary — one-line summaries for Claude stream-json.

Full stream-json is always written to the attempt log file; this module picks
operator-relevant lines for terminal display (session start, subagents, errors,
completion).

Exports:
    summarize_stream_line — map one JSONL line to a terminal line or None.
"""

from __future__ import annotations

import json

_ERROR_HINTS = (
    "traversal",
    "error:",
    "error ",
    "failed",
    "denied",
    "not found",
    "fatal:",
    "enoent",
    "permission denied",
    "command not found",
)


def _tool_input_summary(name: str, inp: dict[str, object]) -> str | None:
    """Return a one-line summary for a tool-use block, or None when not summarisable."""
    if name == "Task":
        sub = str(inp.get("subagent_type") or "?")
        desc = str(inp.get("description") or "")[:72]
        return f"  → subagent {sub}: {desc}"
    return None


def _tool_result_error(content: object) -> str | None:
    """Return a warning line when tool result *content* looks like an error."""
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    low = text.lower()
    if not any(h in low for h in _ERROR_HINTS):
        return None
    # Skip benign docstring mentions (e.g. "processed/ | failed/").
    if "traversal" in low or "error:" in low or "fatal:" in low or "denied" in low:
        snippet = text.replace("\n", " ").strip()[:220]
        return f"  ⚠ {snippet}"
    if low.count("failed") == 1 and "processed/" in low and "failed/" in low:
        return None
    snippet = text.replace("\n", " ").strip()[:220]
    return f"  ⚠ {snippet}"


def summarize_stream_line(line: str) -> str | None:
    """Return a one-line terminal summary for a stream-json *line*, or None to skip.

    Args:
        line (str): One line of Claude ``stream-json`` output.

    Returns:
        str | None: Human-readable summary, or None when the line is noise.

    Examples:
        >>> summarize_stream_line('{"type":"system","subtype":"init","model":"x","cwd":"/wt"}')
        '  agent session started (model=x, cwd=/wt)'
    """
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    kind = event.get("type")
    if kind == "system":
        if event.get("subtype") == "init":
            model = event.get("model") or "?"
            cwd = event.get("cwd") or "?"
            return f"  agent session started (model={model}, cwd={cwd})"
        return None

    if kind == "assistant":
        msg = event.get("message") or {}
        text_bits: list[str] = []
        summaries: list[str] = []
        for block in msg.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                snippet = str(block.get("text") or "").strip().replace("\n", " ")
                if snippet:
                    text_bits.append(snippet[:160])
            if btype != "tool_use":
                continue
            summary = _tool_input_summary(str(block.get("name") or "?"), block.get("input") or {})
            if summary:
                summaries.append(summary)
        if text_bits and not summaries:
            preview = text_bits[0]
            if len(preview) > 80:
                return f"  Thought: {preview[:120]}…"
            return f"  {preview}"
        if len(summaries) == 1:
            return summaries[0]
        if summaries:
            return summaries[0]
        return None

    if kind == "user":
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_result":
                continue
            err = _tool_result_error(block.get("content"))
            if err:
                return err
        return None

    if kind == "result":
        if event.get("is_error"):
            text = str(event.get("result") or event.get("error") or "unknown error")[:300]
            return f"  ✗ agent failed: {text}"
        return "  ✓ agent finished"

    if kind == "rate_limit_event":
        info = event.get("rate_limit_info") or {}
        status = str(info.get("status", "")).lower()
        if status in {"denied", "rejected", "blocked"}:
            return f"  ⚠ rate limit {status} — pausing recommended"
        util = info.get("utilization")
        if isinstance(util, (int, float)) and float(util) >= 0.9:
            pct = round(float(util) * 100)
            return f"  ⚠ session utilization {pct}% ({info.get('rateLimitType', 'session')})"
        reason = info.get("overageDisabledReason")
        if reason:
            return f"  ⚠ rate limit note: overage {reason} (status={info.get('status')})"
        return None

    return None
