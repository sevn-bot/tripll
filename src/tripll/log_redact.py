"""tripll.log_redact — redact sensitive keys from attempt log text for the GUI.

Loads the operator hide-list from ``config/log-hide-keys.toml`` and strips
matching JSON keys (at any nesting depth) from log lines before the control
plane serves them.

Exports:
    LOG_HIDE_KEYS_PATH — default TOML path under the wave-orchestrator package root.
    load_hide_keys — parse hide_keys from the TOML file.
    redact_json_value — recursively remove configured keys from a parsed object.
    redact_log_line — redact one log line (JSON or plain text).
    redact_log_text — redact a multi-line log fragment.
    validate_hide_keys_config — gate helper; raises when config is invalid/empty.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

LOG_HIDE_KEYS_PATH = Path(__file__).resolve().parents[2] / "config" / "log-hide-keys.toml"
_REDACTED = "[redacted]"


def load_hide_keys(path: Path | None = None) -> frozenset[str]:
    """Load JSON key names to hide from the operator TOML config.

    Args:
        path (Path | None): Override config path (default :data:`LOG_HIDE_KEYS_PATH`).

    Returns:
        frozenset[str]: Key names to strip from parsed JSON log objects.

    Raises:
        FileNotFoundError: When the config file is missing.
        ValueError: When ``hide_keys`` is absent or not a list.

    Examples:
        >>> keys = load_hide_keys(LOG_HIDE_KEYS_PATH)
        >>> "signature" in keys
        True
    """
    cfg_path = path or LOG_HIDE_KEYS_PATH
    with cfg_path.open("rb") as handle:
        data = tomllib.load(handle)
    hide_keys_raw = data.get("hide_keys")
    if not isinstance(hide_keys_raw, list) or not hide_keys_raw:
        raise ValueError(f"hide_keys missing or empty in {cfg_path}")
    return frozenset(str(key) for key in hide_keys_raw)


def validate_hide_keys_config(path: Path | None = None) -> frozenset[str]:
    """Validate the hide-keys config (CI/operator gate).

    Args:
        path (Path | None): Override config path.

    Returns:
        frozenset[str]: Loaded hide key names.

    Raises:
        FileNotFoundError: When the config file is missing.
        ValueError: When ``hide_keys`` is invalid.

    Examples:
        >>> validate_hide_keys_config()  # doctest: +SKIP
        frozenset({'signature'})
    """
    keys = load_hide_keys(path)
    if "signature" not in keys:
        raise ValueError("log-hide-keys.toml must include 'signature'")
    return keys


def redact_json_value(value: Any, hide_keys: frozenset[str]) -> Any:
    """Recursively remove *hide_keys* from dict/list JSON structures.

    Args:
        value (Any): Parsed JSON value.
        hide_keys (frozenset[str]): Key names to remove.

    Returns:
        Any: Copy with hidden keys replaced by ``[redacted]`` (scalars) or removed.

    Examples:
        >>> redact_json_value({"signature": "abc", "type": "thinking"}, frozenset({"signature"}))
        {'type': 'thinking', 'signature': '[redacted]'}
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in hide_keys:
                out[key] = _REDACTED
            else:
                out[key] = redact_json_value(item, hide_keys)
        return out
    if isinstance(value, list):
        return [redact_json_value(item, hide_keys) for item in value]
    return value


def _redact_env_shaped_line(line: str, hide_keys: frozenset[str]) -> str | None:
    """Redact ``KEY=value`` / ``KEY: value`` lines when *KEY* matches a hide key."""
    match = re.match(r"^(\s*)([A-Za-z0-9_.-]+)(\s*[=:]\s*)(.*)$", line)
    if not match:
        return None
    prefix_ws, key, sep, _value = match.groups()
    key_lower = key.lower()
    if not any(hk.lower() in key_lower for hk in hide_keys):
        return None
    return f"{prefix_ws}{key}{sep}{_REDACTED}"


def redact_log_line(line: str, hide_keys: frozenset[str] | None = None) -> str:
    """Redact configured keys from one log line when it is JSON.

    Also redacts env-shaped ``KEY=value`` / ``KEY: value`` lines when the key
    name contains a configured hide key (case-insensitive).

    Args:
        line (str): Raw log line (may include a timestamp prefix).
        hide_keys (frozenset[str] | None): Keys to hide; loads default config when ``None``.

    Returns:
        str: Redacted line (unchanged when not JSON or when redaction fails).

    Examples:
        >>> redact_log_line(
        ...     '{"type":"thinking","signature":"EtUOCmMIDhgCKkDeYY"}',
        ...     frozenset({"signature"}),
        ... )
        '{"type": "thinking", "signature": "[redacted]"}'
    """
    keys = hide_keys if hide_keys is not None else load_hide_keys()
    env_redacted = _redact_env_shaped_line(line, keys)
    if env_redacted is not None:
        return env_redacted
    prefix = ""
    payload = line
    match = re.match(r"^(\[[^\]]+\]\s*)(\{.*\})\s*$", line)
    if match:
        prefix = match.group(1)
        payload = match.group(2)
    trimmed = payload.strip()
    if not trimmed.startswith("{"):
        return line
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError:
        return line
    redacted = redact_json_value(parsed, keys)
    return prefix + json.dumps(redacted, ensure_ascii=False)


def redact_log_text(text: str, hide_keys: frozenset[str] | None = None) -> str:
    """Redact configured keys from every line in a log fragment.

    Args:
        text (str): Multi-line log text.
        hide_keys (frozenset[str] | None): Keys to hide; loads default config when ``None``.

    Returns:
        str: Redacted log text.

    Examples:
        >>> redact_log_text('{"signature":"x"}\\nplain', frozenset({"signature"}))
        '{"signature": "[redacted]"}\\nplain'
    """
    if not text:
        return text
    keys = hide_keys if hide_keys is not None else load_hide_keys()
    lines = text.split("\n")
    return "\n".join(redact_log_line(line, keys) for line in lines)
