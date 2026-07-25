"""Fixtures for spec-kit-wave RED tests.

Exports:
    repo_root — minimal repository tree fixture for interface resolution.

Examples:
    >>> import inspect
    >>> import conftest
    >>> inspect.isfunction(conftest.repo_root)
    True
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.skw.paths import KIT_ROOT


@pytest.fixture
def kit_root() -> Path:
    """Return the spec-kit-wave package root for render tests."""
    return KIT_ROOT


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Minimal repo tree with one Python module for interface resolution.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Returns:
        Path: Synthetic repository root with ``src/sevn/gateway/agent_turn.py``.

    Examples:
        >>> repo_root.__name__
        'repo_root'
    """
    root = tmp_path / "repo"
    root.mkdir()
    module_dir = root / "src" / "sevn" / "gateway"
    module_dir.mkdir(parents=True)
    (module_dir / "agent_turn.py").write_text(
        "def run_turn() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (root / "Makefile").write_text("ci:\n\ttrue\n", encoding="utf-8")
    return root
