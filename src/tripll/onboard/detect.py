"""Repository layout detection for brownfield onboarding (W14).

Exports:
    RepoLayout — detected language, tooling, and structure signals.
    detect_repo_layout — inspect a git checkout and return layout metadata.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["RepoLayout", "detect_repo_layout"]

_PYTHON_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
_TEST_MARKERS = ("tests", "test")


@dataclass(frozen=True, slots=True)
class RepoLayout:
    """Detected repository structure and tooling.

    Args:
        repo_name (str): Directory or git remote basename.
        language (str): Primary language (``python``, ``unknown``).
        test_runner (str | None): Detected test runner (``pytest``, ``make``, etc.).
        ci (str | None): CI system hint (``github-actions``, etc.).
        has_makefile (bool): Whether a Makefile exists at repo root.
        python_modules (list[str]): Relative paths to Python modules under ``src/``.
        python_file_count (int): Count of ``*.py`` files excluding cache dirs.
        target_repo (str): ``owner/name`` when git remote resolves, else repo name.
        sample_symbols (list[tuple[str, str, str]]): ``(file, symbol, rel_path)`` tuples.
        notes (list[str]): Non-fatal detection notes for the evaluation.
    """

    repo_name: str
    language: str
    test_runner: str | None
    ci: str | None
    has_makefile: bool
    python_modules: list[str] = field(default_factory=list)
    python_file_count: int = 0
    target_repo: str = ""
    sample_symbols: list[tuple[str, str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _skip_part(part: str) -> bool:
    return part in {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _git_remote_target(repo_root: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not out:
        return None
    match = re.search(r"[:/]([^/]+/[^/.]+?)(?:\.git)?$", out)
    return match.group(1) if match else None


def _detect_test_runner(repo_root: Path) -> str | None:
    if (repo_root / "Makefile").is_file():
        text = (repo_root / "Makefile").read_text(encoding="utf-8", errors="replace")
        if re.search(r"^test\s*:", text, re.MULTILINE):
            return "make"
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        deps = data.get("project", {}).get("dependencies", [])
        opt = data.get("project", {}).get("optional-dependencies", {})
        dev = data.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
        opt_deps: list[Any] = []
        for rows in opt.values():
            if isinstance(rows, list):
                opt_deps.extend(str(x) for x in rows)
        joined = " ".join(str(x) for x in [*deps, *dev, *opt_deps])
        if "pytest" in joined:
            return "pytest"
    if any((repo_root / name).exists() for name in _TEST_MARKERS):
        return "pytest"
    return None


def _detect_ci(repo_root: Path) -> str | None:
    workflows = repo_root / ".github" / "workflows"
    if workflows.is_dir() and any(workflows.glob("*.yml")):
        return "github-actions"
    if (repo_root / ".gitlab-ci.yml").is_file():
        return "gitlab-ci"
    return None


def _iter_python_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.py"):
        if any(_skip_part(part) for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _first_symbol(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("def ") and "(" in stripped:
            name = stripped[4 : stripped.index("(")].strip()
            if not name.startswith("_"):
                return name
    return None


def detect_repo_layout(repo_root: Path) -> RepoLayout:
    """Inspect *repo_root* and return layout metadata for onboarding.

    Args:
        repo_root (Path): Git repository root.

    Returns:
        RepoLayout: Detected structure and tooling signals.

    Examples:
        >>> layout = detect_repo_layout(Path("."))
        >>> layout.language in {"python", "unknown"}
        True
    """
    root = repo_root.resolve()
    repo_name = root.name
    remote = _git_remote_target(root)
    target_repo = remote or repo_name

    py_files = _iter_python_files(root)
    python_file_count = len(py_files)
    language = (
        "python"
        if python_file_count or any((root / m).exists() for m in _PYTHON_MARKERS)
        else "unknown"
    )

    modules: list[str] = []
    symbols: list[tuple[str, str, str]] = []
    for path in py_files:
        rel = path.relative_to(root).as_posix()
        if rel.startswith("src/") and not rel.endswith("__init__.py"):
            modules.append(rel)
        symbol = _first_symbol(path)
        if symbol and len(symbols) < 5:
            symbols.append((rel, symbol, rel))

    notes: list[str] = []
    if language == "unknown":
        notes.append(f"{root}/: no Python markers detected")

    return RepoLayout(
        repo_name=repo_name,
        language=language,
        test_runner=_detect_test_runner(root),
        ci=_detect_ci(root),
        has_makefile=(root / "Makefile").is_file(),
        python_modules=modules[:20],
        python_file_count=python_file_count,
        target_repo=target_repo,
        sample_symbols=symbols,
        notes=notes,
    )
