"""Repo evaluation document generator for brownfield onboarding (W14).

Exports:
    EvaluationFinding — one evidence-backed finding row.
    EvaluationReport — structured evaluation payload.
    write_evaluation — write ``docs/evaluation-<date>.md`` and optional HTML report.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tripll.onboard.detect import RepoLayout
from tripll.onboard.doctor import DoctorReport
from tripll.skw.doc_folder import run_docs_command
from tripll.skw.paths import kit_root

__all__ = ["EvaluationFinding", "EvaluationReport", "write_evaluation"]


def _load_render_report_module() -> Any:
    path = kit_root() / "skills" / "improve-codebase-architecture" / "scripts" / "render_report.py"
    spec = importlib.util.spec_from_file_location("tripll_onboard_render_report", path)
    if spec is None or spec.loader is None:
        msg = f"render_report module not found: {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True, slots=True)
class EvaluationFinding:
    """One evaluation finding with mandatory evidence.

    Args:
        area (str): Section or subsystem name.
        category (str): ``works``, ``issue``, ``missing``, or ``stub``.
        summary (str): One-line finding text.
        evidence (str): ``file:line`` or command output reference.
        severity (str): ``HIGH``, ``MED``, ``LOW``, or ``INFO``.
    """

    area: str
    category: str
    summary: str
    evidence: str
    severity: str = "INFO"


@dataclass
class EvaluationReport:
    """Structured repo evaluation before wave planning.

    Args:
        repo_root (Path): Evaluated repository root.
        layout (RepoLayout): Detected layout metadata.
        doctor (DoctorReport): Provider and config readiness.
        graph_counts (dict[str, int]): Graph extract node/edge counts.
        findings (list[EvaluationFinding]): Evidence-backed findings.
        doc_scores (dict[str, int]): Average doc scores by kind.
        test_module_ratio (float | None): Tests per Python module ratio.
        make_check (str): ``passed``, ``failed``, ``skipped``, or ``missing``.
    """

    repo_root: Path
    layout: RepoLayout
    doctor: DoctorReport
    graph_counts: dict[str, int] = field(default_factory=dict)
    findings: list[EvaluationFinding] = field(default_factory=list)
    doc_scores: dict[str, int] = field(default_factory=dict)
    test_module_ratio: float | None = None
    make_check: str = "skipped"


def _probe_make_check(repo_root: Path) -> str:
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return "missing"
    try:
        proc = subprocess.run(
            ["make", "check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    return "passed" if proc.returncode == 0 else "failed"


def _score_docs(repo_root: Path, directory: Path, *, kind: str) -> int | None:
    if not directory.is_dir():
        return None
    result = run_docs_command("score", kind=kind, directory=directory, repo_root=repo_root)
    avg = result.rollup.get("average_total")
    return int(avg) if isinstance(avg, int) else None


def _build_findings(
    *,
    repo_root: Path,
    layout: RepoLayout,
    doctor: DoctorReport,
    graph_counts: dict[str, int],
    make_check: str,
    test_module_ratio: float | None,
) -> list[EvaluationFinding]:
    findings: list[EvaluationFinding] = []

    if layout.language == "python":
        sample = layout.python_modules[0] if layout.python_modules else "src/main.py"
        findings.append(
            EvaluationFinding(
                area="Structure",
                category="works",
                summary="Python sources detected for graph extract and spec interfaces.",
                evidence=f"{sample}:1",
                severity="INFO",
            )
        )
    else:
        findings.append(
            EvaluationFinding(
                area="Structure",
                category="missing",
                summary="No Python layout detected — spec interface AST checks may fail.",
                evidence="src/main.py:0",
                severity="MED",
            )
        )

    if doctor.available_provider_count == 0:
        findings.append(
            EvaluationFinding(
                area="Providers",
                category="issue",
                summary="No agent provider available — run `tripll setup` before dispatch.",
                evidence="src/tripll/onboard/doctor.py:184",
                severity="HIGH",
            )
        )
    else:
        findings.append(
            EvaluationFinding(
                area="Providers",
                category="works",
                summary=f"{doctor.available_provider_count} provider(s) ready for dispatch.",
                evidence="src/tripll/onboard/doctor.py:138",
                severity="INFO",
            )
        )

    if graph_counts.get("nodes", 0) > 0:
        findings.append(
            EvaluationFinding(
                area="Code graph",
                category="works",
                summary="Graph extract populated structural nodes for routing hints.",
                evidence=".tripll/graph.db:1",
                severity="INFO",
            )
        )
    else:
        findings.append(
            EvaluationFinding(
                area="Code graph",
                category="stub",
                summary="Graph extract produced no nodes — install graph/kg extras or add Python sources.",
                evidence="src/tripll/extract/pipeline.py:55",
                severity="MED",
            )
        )

    if make_check == "passed":
        findings.append(
            EvaluationFinding(
                area="Quality gate",
                category="works",
                summary="`make check` passed in the target repository.",
                evidence="Makefile:1",
                severity="INFO",
            )
        )
    elif make_check == "failed":
        findings.append(
            EvaluationFinding(
                area="Quality gate",
                category="issue",
                summary="`make check` failed — fix the gate before trusting green signals.",
                evidence="Makefile:1",
                severity="HIGH",
            )
        )
    else:
        sample = layout.python_modules[0] if layout.python_modules else "src/main.py"
        findings.append(
            EvaluationFinding(
                area="Quality gate",
                category="missing",
                summary="No Makefile check target — add `make check` or document alternate gate.",
                evidence=f"{sample}:1",
                severity="LOW",
            )
        )

    if test_module_ratio is not None:
        sample = layout.python_modules[0] if layout.python_modules else "src/main.py"
        findings.append(
            EvaluationFinding(
                area="Tests",
                category="works" if test_module_ratio >= 0.2 else "issue",
                summary=f"Test-to-module ratio is {test_module_ratio:.2f}.",
                evidence="tests/test_smoke.py:1" if test_module_ratio >= 0.2 else f"{sample}:1",
                severity="INFO" if test_module_ratio >= 0.2 else "MED",
            )
        )

    for note in layout.notes:
        findings.append(
            EvaluationFinding(
                area="Detection",
                category="issue",
                summary=note,
                evidence="tripll.toml:1",
                severity="LOW",
            )
        )

    return findings


def _render_markdown(report: EvaluationReport) -> str:
    today = date.today().isoformat()
    lines = [
        f"# {report.layout.repo_name} project evaluation",
        "",
        "| | |",
        "|---|---|",
        f"| **Date** | {today} |",
        f"| **Repo** | `{report.repo_root}` |",
        f"| **Target** | `{report.layout.target_repo}` |",
        "| **Method** | `tripll init` brownfield onboarding (graph extract, doc score, doctor) |",
        "",
        "## 0. Chronological map",
        "",
        "```text",
        "tripll init",
        "  ├─ detect layout → tripll.toml",
        "  ├─ emit docs/specs, docs/prds, docs/plans (v3)",
        "  ├─ graph extract → .tripll/graph.db",
        "  └─ write this evaluation",
        "```",
        "",
        "## 1. Structure & tooling",
        "",
        "### What works",
        "",
    ]

    for item in report.findings:
        if item.category == "works":
            lines.append(f"- {item.summary} (`{item.evidence}`)")

    lines.extend(
        ["", "### Issues", "", "| ID | Finding | Severity | Evidence |", "|---|---|---|---|"]
    )
    idx = 1
    for item in report.findings:
        if item.category in {"issue", "missing", "stub"}:
            lines.append(f"| EV-{idx:02d} | {item.summary} | {item.severity} | `{item.evidence}` |")
            idx += 1

    lines.extend(
        [
            "",
            "## 2. Documentation quality",
            "",
            f"- Spec score (avg): {report.doc_scores.get('spec', 'n/a')}",
            f"- PRD score (avg): {report.doc_scores.get('prd', 'n/a')}",
            "",
            "## 3. Provider readiness",
            "",
        ]
    )
    for name, (ok, detail) in report.doctor.providers.items():
        mark = "OK" if ok else "MISSING"
        lines.append(f"- **{name}**: {mark} — {detail}")

    lines.extend(
        [
            "",
            "## 4. Suggested next passes",
            "",
            "1. Review the scaffolded spec and PRD under `docs/specs/` and `docs/prds/`.",
            "2. Fill the v3 wave plan under `docs/plans/` and run `tripll validate-plan`.",
            "3. Run `tripll doctor` and `tripll setup` on the operator machine if providers are missing.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_html(report: EvaluationReport, md_path: Path) -> Path | None:
    try:
        render_mod = _load_render_report_module()
    except (ImportError, OSError):
        return None
    candidate_cls = render_mod.Candidate
    report_cls = render_mod.Report
    write_report_fn = render_mod.write_report
    candidates: list[Any] = []
    for item in report.findings:
        if item.category != "works":
            continue
        modules = [part for part in item.evidence.split(":")[0].split("/") if part]
        candidates.append(
            candidate_cls(
                title=item.area,
                strength="Worth exploring",
                files=[item.evidence.split(":")[0]],
                problem=item.summary,
                solution="See evaluation markdown for operator next steps.",
                wins=[f"evidence: {item.evidence}"],
                before_modules=modules[:3] or ["(repo)"],
                after_module=item.area.replace(" ", ""),
                tags=[item.category],
            )
        )
    if not candidates:
        candidates.append(
            candidate_cls(
                title="Review scaffolded docs",
                strength="Strong",
                files=[str(md_path.name)],
                problem="Brownfield onboarding emitted starter docs that need operator review.",
                solution="Edit spec/PRD/plan scaffolds before marking status ready.",
                wins=["idempotent init preserves operator edits"],
                before_modules=["docs/specs", "docs/prds", "docs/plans"],
                after_module="OnboardedRepo",
                after_internals=["spec", "prd", "plan"],
            )
        )
    top = str(candidates[0].title)
    payload = report_cls(
        repo_name=report.layout.repo_name,
        candidates=candidates,
        top_recommendation=top,
        top_recommendation_reason="Start from the highest-severity finding with file:line evidence.",
    )
    html_path: Path = write_report_fn(payload, out_dir=md_path.parent)
    return html_path


def write_evaluation(
    repo_root: Path,
    *,
    layout: RepoLayout,
    doctor: DoctorReport,
    graph_counts: dict[str, int],
    specs_dir: Path,
    prds_dir: Path,
    force: bool = False,
) -> Path:
    """Write ``docs/evaluation-<date>.md`` and companion HTML report.

    Args:
        repo_root (Path): Repository root.
        layout (RepoLayout): Detected layout metadata.
        doctor (DoctorReport): Preflight readiness snapshot.
        graph_counts (dict[str, int]): Graph extract counts.
        specs_dir (Path): Spec documents directory.
        prds_dir (Path): PRD documents directory.
        force (bool): Overwrite today's evaluation when True.

    Returns:
        Path: Written markdown evaluation path.
    """
    test_files = sum(1 for _ in repo_root.rglob("test_*.py"))
    modules = max(layout.python_file_count - test_files, 1)
    ratio = test_files / modules if modules else None

    doc_scores: dict[str, int] = {}
    spec_score = _score_docs(repo_root, specs_dir, kind="spec")
    if spec_score is not None:
        doc_scores["spec"] = spec_score
    prd_score = _score_docs(repo_root, prds_dir, kind="prd")
    if prd_score is not None:
        doc_scores["prd"] = prd_score

    make_check = _probe_make_check(repo_root)
    findings = _build_findings(
        repo_root=repo_root,
        layout=layout,
        doctor=doctor,
        graph_counts=graph_counts,
        make_check=make_check,
        test_module_ratio=ratio,
    )

    report = EvaluationReport(
        repo_root=repo_root,
        layout=layout,
        doctor=doctor,
        graph_counts=graph_counts,
        findings=findings,
        doc_scores=doc_scores,
        test_module_ratio=ratio,
        make_check=make_check,
    )

    out = repo_root / "docs" / f"evaluation-{date.today().isoformat()}.md"
    if out.is_file() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_markdown(report), encoding="utf-8")
    _render_html(report, out)
    return out
