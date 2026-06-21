"""Tests for tripll.log_redact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripll.log_redact import (
    LOG_HIDE_KEYS_PATH,
    load_hide_keys,
    redact_json_value,
    redact_log_line,
    redact_log_text,
    validate_hide_keys_config,
)


def test_load_hide_keys_includes_signature() -> None:
    keys = load_hide_keys(LOG_HIDE_KEYS_PATH)
    assert "signature" in keys


def test_validate_hide_keys_config_gate() -> None:
    keys = validate_hide_keys_config()
    assert "signature" in keys


def test_validate_hide_keys_config_rejects_missing_signature(tmp_path: Path) -> None:
    bad = tmp_path / "log-hide-keys.toml"
    bad.write_text('hide_keys = ["token"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="signature"):
        validate_hide_keys_config(bad)


def test_redact_json_value_replaces_signature() -> None:
    keys = frozenset({"signature"})
    out = redact_json_value({"type": "thinking", "signature": "EtUOCmMIDhgCKkDeYY"}, keys)
    assert out["signature"] == "[redacted]"
    assert out["type"] == "thinking"


def test_redact_log_line_json() -> None:
    line = '{"type":"thinking","signature":"EtUOCmMIDhgCKkDeYY"}'
    out = redact_log_line(line, frozenset({"signature"}))
    parsed = json.loads(out)
    assert parsed["signature"] == "[redacted]"


def test_redact_log_line_with_timestamp_prefix() -> None:
    line = '[2026-06-19 17:22:43] {"signature":"secret"}'
    out = redact_log_line(line, frozenset({"signature"}))
    assert out.startswith("[2026-06-19")
    assert '"[redacted]"' in out


def test_redact_log_text_multiline() -> None:
    text = '{"signature":"x"}\nplain line\n'
    out = redact_log_text(text, frozenset({"signature"}))
    assert '"[redacted]"' in out
    assert "plain line" in out
