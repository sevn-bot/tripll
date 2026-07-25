"""Path helpers for the absorbed spec-kit-wave kit."""

from __future__ import annotations

from pathlib import Path


def kit_root() -> Path:
    """Return the bundled skw kit directory (``src/tripll/skw``)."""
    return Path(__file__).resolve().parent


def repo_root_for_kit(_kit_root: Path | None = None) -> Path:
    """Return the target git repository root for doc and render paths."""
    from tripll.repo_root import resolve_repo_root

    return resolve_repo_root()
