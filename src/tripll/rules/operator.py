"""Operator-only gate for rule lifecycle commands (R27).

Exports:
    require_operator — refuse promote/retire unless ``TRIPLL_OPERATOR`` is set.
"""

from __future__ import annotations

import os

__all__ = ["require_operator"]

_OPERATOR_TRUTHY = frozenset({"1", "true", "yes", "on"})


def require_operator(action: str) -> None:
    """Refuse rule lifecycle mutations unless the operator env is set (R27).

    Args:
        action (str): Human-readable action label for error messages.

    Raises:
        PermissionError: When ``TRIPLL_OPERATOR`` is not truthy.
    """
    raw = os.environ.get("TRIPLL_OPERATOR", "").strip().lower()
    if raw not in _OPERATOR_TRUTHY:
        msg = f"{action} requires TRIPLL_OPERATOR=1 — agents must not activate rules (R27)"
        raise PermissionError(msg)
