"""Tests for tripll.adapters.quota — session/quota detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tripll.adapters.base import run_streaming
from tripll.adapters.claude_code import ClaudeCodeAdapter
from tripll.adapters.quota import is_quota_exhausted, quota_message, stream_quota_pause


def test_is_quota_exhausted_session_limit() -> None:
    assert is_quota_exhausted("You've hit your session limit · resets 1:30am")


def test_is_quota_exhausted_make_lint_not_quota() -> None:
    assert not is_quota_exhausted("make lint failed: ruff error in src/foo.py")


def test_quota_message_first_line() -> None:
    assert "session limit" in quota_message("You've hit your session limit · resets 1:30am")


def test_claude_parse_result_quota_exhausted() -> None:
    out = (
        '{"type":"result","is_error":true,'
        '"result":"You\'ve hit your session limit · resets 1:30am"}\n'
    )
    r = ClaudeCodeAdapter().parse_result(1, out)
    assert r.outcome == "quota_exhausted"


def test_stream_quota_pause_at_99() -> None:
    line = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed_warning",
                "utilization": 0.99,
                "rateLimitType": "five_hour",
            },
        }
    )
    reason = stream_quota_pause(line)
    assert reason is not None
    assert "99%" in reason


def test_stream_quota_pause_rejected() -> None:
    line = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"},
        }
    )
    assert stream_quota_pause(line) == "rate limit rejected (five_hour)"


def test_stream_quota_pause_below_threshold() -> None:
    line = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed_warning", "utilization": 0.97},
        }
    )
    assert stream_quota_pause(line) is None


async def test_run_streaming_stops_at_utilization(tmp_path: Path) -> None:
    event = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed_warning", "utilization": 0.99},
        }
    )
    script = (
        f'import sys, time\nprint({event!r})\nsys.stdout.flush()\ntime.sleep(30)\nprint("late")\n'
    )
    rc, out, quota = await run_streaming(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        log_path=tmp_path / "q.log",
        timeout_s=60,
    )
    assert quota is not None
    assert "99%" in quota
    assert "late" not in out
    assert rc is not None
