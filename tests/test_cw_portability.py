"""Coordination-wave portability — ARCH-CW, R9 (W1.11)."""

from __future__ import annotations

import pytest

from tests.fixtures.legacy_cw_buckets import LEGACY_CW_BUCKETS
from tripll.graph import CW_HOTSPOTS, Lane, derive_forbidden_paths
from tripll.plan.cw_buckets import default_cw_hotspots


@pytest.mark.tier1
def test_default_hotspots_empty_without_config() -> None:
    hotspots = default_cw_hotspots()
    assert hotspots == {}


@pytest.mark.tier1
def test_non_sevn_plan_has_no_sevn_forbidden_paths() -> None:
    lanes = {
        "core": Lane("core", owned_paths=["src/myapp/"]),
        "ui": Lane("ui", owned_paths=["src/myapp/ui/"]),
    }
    forbidden = derive_forbidden_paths("core", lanes)
    sevn_paths = [p for p in forbidden if "sevn" in p.lower()]
    assert sevn_paths == []


@pytest.mark.tier1
def test_legacy_buckets_reproduce_via_opt_in_fixture() -> None:
    """R9: legacy sevn buckets remain available for corpus replay."""
    assert "CW-1" in LEGACY_CW_BUCKETS
    assert any("sevn" in p for paths in LEGACY_CW_BUCKETS.values() for p in paths)


@pytest.mark.tier1
def test_cw_hotspots_module_default_empty() -> None:
    assert CW_HOTSPOTS == {}
