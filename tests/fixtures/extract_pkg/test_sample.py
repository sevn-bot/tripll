"""Coverage fixture for COVERS edges."""

from __future__ import annotations

from sample import helper


def test_helper() -> None:
    assert helper() == 1
