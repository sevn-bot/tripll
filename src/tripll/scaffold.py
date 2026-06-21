"""tripll.scaffold — scaffold a new Python package via cookiecutter-pypackage.

Wraps ``uvx cookiecutter gh:audreyfeldroy/cookiecutter-pypackage`` (non-interactive)
and normalizes the generated project to sevn standards (Makefile / mypy / uv — not
the template's justfile / ty), per design-note §9.7. cookiecutter is an **optional**
dependency (the ``scaffold`` extra); nothing here runs at import time.

Exports:
    TEMPLATE — the cookiecutter template reference (GitHub shorthand).
    ScaffoldError — raised when scaffolding or normalization fails.
    scaffold_package — run cookiecutter for one new package and normalize its output.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

TEMPLATE = "gh:audreyfeldroy/cookiecutter-pypackage"

#: Files cookiecutter emits that sevn drops (uv/Makefile/mypy replace them).
_DROP_FILES = ("ty.toml", "tox.ini")


class ScaffoldError(RuntimeError):
    """Raised when package scaffolding fails (cookiecutter error or normalization).

    Examples:
        >>> issubclass(ScaffoldError, RuntimeError)
        True
    """


def _build_command(project_name: str, output_dir: Path) -> list[str]:
    """Build the non-interactive ``uvx cookiecutter`` argv for *project_name*.

    Args:
        project_name (str): The new package's project name (cookiecutter context).
        output_dir (Path): Directory cookiecutter writes the project into.

    Returns:
        list[str]: The argv for :func:`subprocess.run`.

    Examples:
        >>> "cookiecutter" in _build_command("demo", Path("/tmp"))
        True
    """
    return [
        "uvx",
        "cookiecutter",
        TEMPLATE,
        "--no-input",
        "--output-dir",
        str(output_dir),
        f"project_name={project_name}",
    ]


def _apply_normalization(project_dir: Path) -> None:
    """Normalize a cookiecutter-generated *project_dir* to sevn standards.

    Renames ``justfile``/``Justfile`` → ``Makefile`` (without clobbering an existing
    Makefile), drops ``ty.toml`` / ``tox.ini`` / ``.github/workflows/``, and keeps
    ``tests/`` + ``pyproject.toml``. Idempotent and a no-op when *project_dir* is
    absent.

    Args:
        project_dir (Path): The generated project root.

    Examples:
        >>> _apply_normalization(Path("/nonexistent-xyz")) is None
        True
    """
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        return

    for just_name in ("justfile", "Justfile"):
        just = project_dir / just_name
        if just.exists():
            makefile = project_dir / "Makefile"
            if makefile.exists():
                just.unlink()
            else:
                just.rename(makefile)

    for drop in _DROP_FILES:
        target = project_dir / drop
        if target.exists():
            target.unlink()

    workflows = project_dir / ".github" / "workflows"
    if workflows.exists():
        shutil.rmtree(workflows)


def _locate_project_dir(output_dir: Path, project_name: str) -> Path | None:
    """Find the project directory cookiecutter created under *output_dir*.

    Prefers ``output_dir/project_name``; otherwise the most recently modified
    subdirectory. Returns ``None`` when nothing was created (e.g. mocked runs).

    Args:
        output_dir (Path): Directory cookiecutter wrote into.
        project_name (str): The requested project name.

    Returns:
        Path | None: The generated project root, or ``None`` if not found.
    """
    candidate = output_dir / project_name
    if candidate.is_dir():
        return candidate
    if not output_dir.is_dir():
        return None
    subdirs = [p for p in output_dir.iterdir() if p.is_dir()]
    if not subdirs:
        return None
    return max(subdirs, key=lambda p: p.stat().st_mtime)


def scaffold_package(
    *,
    project_name: str,
    output_dir: str | Path,
    normalize: bool = True,
) -> Path | None:
    """Scaffold a new Python package from cookiecutter-pypackage and normalize it.

    Runs ``uvx cookiecutter gh:audreyfeldroy/cookiecutter-pypackage --no-input`` into
    *output_dir*, then (when *normalize*) maps the output onto sevn's toolchain
    (justfile→Makefile, drop ty/tox/.github workflows; keep tests/ + pyproject).

    Args:
        project_name (str): The new package's project name.
        output_dir (str | Path): Directory to create the package in.
        normalize (bool): Apply the sevn normalization map after generation.

    Returns:
        Path | None: The generated (normalized) project root, or ``None`` when the
        directory could not be located (e.g. under a mocked subprocess).

    Raises:
        ScaffoldError: When the cookiecutter subprocess exits non-zero or its binary
            is missing.

    Examples:
        >>> callable(scaffold_package)
        True
    """
    output_path = Path(output_dir)
    argv = _build_command(project_name, output_path)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ScaffoldError(
            f"scaffold failed: could not run cookiecutter (uvx not found) — {exc}"
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ScaffoldError(f"cookiecutter scaffold failed (exit {result.returncode}): {detail}")

    project_dir = _locate_project_dir(output_path, project_name)
    if normalize and project_dir is not None:
        _apply_normalization(project_dir)
    return project_dir
