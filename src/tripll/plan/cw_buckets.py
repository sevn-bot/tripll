"""Coordination-wave hotspot defaults (W8 repo portability, R9)."""

from __future__ import annotations


def default_cw_hotspots() -> dict[str, list[str]]:
    """Return the default coordination-wave hotspot map.

    Production defaults are empty so foreign target repos do not inherit
    sevn-shaped forbidden paths. Legacy sevn buckets live in
    ``tests/fixtures/legacy_cw_buckets.py`` for corpus replay only.

    Returns:
        dict[str, list[str]]: Empty hotspot map unless configured elsewhere.

    Examples:
        >>> default_cw_hotspots()
        {}
    """
    return {}
