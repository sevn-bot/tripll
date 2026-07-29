"""Shared helpers for partial CI gates (``ci-changed``, ``ci-affected``).

Module: scripts.ci_lib
Depends: fnmatch, os, subprocess, pathlib

Exports:
    PathRule — path glob → make target mapping row.
    collect_changed_paths — git diff union vs ``TRIPLL_CI_BASE``.
    collect_changed_py — changed ``.py`` under scan roots.
    match_path_rules — map changed paths to ``make`` target names.
    discover_related_tests — import-graph test selection.
    build_python_gate_steps — ruff/mypy/pytest step list for changed Python.
    run_step — subprocess helper with banner logging.
    run_make_targets — run deduped ``make`` targets in order.
    run_python_gates — execute Python partial gates.

Examples:
    >>> REPO_ROOT.name
    'tripll'
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = ("src/", "tests/", "scripts/")
_PY_SCAN_ROOTS = _SCAN_ROOTS


@dataclass(frozen=True)
class PathRule:
    """Map path globs (repo-relative) to one ``make`` target."""

    patterns: tuple[str, ...]
    target: str


# Order matters for logging only; targets are deduped before execution.
PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        (
            "about-tripll/_sources/**",
            "about-tripll/_templates/**",
            "scripts/build_about_site.py",
        ),
        "about-site-check",
    ),
    PathRule(
        (
            "config/log-hide-keys.toml",
            "tests/test_log_redact.py",
        ),
        "log-redact-check",
    ),
    PathRule(
        (
            ".github/workflows/pullfrog.yml",
            "Makefile",
            "scripts/check_pullfrog_ref_parity.py",
        ),
        "pullfrog-ref-check",
    ),
    PathRule(("CHANGELOG.md",), "changelog-check"),
)

# ``make`` target order when multiple path rules fire (stable, tier-ish).
TARGET_ORDER: tuple[str, ...] = (
    "pullfrog-ref-check",
    "log-redact-check",
    "about-site-check",
    "changelog-check",
)


def _ci_base() -> str:
    """Return merge-base ref for changed-path discovery.

    Returns:
        str: Git ref (default ``origin/main``).

    Examples:
        >>> _ci_base()
        'origin/main'
    """
    return os.environ.get("TRIPLL_CI_BASE") or os.environ.get("BASE") or "origin/main"


def _git_lines(args: list[str]) -> list[str]:
    """Return non-empty lines from a git command (empty when git fails).

    Args:
        args (list[str]): Arguments after ``git``.

    Returns:
        list[str]: Trimmed stdout lines.

    Examples:
        >>> isinstance(_git_lines(["rev-parse", "--show-toplevel"]), list)
        True
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def collect_changed_paths() -> list[str]:
    """Union changed repo-relative paths (working tree, index, branch vs base).

    Returns:
        list[str]: Sorted unique paths.

    Examples:
        >>> isinstance(collect_changed_paths(), list)
        True
    """
    base = _ci_base()
    seen: set[str] = set()
    for rel in (
        *_git_lines(["diff", "--name-only", "--diff-filter=ACMR"]),
        *_git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]),
        *_git_lines(["diff", "--name-only", f"{base}...HEAD", "--diff-filter=ACMR"]),
    ):
        if rel:
            seen.add(rel)
    return sorted(seen)


def collect_changed_py() -> list[Path]:
    """Union changed ``.py`` files under ``src/``, ``tests/``, ``scripts/``.

    Returns:
        list[Path]: Absolute paths, sorted unique.

    Examples:
        >>> paths = collect_changed_py()
        >>> all(p.suffix == ".py" for p in paths)
        True
    """
    return sorted(
        REPO_ROOT / rel
        for rel in collect_changed_paths()
        if rel.endswith(".py") and rel.startswith(_PY_SCAN_ROOTS)
    )


def _pattern_matches(rel_path: str, pattern: str) -> bool:
    """Return True when ``rel_path`` matches a repo-relative glob pattern.

    Args:
        rel_path (str): Repo-relative file path.
        pattern (str): Glob (``**`` supported via ``fnmatch`` segments).

    Returns:
        bool: True on match.

    Examples:
        >>> _pattern_matches("src/tripll/inject.py", "src/tripll/**")
        True
    """
    if fnmatch.fnmatch(rel_path, pattern):
        return True
    if "**" in pattern:
        prefix = pattern.split("**", 1)[0]
        if prefix and rel_path.startswith(prefix):
            return True
    return False


def match_path_rules(changed: list[str]) -> list[str]:
    """Map changed paths to deduped ``make`` targets (stable order).

    Args:
        changed (list[str]): Repo-relative changed paths.

    Returns:
        list[str]: ``make`` target names to run.

    Examples:
        >>> match_path_rules(["about-tripll/_sources/index.md"])
        ['about-site-check']
    """
    matched: set[str] = set()
    for rel in changed:
        for rule in PATH_RULES:
            if any(_pattern_matches(rel, pat) for pat in rule.patterns):
                matched.add(rule.target)
    order = {name: idx for idx, name in enumerate(TARGET_ORDER)}
    return sorted(matched, key=lambda target: (order.get(target, len(TARGET_ORDER)), target))


def _is_under(path: Path, root: Path) -> bool:
    """Return True when ``path`` is inside ``root``.

    Args:
        path (Path): Candidate file.
        root (Path): Directory prefix.

    Returns:
        bool: True when ``path`` is under ``root``.

    Examples:
        >>> _is_under(REPO_ROOT / "src/tripll/inject.py", REPO_ROOT / "src/tripll")
        True
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _module_dotted_name(src_path: Path) -> str | None:
    """Map ``src/tripll/pkg/mod.py`` → ``tripll.pkg.mod``.

    Args:
        src_path (Path): Source file under ``src/``.

    Returns:
        str | None: Dotted module name or ``None``.

    Examples:
        >>> p = REPO_ROOT / "src/tripll/inject.py"
        >>> _module_dotted_name(p)
        'tripll.inject'
    """
    try:
        rel = src_path.relative_to(REPO_ROOT / "src")
    except ValueError:
        return None
    return ".".join(rel.with_suffix("").parts)


def _import_needles(modules: set[str]) -> set[str]:
    """Build substring needles for tests that import ``modules``.

    Args:
        modules (set[str]): Dotted module names.

    Returns:
        set[str]: Import-line substrings to search for.

    Examples:
        >>> "from tripll.inject" in _import_needles({"tripll.inject"})
        True
    """
    needles: set[str] = set()
    for mod in modules:
        needles.add(f"from {mod} ")
        needles.add(f"from {mod}\n")
        needles.add(f"import {mod}")
        parts = mod.split(".")
        for i in range(len(parts), 0, -1):
            pkg = ".".join(parts[:i])
            needles.add(f"from {pkg} import")
            needles.add(f"import {pkg}")
    return needles


def _paired_test(src: Path) -> Path | None:
    """Map ``src/tripll/.../mod.py`` to ``tests/.../test_mod.py`` when present.

    Args:
        src (Path): Changed source file under ``src/tripll/``.

    Returns:
        Path | None: Matching test module or ``None``.

    Examples:
        >>> p = REPO_ROOT / "src/tripll/inject.py"
        >>> _paired_test(p) == REPO_ROOT / "tests/test_inject.py"
        True
    """
    try:
        rel = src.relative_to(REPO_ROOT / "src" / "tripll")
    except ValueError:
        return None
    nested = REPO_ROOT / "tests" / rel.parent / f"test_{rel.stem}.py"
    if nested.is_file():
        return nested
    flat = REPO_ROOT / "tests" / f"test_{rel.stem}.py"
    return flat if flat.is_file() else None


def discover_related_tests(src_tripll: list[Path]) -> list[Path]:
    """Select tests for changed ``src/tripll`` modules (paired + import graph).

    Args:
        src_tripll (list[Path]): Changed files under ``src/tripll/``.

    Returns:
        list[Path]: Absolute test paths, sorted unique.

    Examples:
        >>> discover_related_tests([]) == []
        True
    """
    modules = {m for p in src_tripll if (m := _module_dotted_name(p)) is not None}
    if not modules:
        return []

    selected: dict[Path, None] = {}
    for src in src_tripll:
        paired = _paired_test(src)
        if paired is not None:
            selected[paired] = None

    needles = _import_needles(modules)
    tests_root = REPO_ROOT / "tests"
    if tests_root.is_dir():
        for test_file in tests_root.rglob("*.py"):
            if test_file.name == "conftest.py" or not test_file.name.startswith("test_"):
                continue
            try:
                text = test_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if any(needle in text for needle in needles):
                selected[test_file] = None

    return sorted(selected)


def _uv_run_base() -> list[str]:
    """Build ``uv run`` argv prefix matching Makefile extras.

    Returns:
        list[str]: Command prefix for subprocess steps.

    Examples:
        >>> _uv_run_base()[:3]
        ['env', '-u', 'VIRTUAL_ENV', 'uv']
    """
    return [
        "env",
        "-u",
        "VIRTUAL_ENV",
        "uv",
        "run",
        "--extra",
        "dev",
        "--extra",
        "api",
        "--extra",
        "obs",
    ]


def _pytest_marker_expr() -> str:
    """Mirror Makefile tier gating for scoped pytest runs.

    Returns:
        str: Pytest ``-m`` expression.

    Examples:
        >>> "tier4" in _pytest_marker_expr()
        True
    """
    expr = "not tier4"
    if os.environ.get("RUN_LIVE") != "1":
        expr = f"{expr} and not tier2"
    return expr


def run_step(label: str, cmd: list[str], *, prefix: str = "ci-changed") -> int:
    """Run one subprocess step; print a banner and return exit code.

    Args:
        label (str): Step name for logs.
        cmd (list[str]): Executable + args.
        prefix (str): Log prefix (``ci-changed`` or ``ci-affected``).

    Returns:
        int: Subprocess exit code.

    Examples:
        >>> run_step.__name__
        'run_step'
    """
    rel_cmd = [
        str(Path(part).relative_to(REPO_ROOT)) if part.startswith(str(REPO_ROOT)) else part
        for part in cmd
    ]
    print(f"[{prefix}] {label}: {' '.join(rel_cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    return int(proc.returncode)


def run_make_targets(targets: list[str], *, prefix: str = "ci-affected") -> int:
    """Run ``make`` targets in order; stop aggregating failures.

    Args:
        targets (list[str]): ``make`` target names.
        prefix (str): Log prefix.

    Returns:
        int: First non-zero exit code, or ``0``.

    Examples:
        >>> run_make_targets([]) == 0
        True
    """
    exit_code = 0
    for target in targets:
        code = run_step(f"make {target}", ["make", target], prefix=prefix)
        if code != 0 and exit_code == 0:
            exit_code = code
    return exit_code


def build_python_gate_steps(changed: list[Path]) -> list[tuple[str, list[str]]]:
    """Build ruff/mypy/pytest steps for changed Python files.

    Args:
        changed (list[Path]): Absolute paths under ``src/``, ``tests/``, ``scripts/``.

    Returns:
        list[tuple[str, list[str]]]: Ordered subprocess steps.

    Examples:
        >>> steps = build_python_gate_steps([])
        >>> steps == []
        True
    """
    if not changed:
        return []

    rel_paths = [str(p.relative_to(REPO_ROOT)) for p in changed]
    src_tripll = [p for p in changed if _is_under(p, REPO_ROOT / "src" / "tripll")]
    test_files = [p for p in changed if _is_under(p, REPO_ROOT / "tests")]
    for src in src_tripll:
        paired = _paired_test(src)
        if paired is not None and paired not in test_files:
            test_files.append(paired)
    for related in discover_related_tests(src_tripll):
        if related not in test_files:
            test_files.append(related)

    uv = _uv_run_base()
    steps: list[tuple[str, list[str]]] = [
        (
            "ruff check",
            [*uv, "ruff", "check", "--config", "pyproject.toml", *rel_paths],
        ),
        (
            "ruff format --check",
            [*uv, "ruff", "format", "--check", "--config", "pyproject.toml", *rel_paths],
        ),
    ]
    if src_tripll:
        src_rel = [str(p.relative_to(REPO_ROOT)) for p in src_tripll]
        steps.append(
            (
                "mypy",
                [*uv, "mypy", "--config-file", "pyproject.toml", *src_rel],
            ),
        )
    if test_files:
        test_rel = [str(p.relative_to(REPO_ROOT)) for p in sorted(test_files)]
        steps.append(
            (
                "pytest",
                [
                    *uv,
                    "pytest",
                    *test_rel,
                    "-v",
                    "--tb=short",
                    "-m",
                    _pytest_marker_expr(),
                ],
            ),
        )
    return steps


def run_python_gates(changed: list[Path], *, prefix: str = "ci-changed") -> int:
    """Execute Python partial gates for ``changed`` paths.

    Args:
        changed (list[Path]): Absolute ``.py`` paths.
        prefix (str): Log prefix.

    Returns:
        int: ``0`` on success; first failure code otherwise.

    Examples:
        >>> run_python_gates([]) == 0
        True
    """
    steps = build_python_gate_steps(changed)
    exit_code = 0
    for label, cmd in steps:
        code = run_step(label, cmd, prefix=prefix)
        if code != 0 and exit_code == 0:
            exit_code = code
    return exit_code
