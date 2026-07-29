"""Derive cited rules and context modules from evaluation findings (W2.3, R32).

Exports:
    DeriveResult — paths written by a derive run.
    derive_rules — consume :func:`tripll.onboard.evaluate._build_findings` output.
    passes_honesty_gate — drop scaffold filler via ``doc_score`` penalty phrases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — runtime repo paths

from loguru import logger

from tripll.config import RulesConfig, load_config
from tripll.onboard.detect import RepoLayout, detect_repo_layout
from tripll.onboard.doctor import build_doctor_report
from tripll.onboard.evaluate import EvaluationFinding, _build_findings
from tripll.rules.model import Rule, validate_rule
from tripll.rules.pack import ContextModule
from tripll.rules.store import RuleStore
from tripll.skw.spec_validate import load_spec_rules

__all__ = ["DeriveResult", "derive_rules", "passes_honesty_gate"]

_LOGGING_IMPORT_RE = re.compile(r"^\s*(import logging\b|from logging import\b)")


@dataclass
class DeriveResult:
    """Outcome of ``tripll rules derive``.

    Args:
        rules_written (list[Path]): Rule markdown paths written or reconciled.
        context_written (list[Path]): Context module paths written or reconciled.
        skipped (list[str]): Rule ids skipped (existing operator edits or honesty gate).
    """

    rules_written: list[Path] = field(default_factory=list)
    context_written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _scaffold_forbidden_phrases() -> list[str]:
    return list(load_spec_rules()["scaffold"]["forbidden_when_ready"])


def passes_honesty_gate(text: str, *, has_unit_tests: bool) -> bool:
    """Return False when *text* reads as scaffold filler (R32).

    Args:
        text (str): Rule or context body to score.
        has_unit_tests (bool): Whether the repo has ``test_*.py`` files.

    Returns:
        bool: ``True`` when the text is honest enough to emit.
    """
    body = text.strip()
    if not body:
        return False
    for phrase in _scaffold_forbidden_phrases():
        if phrase in body:
            return False
    lowered = body.lower()
    return not (not has_unit_tests and ("coverage" in lowered or "pytest --cov" in lowered))


def _count_unit_tests(repo_root: Path) -> int:
    count = 0
    for path in repo_root.rglob("test_*.py"):
        if any(part.startswith(".") for part in path.parts):
            continue
        count += 1
    return count


def _make_check_status(repo_root: Path) -> str:
    """Return make-check probe status without running full CI during derive."""
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return "missing"
    try:
        text = makefile.read_text(encoding="utf-8")
    except OSError:
        return "missing"
    if re.search(r"^check\s*:", text, re.MULTILINE):
        return "skipped"
    return "missing"


def _collect_findings(repo_root: Path, layout: RepoLayout) -> list[EvaluationFinding]:
    doctor = build_doctor_report()
    test_files = _count_unit_tests(repo_root)
    modules = max(layout.python_file_count - test_files, 1)
    ratio = test_files / modules if modules else None
    make_check = _make_check_status(repo_root)
    graph_counts = {"nodes": 0}
    db_path = repo_root / ".tripll" / "graph.db"
    if db_path.is_file():
        graph_counts = {"nodes": 1}
    return _build_findings(
        repo_root=repo_root,
        layout=layout,
        doctor=doctor,
        graph_counts=graph_counts,
        make_check=make_check,
        test_module_ratio=ratio,
    )


def _slugify_rule_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64] or "derived-rule"


def _default_scope_for_evidence(evidence: str) -> list[str]:
    file_part = evidence.split(":", 1)[0]
    if file_part.startswith("src/"):
        return ["src/**"]
    return ["**"]


def _finding_to_rule(finding: EvaluationFinding) -> Rule | None:
    if finding.category not in {"issue", "missing"}:
        return None
    if ":" not in finding.evidence:
        return None
    rel, line_s = finding.evidence.rsplit(":", 1)
    try:
        line_no = int(line_s)
    except ValueError:
        return None
    origin = f"codebase://{rel}:{line_no}"
    rule_id = _slugify_rule_id(f"{finding.area}-{finding.summary[:40]}")
    if "logging" in finding.summary.lower():
        rule_id = "no-stdlib-logging"
    body = (
        f"{finding.summary.strip()}\n\n"
        f"**Why:** Derived from onboarding evaluation finding ({finding.area}).\n"
        f"**Evidence:** `{finding.evidence}`.\n"
    )
    return Rule(
        rule_id=rule_id,
        state="proposed",
        origin=origin,
        scope=_default_scope_for_evidence(finding.evidence),
        body=body,
    )


def _scan_stdlib_logging_findings(repo_root: Path) -> list[EvaluationFinding]:
    """Supplement evaluation findings with stdlib ``logging`` detections at file:line."""
    extra: list[EvaluationFinding] = []
    for path in repo_root.rglob("*.py"):
        if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        rel = path.relative_to(repo_root).as_posix()
        for index, line in enumerate(lines, 1):
            if _LOGGING_IMPORT_RE.match(line):
                extra.append(
                    EvaluationFinding(
                        area="Logging",
                        category="issue",
                        summary="stdlib logging detected — prefer loguru or the project logger.",
                        evidence=f"{rel}:{index}",
                        severity="MED",
                    )
                )
                break
    return extra


def _build_context_modules(
    repo_root: Path,
    layout: RepoLayout,
    *,
    has_unit_tests: bool,
    findings: list[EvaluationFinding],
) -> list[ContextModule]:
    modules: list[ContextModule] = []
    readme = repo_root / "README.md"
    one_liner = layout.repo_name
    if readme.is_file():
        first_line = readme.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in first_line:
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                one_liner = stripped
                break

    overview_body = "\n".join(
        [
            f"**Project:** {one_liner}",
            "",
            "## Build and test",
            f"- Language: {layout.language}",
            f"- Test runner: {layout.test_runner or 'none detected'}",
            f"- CI: {layout.ci or 'none detected'}",
            "",
            "## Context table",
            "| Area | Status | Evidence |",
            "|---|---|---|",
        ]
    )
    for item in findings[:8]:
        overview_body += f"\n| {item.area} | {item.category} | `{item.evidence}` |"

    if not has_unit_tests:
        overview_body += (
            "\n\n## Testing honesty\n\n"
            "This repo has no unit tests (`test_*.py` files were not found). "
            "Do not invent test thresholds or quality gates the codebase does not enforce."
        )

    overview_body += (
        "\n\n## Gotchas\n\n- Append operator notes here; derive preserves this section.\n"
    )

    modules.append(
        ContextModule(
            topic="project-overview",
            scope=["**"],
            body=overview_body,
        )
    )
    return modules


def derive_rules(
    repo_root: Path,
    *,
    rules_dir: Path | None = None,
    context_dir: Path | None = None,
    rules_cfg: RulesConfig | None = None,
    force: bool = False,
) -> DeriveResult:
    """Derive cited rules and context modules from evaluation findings (CTX-01, R32).

    Consumes :func:`tripll.onboard.evaluate._build_findings` — does not run a
    second repo-wide architecture analysis.

    Args:
        repo_root (Path): Target repository root.
        rules_dir (Path | None): Override rules output directory.
        context_dir (Path | None): Override context output directory.
        rules_cfg (RulesConfig | None): Rules config; loaded when omitted.
        force (bool): Overwrite existing markdown when True.

    Returns:
        DeriveResult: Written artefact paths and skipped rule ids.
    """
    root = repo_root.resolve()
    cfg = rules_cfg or load_config(repo_root=root).rules
    if not cfg.enabled:
        logger.debug("rules derive skipped: [rules].enabled is false")
        return DeriveResult()

    layout = detect_repo_layout(root)
    findings = _collect_findings(root, layout)
    findings.extend(_scan_stdlib_logging_findings(root))

    has_unit_tests = _count_unit_tests(root) > 0
    store = RuleStore(root, rules_dir=rules_dir, context_dir=context_dir)
    store.ensure_dirs()

    result = DeriveResult()
    seen_ids: set[str] = set()

    for finding in findings:
        rule = _finding_to_rule(finding)
        if rule is None or rule.rule_id in seen_ids:
            continue
        if not passes_honesty_gate(rule.body, has_unit_tests=has_unit_tests):
            result.skipped.append(rule.rule_id)
            continue
        try:
            validate_rule(rule, repo_root=root)
        except (ValueError, OSError) as exc:
            logger.debug("skipping rule {}: {}", rule.rule_id, exc)
            result.skipped.append(rule.rule_id)
            continue
        path = store.rules_path / f"{rule.rule_id}.md"
        if path.is_file() and not force:
            result.rules_written.append(path)
            seen_ids.add(rule.rule_id)
            continue
        if path.is_file() and force:
            existing = store.read_rule(rule.rule_id)
            if existing is not None and existing.state == "active":
                logger.debug("derive: skipping active rule {}", rule.rule_id)
                result.skipped.append(rule.rule_id)
                seen_ids.add(rule.rule_id)
                continue
        written = store.write_rule(rule, force=force)
        result.rules_written.append(written)
        seen_ids.add(rule.rule_id)

    for module in _build_context_modules(
        root, layout, has_unit_tests=has_unit_tests, findings=findings
    ):
        if not passes_honesty_gate(module.body, has_unit_tests=has_unit_tests):
            result.skipped.append(module.topic)
            continue
        ctx_path = store.context_path / f"{module.topic}.md"
        if ctx_path.is_file() and not force:
            result.context_written.append(ctx_path)
            continue
        written = store.write_context_module(module, force=force)
        result.context_written.append(written)

    return result
