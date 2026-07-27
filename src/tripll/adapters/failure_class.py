"""Classify dispatch outcomes as success, failure, or infra (PROV-03).

Exports:
    FailureClass — ``success`` | ``failure`` | ``infra``.
    classify_dispatch — map a :class:`~tripll.adapters.base.DispatchResult` to a class.
    is_auth_failure — detect mid-run auth/session failures (AUTH-01).
"""

from __future__ import annotations

import re
from typing import Literal

from tripll.adapters.base import DispatchResult  # noqa: TC001 — runtime parameter type

FailureClass = Literal["success", "failure", "infra"]

_INFRA_MARKERS = (
    "Couldn't start",
    "Workspace Disconnected",
)

# Word-boundary patterns avoid classifying agent output that merely mentions auth tokens.
_AUTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnot authenticated\b", re.IGNORECASE),
    re.compile(r"\bauthentication required\b", re.IGNORECASE),
    re.compile(r"\bauth required\b", re.IGNORECASE),
    re.compile(r"\blogin required\b", re.IGNORECASE),
    re.compile(r"\bplease log in\b", re.IGNORECASE),
    re.compile(r"\bsign in\b", re.IGNORECASE),
    re.compile(r"\bapi key\b", re.IGNORECASE),
    re.compile(r"\bunauthorized\b", re.IGNORECASE),
    re.compile(r"\b401\b"),
)


def _has_agent_output(output: str) -> bool:
    """Return True when *output* contains structured agent result text."""
    stripped = output.strip()
    if not stripped:
        return False
    for line in stripped.splitlines():
        text = line.strip()
        if text.startswith("{") and '"type":"result"' in text.replace(" ", ""):
            return True
        if text.startswith("{") and '"type": "result"' in text:
            return True
    # Non-JSON backends may still emit a substantive tail on success paths.
    return len(stripped) > 80


def is_auth_failure(text: str) -> bool:
    """Return True when *text* looks like an interactive auth/session failure.

    Args:
        text (str): Dispatch log tail or result text.

    Returns:
        bool: True for auth-related failures that should park as ``infra``.

    Examples:
        >>> is_auth_failure("Error: not authenticated — run claude login")
        True
    """
    return any(pattern.search(text) for pattern in _AUTH_PATTERNS)


def classify_dispatch(result: DispatchResult, *, output: str = "") -> FailureClass:
    """Classify a dispatch outcome for retry and breaker policy.

    ``infra`` matches extension-host crashes, workspace disconnects, auth hangs,
    and non-zero exits with empty agent output. Infra outcomes do **not** consume
    a wave attempt and do **not** trip the exit-7 breaker.

    Args:
        result (DispatchResult): Parsed adapter outcome.
        output (str): Raw combined output when distinct from ``result.result_text``.

    Returns:
        FailureClass: ``success``, ``failure``, or ``infra``.

    Examples:
        >>> classify_dispatch(
        ...     DispatchResult(outcome="failed", result_text="Couldn't start", returncode=1)
        ... )
        'infra'
        >>> classify_dispatch(DispatchResult(outcome="done", returncode=0))
        'success'
    """
    if result.outcome == "done":
        return "success"
    if result.outcome == "quota_exhausted":
        return "failure"

    text = result.result_text or output
    if any(marker in text for marker in _INFRA_MARKERS):
        return "infra"
    if is_auth_failure(text):
        return "infra"
    if result.returncode not in (None, 0) and not _has_agent_output(output or text):
        return "infra"
    return "failure"
