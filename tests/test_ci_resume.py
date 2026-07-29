"""Tests for resumable CI checkpoint script."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci_resume.sh"


def _run_script(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=merged,
    )


def test_ci_steps_lists_expected_targets() -> None:
    proc = subprocess.run(
        ["make", "--no-print-directory", "-s", "ci-steps"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    steps = proc.stdout.split()
    assert steps[:3] == ["lint", "typecheck", "log-redact-check"]
    assert steps[-2:] == ["deps-audit", "build"]


def test_ci_resume_status_fresh_run(tmp_path: Path) -> None:
    state = tmp_path / ".ci-progress"
    proc = _run_script("--status", env={"TRIPLL_CI_PROGRESS_FILE": str(state)})
    assert proc.returncode == 0
    assert "no checkpoint" in proc.stdout


def test_ci_resume_reset_clears_checkpoint(tmp_path: Path) -> None:
    state = tmp_path / ".ci-progress"
    state.write_text("lint\n", encoding="utf-8")
    proc = _run_script("--reset", env={"TRIPLL_CI_PROGRESS_FILE": str(state)})
    assert proc.returncode == 0
    assert not state.exists()
    assert "checkpoint cleared" in proc.stdout


def test_ci_resume_unknown_arg() -> None:
    proc = _run_script("--nope")
    assert proc.returncode == 2
    assert "unknown argument" in proc.stderr
