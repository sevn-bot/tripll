"""tripll.adapters.quota — detect provider quota / session-limit failures.

When a backend reports session or usage limits, the engine pauses the run
immediately (no retry burn) so the operator can switch provider/model and
resume later.

Exports:
    is_quota_exhausted — True when *text* looks like a hard quota/session cap.
    stream_quota_pause — pause reason from one stream-json line, or None.
    quota_message — extract a short operator-facing message from *text*.
"""

from __future__ import annotations

import json
import os
import re

_QUOTA_PATTERNS = (
    re.compile(r"session limit", re.I),
    re.compile(r"usage limit", re.I),
    re.compile(r"rate limit", re.I),
    re.compile(r"out of credits", re.I),
    re.compile(r"quota exceeded", re.I),
    re.compile(r"too many requests", re.I),
    re.compile(r"capacity exceeded", re.I),
)

DEFAULT_UTILIZATION_THRESHOLD = 0.99
_BLOCKED_STATUSES = frozenset({"denied", "rejected", "blocked"})


def _utilization_threshold() -> float:
    """Read ``TRIPLL_QUOTA_UTIL_THRESHOLD`` or return :data:`DEFAULT_UTILIZATION_THRESHOLD`.

    Returns:
        float: Utilization fraction (0-1) at which to pause proactively.

    Examples:
        >>> _utilization_threshold() == DEFAULT_UTILIZATION_THRESHOLD
        True
    """
    raw = os.environ.get("TRIPLL_QUOTA_UTIL_THRESHOLD", "")
    if not raw:
        return DEFAULT_UTILIZATION_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_UTILIZATION_THRESHOLD


def stream_quota_pause(line: str, *, threshold: float | None = None) -> str | None:
    """Return a pause reason when *line* signals quota exhaustion during streaming.

    Proactively stops at ``utilization >= threshold`` (default 99%) on Claude
    ``rate_limit_event`` lines so the run pauses before the hard cap burns retries.

    Args:
        line (str): One stream-json line from the backend.
        threshold (float | None): Utilization fraction to pause at (default 0.99).

    Returns:
        str | None: Operator-facing pause reason, or None to keep running.

    Examples:
        >>> line = '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning","utilization":0.99,"rateLimitType":"five_hour"}}'
        >>> "99%" in (stream_quota_pause(line) or "")
        True
    """
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "rate_limit_event":
        return None
    info = event.get("rate_limit_info") or {}
    status = str(info.get("status", "")).lower()
    limit_type = str(info.get("rateLimitType") or "session")
    if status in _BLOCKED_STATUSES:
        return f"rate limit {status} ({limit_type})"
    util = info.get("utilization")
    cap = threshold if threshold is not None else _utilization_threshold()
    if isinstance(util, (int, float)) and float(util) >= cap:
        pct = round(float(util) * 100)
        cap_pct = round(cap * 100)
        return (
            f"session utilization {pct}% (threshold {cap_pct}%) — "
            f"pausing before hard cap ({limit_type})"
        )
    return None


def is_quota_exhausted(text: str) -> bool:
    """Return True when *text* indicates the provider quota/session cap was hit.

    Args:
        text (str): Dispatch result or log excerpt.

    Returns:
        bool: True when the operator should pause and switch provider/model.

    Examples:
        >>> is_quota_exhausted("You've hit your session limit · resets 1:30am")
        True
        >>> is_quota_exhausted("make lint failed: ruff error")
        False
    """
    if not text.strip():
        return False
    return any(p.search(text) for p in _QUOTA_PATTERNS)


def quota_message(text: str) -> str:
    """Return a one-line operator message from quota-related *text*.

    Args:
        text (str): Raw provider message.

    Returns:
        str: Trimmed message for ``quota-paused.md``.

    Examples:
        >>> quota_message("You've hit your session limit")
        "You've hit your session limit"
    """
    line = text.strip().splitlines()[0] if text.strip() else "provider quota exhausted"
    return line[:500]
