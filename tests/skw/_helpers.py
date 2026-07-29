"""Shared contract constants and import helpers for skw tests.

Exports:
    require_module — import helper that fails tests when implementation is pending.

Examples:
    >>> from tests.skw._helpers import SCORE_THRESHOLD
    >>> SCORE_THRESHOLD
    80
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

SPEC_REQUIRED_SECTIONS: tuple[str, ...] = (
    "Purpose",
    "Public Interface",
    "Data Model",
    "Internal Architecture",
    "Behavior",
    "Failure Modes",
    "Test Strategy",
)

SPEC_STATUS_ENUM: frozenset[str] = frozenset({"draft", "scaffold", "done", "rejected"})

SCORE_COMPONENTS: tuple[str, ...] = (
    "frontmatter_completeness",
    "required_sections",
    "no_scaffold_phrase",
    "status_honesty",
    "interfaces_sources_resolve",
    "link_id_hygiene",
)

SCORE_THRESHOLD = 80


def require_module(name: str) -> Any:
    """Import ``name`` or fail the running test when implementation is pending.

    Args:
        name (str): Dotted module name (for example ``"skw.doc_score"``).

    Returns:
        Any: Imported module object.

    Examples:
        >>> mod = require_module("tripll.skw.doc_score")
        >>> mod.SCORE_THRESHOLD
        80
    """
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        pytest.fail(f"Module {name!r} not available (impl pending): {exc}")
