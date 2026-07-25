"""Runtime environment guards for skw pipeline execution.

Exports:
    is_pytest — detect pytest collection or test execution.
    is_dryrun — ``SKW_DRYRUN=1`` argv-only mode.
    is_auto_approve — ``SKW_AUTO_APPROVE=1`` review-gate bypass.
"""

from __future__ import annotations

import os

__all__: list[str] = ["is_auto_approve", "is_dryrun", "is_pytest"]


def is_pytest() -> bool:
    """Return True when running under pytest.

    Returns:
        bool: True when ``PYTEST_CURRENT_TEST`` is set.

    Examples:
        >>> is_pytest()  # doctest: +SKIP
        False
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def is_dryrun() -> bool:
    """Return True when dry-run mode is enabled.

    Returns:
        bool: True when ``SKW_DRYRUN=1``.

    Examples:
        >>> is_dryrun()  # doctest: +SKIP
        False
    """
    return os.environ.get("SKW_DRYRUN") == "1"


def is_auto_approve() -> bool:
    """Return True when review gates should auto-approve.

    Returns:
        bool: True when ``SKW_AUTO_APPROVE=1``.

    Examples:
        >>> is_auto_approve()  # doctest: +SKIP
        False
    """
    return os.environ.get("SKW_AUTO_APPROVE") == "1"
