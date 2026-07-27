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


@pytest.fixture(autouse=True)
def _pr_dry_run_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real gh/git mutations unless a test clears TRIPLL_PR_DRY_RUN."""
    monkeypatch.setenv("TRIPLL_PR_DRY_RUN", "1")


@pytest.fixture
def legacy_cw_hotspots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in sevn CW buckets for tests that assert legacy hotspot behaviour (R9)."""
    from tests.fixtures.legacy_cw_buckets import LEGACY_CW_BUCKETS

    monkeypatch.setattr("tripll.graph.CW_HOTSPOTS", LEGACY_CW_BUCKETS)
    monkeypatch.setattr(
        "tripll.graph.ALL_CW_PATHS",
        [p for paths in LEGACY_CW_BUCKETS.values() for p in paths],
    )
