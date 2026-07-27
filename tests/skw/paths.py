"""Shared path constants for the skw test suite."""

from __future__ import annotations

from pathlib import Path

_TESTS_SKW = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_SKW.parent.parent
KIT_ROOT = _REPO_ROOT / "src" / "tripll" / "skw"
FIXTURES = _TESTS_SKW / "fixtures"
REPO_ROOT = _REPO_ROOT
