"""Characterization tests for mergeCraft pin-parity gate (CI-02 / W2)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.check_mergecraft_ref_parity as parity

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MATCH_SHA = "b8e83a82e97ed537706d9a712e59af9ef031588f"
_DRIFT_SHA = "0000000000000000000000000000000000000000"


def _write_workflow(path: Path, sha: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"jobs:\n  review:\n    steps:\n      - uses: alexhawat/mergeCraft@{sha}\n",
        encoding="utf-8",
    )


def _write_makefile(path: Path, sha: str) -> None:
    path.write_text(
        f"MERGECRAFT_REF ?= $(if $(TRIPLL_MERGECRAFT_REF),$(TRIPLL_MERGECRAFT_REF),{sha})\n",
        encoding="utf-8",
    )


def _init_temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    _write_workflow(repo / ".github" / "workflows" / "mergecraft.yml", _MATCH_SHA)
    _write_makefile(repo / "Makefile", _MATCH_SHA)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def parity_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """Workflow + Makefile paths in a temp repo the gate reads instead of this one.

    The gate resolves the workflow pin through ``git show <ref>:`` from
    ``REPO_ROOT`` (R36), so pointing only ``WORKFLOW`` at a temp file would leave
    it reading tripll's own ``origin/main`` — coupling these cases to whatever
    pin the repo happens to carry.
    """
    repo = _init_temp_repo(tmp_path)
    monkeypatch.setattr(parity, "REPO_ROOT", repo)
    monkeypatch.setenv("TRIPLL_MERGECRAFT_PARITY_REF", "HEAD")
    workflow = repo / ".github" / "workflows" / "mergecraft.yml"
    makefile = repo / "Makefile"
    monkeypatch.setattr(parity, "WORKFLOW", workflow)
    monkeypatch.setattr(parity, "MAKEFILE", makefile)
    return workflow, makefile


def test_matching_pins_pass_temp_repo(parity_paths: tuple[Path, Path]) -> None:
    """Matching workflow and Makefile pins exit 0 (tier 1)."""
    assert parity.main() == 0


def test_drifted_pins_fail_temp_repo(parity_paths: tuple[Path, Path]) -> None:
    """Drifted pins exit non-zero with the drift message (tier 1)."""
    workflow, makefile = parity_paths
    _write_workflow(workflow, _MATCH_SHA)
    _write_makefile(makefile, _DRIFT_SHA)
    subprocess.run(["git", "commit", "-qam", "drift"], cwd=workflow.parents[2], check=True)
    assert parity.main() == 1


def test_unreachable_ref_offline_skips_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing parity ref warns and exits 0 when ``CI`` is unset (R36)."""
    repo = _init_temp_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TRIPLL_MERGECRAFT_PARITY_REF", "refs/does/not/exist")
    monkeypatch.setattr(parity, "REPO_ROOT", repo)
    monkeypatch.setattr(parity, "WORKFLOW", repo / ".github" / "workflows" / "mergecraft.yml")
    monkeypatch.setattr(parity, "MAKEFILE", repo / "Makefile")
    assert parity.main() == 0
    captured = capsys.readouterr()
    assert "warn" in captured.err.lower() or "skip" in captured.err.lower()


def test_unreachable_ref_ci_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing parity ref exits non-zero when ``CI`` is set (R36)."""
    repo = _init_temp_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CI", "1")
    monkeypatch.setenv("TRIPLL_MERGECRAFT_PARITY_REF", "refs/does/not/exist")
    monkeypatch.setattr(parity, "REPO_ROOT", repo)
    monkeypatch.setattr(parity, "WORKFLOW", repo / ".github" / "workflows" / "mergecraft.yml")
    monkeypatch.setattr(parity, "MAKEFILE", repo / "Makefile")
    assert parity.main() != 0


@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="tier-2 live gate")
def test_real_repo_parity_check_passes() -> None:
    """Live fetch against ``origin/main`` when ``RUN_LIVE=1`` (tier 2)."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_mergecraft_ref_parity"],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
