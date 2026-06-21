"""Tests for tripll.repo_root."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from tripll.repo_root import resolve_repo_root


def test_resolve_repo_root_from_env() -> None:
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "checkout"
        fake.mkdir()
        prev = os.environ.get("TRIPLL_REPO_ROOT")
        os.environ["TRIPLL_REPO_ROOT"] = str(fake)
        try:
            assert resolve_repo_root() == fake.resolve()
        finally:
            if prev is None:
                os.environ.pop("TRIPLL_REPO_ROOT", None)
            else:
                os.environ["TRIPLL_REPO_ROOT"] = prev


def test_resolve_repo_root_walks_up_to_git() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "repo"
        nested = root / "wave-orchestrator"
        nested.mkdir(parents=True)
        (root / ".git").mkdir()
        prev = os.environ.pop("TRIPLL_REPO_ROOT", None)
        try:
            assert resolve_repo_root(cwd=nested) == root.resolve()
        finally:
            if prev is not None:
                os.environ["TRIPLL_REPO_ROOT"] = prev
