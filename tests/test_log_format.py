"""Tests for tripll.log_format."""

from __future__ import annotations

from io import StringIO

from tripll.log_format import (
    format_terminal_summary,
    stamp_log_line,
    write_attempt_log_header,
)


def test_stamp_log_line_adds_timestamp() -> None:
    line = stamp_log_line("hello\n")
    assert line.startswith("[")
    assert "] hello" in line


def test_write_attempt_log_header() -> None:
    buf = StringIO()
    write_attempt_log_header(
        buf,
        run_id="r1",
        node_id="p:W0",
        attempt=2,
        backend="cursor_local",
        argv=["agent", "--print", "go"],
    )
    text = buf.getvalue()
    assert "ATTEMPT START" in text
    assert "node_id=p:W0" in text
    assert "attempt=2" in text


def test_format_terminal_summary() -> None:
    assert "agent finished" in format_terminal_summary("  ✓ agent finished")
