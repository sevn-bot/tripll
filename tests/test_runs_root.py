"""Default runs-root resolution for tripll dev vs foreign repos."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tripll.pipeline import default_runs_root, is_tripll_dev_checkout, resolve_runs_root

if TYPE_CHECKING:
    import pytest


def test_tripll_dev_checkout_uses_repo_runs() -> None:
    tripll_root = Path(__file__).resolve().parents[1]
    assert is_tripll_dev_checkout(tripll_root)
    assert default_runs_root(tripll_root) == (tripll_root / "runs").resolve()


def test_foreign_repo_defaults_to_tripll_runs(tmp_path: Path) -> None:
    repo = tmp_path / "foreign"
    repo.mkdir()
    (repo / "src" / "app").mkdir(parents=True)
    assert default_runs_root(repo) == (repo / ".tripll" / "runs").resolve()


def test_foreign_repo_keeps_legacy_runs(tmp_path: Path) -> None:
    repo = tmp_path / "legacy"
    legacy = repo / "runs"
    legacy.mkdir(parents=True)
    assert default_runs_root(repo) == legacy.resolve()


def test_resolve_runs_root_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom-runs"
    monkeypatch.setenv("TRIPLL_RUNS", str(custom))
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(tmp_path / "repo"))
    assert resolve_runs_root(None).root == custom.resolve()
