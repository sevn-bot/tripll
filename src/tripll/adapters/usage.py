"""tripll.adapters.usage — parse token/cost fields from stream-json output.

Exports:
    StreamUsage — token and cost totals from a stream-json session.
    parse_stream_usage — extract usage from the last ``result`` event in output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamUsage:
    """Token and cost totals from a stream-json session."""

    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def _json_line_from_log_line(line: str) -> dict[str, object] | None:
    """Parse one NDJSON line or a timestamp-prefixed attempt-log line.

    Args:
        line (str): One line from stream-json or a stamped attempt log.

    Returns:
        dict[str, object] | None: Parsed JSON object, or None when not JSON.

    Examples:
        >>> _json_line_from_log_line('{"type":"result"}') == {"type": "result"}
        True
        >>> _json_line_from_log_line("not json") is None
        True
    """
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("["):
        close = stripped.find("] ")
        if close != -1:
            rest = stripped[close + 2 :].strip()
            if rest.startswith("{"):
                stripped = rest
    if not stripped.startswith("{"):
        return None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _int_field(data: dict[str, object], *keys: str) -> int | None:
    """Return the first integer-valued *keys* entry from *data*, or None."""
    for key in keys:
        val = data.get(key)
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, float) and val.is_integer():
            return int(val)
    return None


def _cost_from_event(event: dict[str, object]) -> float | None:
    """Extract USD cost from a stream-json ``result`` event when present."""
    for key in ("cost_usd", "total_cost_usd", "costUsd", "totalCostUsd"):
        raw = event.get(key)
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _usage_from_event(event: dict[str, object]) -> tuple[int | None, int | None]:
    """Return ``(input_tokens, output_tokens)`` from a ``result`` event's ``usage`` block."""
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None, None
    inp = _int_field(
        usage,
        "input_tokens",
        "inputTokens",
        "prompt_tokens",
        "promptTokens",
    )
    out_tok = _int_field(
        usage,
        "output_tokens",
        "outputTokens",
        "completion_tokens",
        "completionTokens",
    )
    return inp, out_tok


def parse_stream_usage(output: str) -> StreamUsage:
    """Extract usage from the last ``result`` event in *output*.

    Supports Claude Code ``stream-json`` (``cost_usd``, ``usage.input_tokens``)
    and Cursor ``agent`` CLI output (``usage.inputTokens`` / ``outputTokens``,
    optional ``total_cost_usd``).  Attempt log lines prefixed with
    ``[YYYY-MM-DD HH:MM:SS]`` are accepted.

    Args:
        output (str): Combined stream-json stdout or stamped attempt log text.

    Returns:
        StreamUsage: Parsed cost/token fields (may be empty).

    Examples:
        >>> u = parse_stream_usage(
        ...     '{"type":"result","cost_usd":0.12,"usage":{"input_tokens":1,"output_tokens":2}}'
        ... )
        >>> u.cost_usd == 0.12 and u.input_tokens == 1
        True
        >>> c = parse_stream_usage(
        ...     '{"type":"result","usage":{"inputTokens":10,"outputTokens":3}}'
        ... )
        >>> c.input_tokens == 10 and c.output_tokens == 3
        True
    """
    cost: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    for line in output.splitlines():
        event = _json_line_from_log_line(line)
        if event is None or event.get("type") != "result":
            continue
        raw_cost = _cost_from_event(event)
        if raw_cost is not None:
            cost = raw_cost
        inp, out_tok = _usage_from_event(event)
        if inp is not None:
            input_tokens = inp
        if out_tok is not None:
            output_tokens = out_tok
    return StreamUsage(cost_usd=cost, input_tokens=input_tokens, output_tokens=output_tokens)
