"""Shared pytest helpers for the code factory L1 RED suite."""

from __future__ import annotations

import importlib
from typing import Any

import pytest


def require_module(module: str, *, attr: str | None = None) -> Any:
    """Import a not-yet-implemented module; fail the test (xfail-guarded) if absent."""
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(f"{module} not implemented: {exc}")
    if attr is not None:
        return getattr(mod, attr)
    return mod
