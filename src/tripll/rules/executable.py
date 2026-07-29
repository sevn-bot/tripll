"""Executable structural rules — ast-grep backend with prose fallback (W4.1, R29).

Exports:
    ExecutableRulesResult — outcome of a rules-check run.
    run_executable_rules — scan active executable rules under *repo_root*.
    main — CLI entry for ``make rules-check``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from tripll.config import load_config
from tripll.rules.model import Rule, parse_rule_markdown
from tripll.worktrees import path_matches_owned

__all__ = ["ExecutableRulesResult", "main", "run_executable_rules"]

_PY_SUFFIXES = frozenset({".py"})
_STRUCTURAL_LINE_RE = re.compile(r"^\s*(import\s+\S+|from\s+\S+\s+import\b)")


@dataclass
class ExecutableRulesResult:
    """Outcome of running active executable rules.

    Args:
        exit_code (int): ``0`` when clean or degraded; non-zero on violation.
        violations (list[str]): ``file:line`` messages for structural breaches.
        warnings (list[str]): Degrade / skip notices (e.g. absent ``ast-grep``).
    """

    exit_code: int = 0
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _list_rule_files(rules_dir: Path) -> list[Path]:
    if not rules_dir.is_dir():
        return []
    return sorted(rules_dir.glob("*.md"))


def _load_active_executable_rules(rules_dir: Path) -> list[Rule]:
    rules: list[Rule] = []
    for path in _list_rule_files(rules_dir):
        try:
            rule = parse_rule_markdown(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            logger.debug("skip rule {}: {}", path.name, exc)
            continue
        if rule.state != "active" or not rule.executable:
            continue
        rules.append(rule)
    return rules


def _scoped_python_files(repo_root: Path, scope: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.py"):
        if any(part.startswith(".") for part in path.parts):
            continue
        rel = path.relative_to(repo_root).as_posix()
        if scope and not path_matches_owned(rel, scope):
            continue
        files.append(path)
    return files


def _structural_violations(rule: Rule, files: list[Path]) -> list[str]:
    pattern = (rule.pattern or "").strip()
    if not pattern:
        return []
    violations: list[str] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        rel = path.as_posix()
        for line_no, line in enumerate(lines, 1):
            if pattern in line and _STRUCTURAL_LINE_RE.match(line):
                violations.append(f"{rel}:{line_no}: {line.strip()} ({rule.rule_id})")
                break
    return violations


def _ast_grep_violations(
    rule: Rule,
    files: list[Path],
    *,
    env: dict[str, str] | None,
) -> list[str] | None:
    """Run ``ast-grep scan`` when the binary is on PATH; ``None`` when absent."""
    pattern = (rule.pattern or "").strip()
    if not pattern or not files:
        return []
    run_env = {**os.environ, **(env or {})}
    if not shutil.which("ast-grep", path=run_env.get("PATH")):
        return None
    violations: list[str] = []
    for path in files:
        proc = subprocess.run(
            [
                "ast-grep",
                "scan",
                "-l",
                "python",
                "-p",
                pattern,
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=run_env,
            timeout=120,
        )
        if proc.returncode not in (0, 1):
            logger.debug(
                "ast-grep failed for {} on {}: {}",
                rule.rule_id,
                path,
                proc.stderr.strip(),
            )
            continue
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(path.as_posix()) or ":" in line:
                violations.append(f"{line} ({rule.rule_id})")
            else:
                violations.append(f"{path.as_posix()}: {line} ({rule.rule_id})")
    return sorted(set(violations))


def run_executable_rules(
    *,
    rules_dir: Path,
    repo_root: Path,
    backend: str | None = None,
    env: dict[str, str] | None = None,
) -> ExecutableRulesResult:
    """Run every active executable rule under *repo_root*.

    Args:
        rules_dir (Path): Directory of committed rule markdown files.
        repo_root (Path): Repository root to scan.
        backend (str | None): Override ``[rules].executable`` (``off`` | ``ast-grep``).
        env (dict[str, str] | None): Optional subprocess environment (e.g. minimal PATH).

    Returns:
        ExecutableRulesResult: Violations and degrade warnings.

    Examples:
        >>> run_executable_rules(
        ...     rules_dir=Path(".tripll/rules"),
        ...     repo_root=Path("."),
        ... ).exit_code in (0, 1)
        True
    """
    resolved_root = repo_root.resolve()
    cfg = load_config(repo_root=resolved_root)
    selected = (backend or cfg.rules.executable or "off").strip().lower()
    if selected == "off":
        return ExecutableRulesResult()

    rules = _load_active_executable_rules(rules_dir.resolve())
    if not rules:
        return ExecutableRulesResult()

    run_env = {**os.environ, **(env or {})}
    ast_grep_available = bool(shutil.which("ast-grep", path=run_env.get("PATH")))
    warnings: list[str] = []
    violations: list[str] = []

    for rule in rules:
        files = _scoped_python_files(resolved_root, rule.scope)
        pattern = (rule.pattern or "").strip()
        if not pattern:
            if not ast_grep_available:
                warnings.append(
                    f"{rule.rule_id}: ast-grep absent — prose-only enforcement for this rule"
                )
            continue

        if ast_grep_available:
            grep_hits = _ast_grep_violations(rule, files, env=env)
            if grep_hits is None:
                ast_grep_available = False
                grep_hits = []
            if grep_hits:
                violations.extend(grep_hits)
                continue

        if not ast_grep_available:
            warnings.append(f"{rule.rule_id}: ast-grep absent — using structural pattern fallback")
        structural = _structural_violations(rule, files)
        violations.extend(structural)

    if violations:
        return ExecutableRulesResult(
            exit_code=1, violations=sorted(set(violations)), warnings=warnings
        )
    return ExecutableRulesResult(exit_code=0, warnings=warnings)


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``make rules-check``.

    Args:
        argv (list[str] | None): Unused; reserved for future flags.

    Returns:
        int: Process exit code.

    Examples:
        >>> isinstance(main([]), int)
        True
    """
    _ = argv
    repo_root = Path.cwd().resolve()
    cfg = load_config(repo_root=repo_root)
    rules_dir = repo_root / cfg.rules.dir
    result = run_executable_rules(rules_dir=rules_dir, repo_root=repo_root)
    for warning in result.warnings:
        logger.warning(warning)
        sys.stderr.write(f"warning: {warning}\n")
    for violation in result.violations:
        sys.stderr.write(f"{violation}\n")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
