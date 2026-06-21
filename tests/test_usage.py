"""Tests for tripll.adapters.usage."""

from __future__ import annotations

from tripll.adapters.usage import parse_stream_usage


def test_parse_stream_usage_from_claude_result_event() -> None:
    out = (
        '{"type":"assistant","message":{}}\n'
        '{"type":"result","cost_usd":1.5,"usage":{"input_tokens":100,"output_tokens":40}}\n'
    )
    usage = parse_stream_usage(out)
    assert usage.cost_usd == 1.5
    assert usage.input_tokens == 100
    assert usage.output_tokens == 40


def test_parse_stream_usage_from_cursor_result_event() -> None:
    """Cursor agent CLI uses camelCase usage keys on the terminal result event."""
    out = (
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"OK"}]}}\n'
        '{"type":"result","subtype":"success","duration_ms":8233,"is_error":false,'
        '"result":"OK","usage":{"inputTokens":26553,"outputTokens":33,'
        '"cacheReadTokens":5280,"cacheWriteTokens":0}}\n'
    )
    usage = parse_stream_usage(out)
    assert usage.cost_usd is None
    assert usage.input_tokens == 26553
    assert usage.output_tokens == 33


def test_parse_stream_usage_from_stamped_attempt_log_line() -> None:
    line = (
        '[2026-06-18 18:11:25] {"type":"result","usage":{"inputTokens":1200,"outputTokens":45}}\n'
    )
    usage = parse_stream_usage(line)
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 45


def test_parse_stream_usage_cursor_snake_case_variant() -> None:
    out = (
        '{"type":"result","total_cost_usd":0.42,'
        '"usage":{"input_tokens":500,"output_tokens":180,"cached_input_tokens":80}}\n'
    )
    usage = parse_stream_usage(out)
    assert usage.cost_usd == 0.42
    assert usage.input_tokens == 500
    assert usage.output_tokens == 180


def test_parse_stream_usage_uses_last_result_event() -> None:
    out = (
        '{"type":"result","usage":{"inputTokens":1,"outputTokens":1}}\n'
        '{"type":"result","usage":{"inputTokens":99,"outputTokens":7}}\n'
    )
    usage = parse_stream_usage(out)
    assert usage.input_tokens == 99
    assert usage.output_tokens == 7
