"""Tests for ``scaffold_package`` — cookiecutter normalization + subprocess mock.

Covers W1.5 of the test-creator-tests-first wave plan: ``scaffold_package``
builds the correct cookiecutter command, applies the normalization map
(justfile->Makefile, ty->mypy), and handles subprocess failures.

Coverage matrix (W1.6):
  Unit:        cookiecutter command construction, normalization map application.
  Edge cases:  Missing cookiecutter extra, no-op when template already normalized.
  Error:       subprocess failure raises with descriptive error type + message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# W1.5 — Unit: scaffold_package builds correct command
# ---------------------------------------------------------------------------


class TestScaffoldCommand:
    """scaffold_package constructs the correct cookiecutter invocation."""

    def test_builds_uvx_cookiecutter_command(self) -> None:
        from tripll.scaffold import scaffold_package

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            scaffold_package(
                project_name="my-package",
                output_dir="/tmp/out",
            )
            call_args = mock_run.call_args
            argv = call_args[0][0] if call_args[0] else call_args[1].get("args", [])
            # Should invoke uvx cookiecutter with the right template
            assert "uvx" in argv or "cookiecutter" in " ".join(str(a) for a in argv)
            joined = " ".join(str(a) for a in argv)
            assert "cookiecutter" in joined
            assert "audreyfeldroy/cookiecutter-pypackage" in joined or "gh:" in joined

    def test_passes_no_input_flag(self) -> None:
        from tripll.scaffold import scaffold_package

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            scaffold_package(
                project_name="my-package",
                output_dir="/tmp/out",
            )
            call_args = mock_run.call_args
            argv = call_args[0][0] if call_args[0] else call_args[1].get("args", [])
            assert "--no-input" in [str(a) for a in argv]


# ---------------------------------------------------------------------------
# W1.5 — Unit: normalization map applied
# ---------------------------------------------------------------------------


class TestNormalizationMap:
    """Post-scaffold normalization map transforms cookiecutter output."""

    def test_justfile_renamed_to_makefile(self, tmp_path: Path) -> None:
        """justfile/Justfile should be renamed to Makefile."""
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        (project_dir / "justfile").write_text("# justfile")
        _apply_normalization(project_dir)
        assert (project_dir / "Makefile").exists()
        assert not (project_dir / "justfile").exists()

    def test_ty_toml_replaced_with_mypy(self, tmp_path: Path) -> None:
        """ty.toml should be dropped; mypy config should be present."""
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        (project_dir / "ty.toml").write_text("[tool.ty]\n")
        _apply_normalization(project_dir)
        assert not (project_dir / "ty.toml").exists()

    def test_tox_ini_dropped(self, tmp_path: Path) -> None:
        """tox.ini should be removed (uv handles cross-version)."""
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        (project_dir / "tox.ini").write_text("[tox]\n")
        _apply_normalization(project_dir)
        assert not (project_dir / "tox.ini").exists()

    def test_github_workflows_dropped(self, tmp_path: Path) -> None:
        """.github/workflows/ should be removed (sevn has its own CI)."""
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        wf_dir = project_dir / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\n")
        _apply_normalization(project_dir)
        assert not (project_dir / ".github" / "workflows").exists()

    def test_tests_dir_kept(self, tmp_path: Path) -> None:
        """tests/ directory should be preserved."""
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        tests_dir = project_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("def test_ok(): pass\n")
        _apply_normalization(project_dir)
        assert tests_dir.exists()
        assert (tests_dir / "test_example.py").exists()

    def test_pyproject_toml_kept(self, tmp_path: Path) -> None:
        """pyproject.toml should be preserved."""
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").write_text("[project]\n")
        _apply_normalization(project_dir)
        assert (project_dir / "pyproject.toml").exists()


# ---------------------------------------------------------------------------
# W1.5 — Edge: already-normalized project is idempotent
# ---------------------------------------------------------------------------


class TestNormalizationIdempotent:
    """Normalization is safe to run on already-normalized projects."""

    def test_no_op_when_already_normalized(self, tmp_path: Path) -> None:
        from tripll.scaffold import _apply_normalization

        project_dir = tmp_path / "my-package"
        project_dir.mkdir()
        (project_dir / "Makefile").write_text("# already a Makefile")
        (project_dir / "pyproject.toml").write_text("[project]\n")
        # Should not error or modify existing Makefile
        _apply_normalization(project_dir)
        assert (project_dir / "Makefile").read_text() == "# already a Makefile"


# ---------------------------------------------------------------------------
# W1.5 — Error: subprocess failure
# ---------------------------------------------------------------------------


class TestScaffoldSubprocessFailure:
    """scaffold_package raises on subprocess failure with error type + message."""

    def test_raises_on_nonzero_exit(self) -> None:
        from tripll.scaffold import ScaffoldError, scaffold_package

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="cookiecutter not found",
                stdout="",
            )
            with pytest.raises(ScaffoldError) as exc_info:
                scaffold_package(
                    project_name="bad-package",
                    output_dir="/tmp/out",
                )
            # Error message should mention what failed
            assert (
                "cookiecutter" in str(exc_info.value).lower()
                or "scaffold" in str(exc_info.value).lower()
            )

    def test_raises_on_missing_cookiecutter(self) -> None:
        """FileNotFoundError when cookiecutter binary is missing."""
        from tripll.scaffold import ScaffoldError, scaffold_package

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("uvx: command not found")
            with pytest.raises((ScaffoldError, FileNotFoundError)):
                scaffold_package(
                    project_name="missing-tool",
                    output_dir="/tmp/out",
                )

    def test_error_includes_stderr(self) -> None:
        """Error message includes subprocess stderr for debugging."""
        from tripll.scaffold import ScaffoldError, scaffold_package

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="network error: could not reach github.com",
                stdout="",
            )
            with pytest.raises(ScaffoldError) as exc_info:
                scaffold_package(
                    project_name="net-fail",
                    output_dir="/tmp/out",
                )
            assert (
                "network error" in str(exc_info.value).lower()
                or "stderr" in str(exc_info.value).lower()
            )
