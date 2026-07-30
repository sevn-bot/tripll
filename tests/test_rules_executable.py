"""Executable rules — structural checks and ast-grep backend (W1.4)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.rules._helpers import require_attr

pytestmark = pytest.mark.tier1


def test_structural_match_catches_stdlib_logging_import(
    tmp_path: Path,
) -> None:
    """Tier-1: executable rule flags import logging in fixture tree."""
    run_executable_rules = require_attr("tripll.rules.executable", "run_executable_rules")
    rules_dir = tmp_path / ".tripll" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "no-stdlib-logging.md").write_text(
        "---\n"
        "rule_id: no-stdlib-logging\n"
        "state: active\n"
        "origin: codebase://src/a.py:1\n"
        'scope: ["src/**"]\n'
        "executable: ast-grep\n"
        "severity: error\n"
        "pattern: import logging\n"
        "---\n\n"
        "Never use stdlib logging.\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("import logging\n", encoding="utf-8")
    result = run_executable_rules(rules_dir=rules_dir, repo_root=tmp_path)
    assert result.exit_code != 0
    assert result.violations
    assert any("logging" in v.lower() for v in result.violations)


def test_ast_grep_absent_degrades_warn_exit_zero(tmp_path: Path) -> None:
    """Absent ast-grep binary ⇒ warn, prose-only, exit 0 (ADR 017)."""
    run_executable_rules = require_attr("tripll.rules.executable", "run_executable_rules")
    rules_dir = tmp_path / ".tripll" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "no-stdlib-logging.md").write_text(
        "---\n"
        "rule_id: no-stdlib-logging\n"
        "state: active\n"
        "origin: codebase://src/a.py:1\n"
        'scope: ["src/**"]\n'
        "executable: ast-grep\n"
        "severity: error\n"
        "---\n\n"
        "Never use stdlib logging.\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("import logging\n", encoding="utf-8")

    env = {"PATH": "/usr/bin:/bin"}
    if shutil.which("ast-grep", path=env["PATH"]):
        pytest.skip("ast-grep present on minimal PATH — use tier-2 for real binary")

    result = run_executable_rules(
        rules_dir=rules_dir,
        repo_root=tmp_path,
        backend="ast-grep",
        env=env,
    )
    assert result.exit_code == 0
    assert result.warnings
    assert any("ast-grep" in w.lower() or "prose" in w.lower() for w in result.warnings)


@pytest.mark.tier2
def test_real_ast_grep_binary_catches_violation(tmp_path: Path) -> None:
    """Tier-2: real ast-grep on PATH catches planted import logging."""
    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("tier-2 requires RUN_LIVE=1")
    if not shutil.which("ast-grep"):
        pytest.skip("ast-grep not installed")

    run_executable_rules = require_attr("tripll.rules.executable", "run_executable_rules")
    rules_dir = tmp_path / ".tripll" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "no-stdlib-logging.md").write_text(
        "---\n"
        "rule_id: no-stdlib-logging\n"
        "state: active\n"
        "origin: codebase://src/a.py:1\n"
        'scope: ["src/**"]\n'
        "executable: ast-grep\n"
        "severity: error\n"
        "pattern: import logging\n"
        "---\n\n"
        "Never use stdlib logging.\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("import logging\n", encoding="utf-8")
    result = run_executable_rules(rules_dir=rules_dir, repo_root=tmp_path)
    assert result.exit_code != 0


@pytest.mark.tier4
def test_ast_grep_availability_canary() -> None:
    """Tier-4 canary: report whether ast-grep is on PATH (never blocks)."""
    proc = subprocess.run(
        ["sh", "-c", "command -v ast-grep"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert proc.returncode in (0, 1)
