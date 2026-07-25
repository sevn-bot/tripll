"""Double LLM-score evaluator for CHANGELOG.md ``## [Unreleased]`` entries.

Module: skw.changelog_eval
Depends: tomllib (stdlib), pydantic; pydantic-ai + pydantic-evals loaded lazily
         only when a judge is actually run (never at import time).

This is the **advisory, on-request** quality gate that complements the
deterministic structural/diff validator. It is **never** wired into CI: it needs
live model access, so it fails loudly when no judge model is configured rather
than silently passing.

Design (see ``spec-kit-wave/CHANGELOG-STANDARDS.md``):
    * **Structured score** — one judge pass scores every rubric dimension on a
      0-10 scale with a one-line rationale (conceptually a per-dimension
      ``pydantic_evals.evaluators.LLMJudge``; implemented here as a single
      structured judge returning a pydantic model of per-dimension scores).
      Pass when *every* dimension ``>= structured_min``.
    * **Unstructured score** — a separate holistic judge pass: one overall 0-10
      plus free prose, no rubric scaffolding. Pass when ``>= unstructured_min``.
    * **Verdict** — PASS only when both passes clear their thresholds.

Exports:
    EvalConfig — thresholds + rubric dimensions + judge model.
    DimensionScore / StructuredScore / UnstructuredScore — judge output models.
    ChangelogEntry — one parsed Unreleased bullet.
    Verdict — combined double-score result.
    load_eval_config — read ``changelog-rules.toml`` ``[eval]`` with fallbacks.
    read_changelog / extract_unreleased_entries — parse the Unreleased block.
    score_structured / score_unstructured — the two judge passes.
    evaluate — end-to-end verdict for a repo.
    main — argparse CLI (``--repo``, ``--base``, ``--model``, ``--json``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Sequence

# --------------------------------------------------------------------------- #
# Defaults (mirror the [eval] block in spec-kit-wave/changelog-rules.toml)
# --------------------------------------------------------------------------- #

#: Cheap default judge. Override with ``--model`` or ``SEVN_CHANGELOG_JUDGE_MODEL``.
DEFAULT_JUDGE_MODEL = "anthropic:claude-haiku-4-5-20251001"

#: Rubric dimensions scored by the structured judge (Keep-a-Changelog quality bar).
DEFAULT_RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "specificity",
    "user_impact_clarity",
    "category_correctness",
    "diff_equivalence",
)

DEFAULT_STRUCTURED_MIN = 7
DEFAULT_UNSTRUCTURED_MIN = 7

#: Env var that overrides the judge model when ``--model`` is not passed.
MODEL_ENV_VAR = "SEVN_CHANGELOG_JUDGE_MODEL"

_MODEL_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")

_UNRELEASED_HEADING_RE = re.compile(r"^##\s*\[Unreleased\]\s*$", re.IGNORECASE | re.MULTILINE)
_NEXT_VERSION_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
_CATEGORY_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*\S)\s*$")

#: One-line human descriptions for the default rubric dimensions.
_DIMENSION_GUIDE: dict[str, str] = {
    "specificity": (
        "The entry names the concrete surface that changed (command, flag, path, "
        "endpoint) instead of a vague gesture like 'various fixes' or 'improvements'."
    ),
    "user_impact_clarity": (
        "A reader who did not write the code understands what is now different for "
        "them. Impact first, mechanism second."
    ),
    "category_correctness": (
        "The entry sits under the right Keep a Changelog category "
        "(Added/Changed/Deprecated/Removed/Fixed/Security)."
    ),
    "diff_equivalence": (
        "The entry faithfully reflects the actual code change: no invented behavior, "
        "no material change left undocumented, no overstatement."
    ),
}


class ChangelogEvalError(RuntimeError):
    """Base error for changelog evaluation problems."""


class NoEntriesError(ChangelogEvalError):
    """Raised when the ``## [Unreleased]`` block has no entries to score."""


class ModelUnavailableError(ChangelogEvalError):
    """Raised when no judge model / API access is configured. Fail loudly."""


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EvalConfig:
    """Thresholds and rubric for the double LLM score."""

    structured_min: int = DEFAULT_STRUCTURED_MIN
    unstructured_min: int = DEFAULT_UNSTRUCTURED_MIN
    rubric_dimensions: tuple[str, ...] = DEFAULT_RUBRIC_DIMENSIONS
    judge_model: str = DEFAULT_JUDGE_MODEL


def default_rules_path(repo_root: Path) -> Path:
    """Return the conventional ``changelog-rules.toml`` location.

    Args:
        repo_root (Path): Repository root.

    Returns:
        Path: ``<repo_root>/spec-kit-wave/changelog-rules.toml``.

    Examples:
        >>> default_rules_path(Path("/x")).as_posix()
        '/x/spec-kit-wave/changelog-rules.toml'
    """
    return repo_root / "spec-kit-wave" / "changelog-rules.toml"


def load_eval_config(path: Path | None) -> EvalConfig:
    """Read the ``[eval]`` block from ``changelog-rules.toml`` with fallbacks.

    Missing file or missing keys fall back to the module defaults, so the
    evaluator still runs before the sibling enforcement agent lands the toml.

    Args:
        path (Path | None): Path to ``changelog-rules.toml``; ``None`` yields defaults.

    Returns:
        EvalConfig: Thresholds, rubric dimensions, and judge model.

    Examples:
        >>> load_eval_config(None).structured_min
        7
    """
    if path is None or not Path(path).is_file():
        return EvalConfig()
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    eval_block = data.get("eval", {}) if isinstance(data, dict) else {}
    dims = eval_block.get("rubric_dimensions")
    rubric = (
        tuple(str(d) for d in dims)
        if isinstance(dims, (list, tuple)) and dims
        else DEFAULT_RUBRIC_DIMENSIONS
    )
    return EvalConfig(
        structured_min=int(eval_block.get("structured_min", DEFAULT_STRUCTURED_MIN)),
        unstructured_min=int(eval_block.get("unstructured_min", DEFAULT_UNSTRUCTURED_MIN)),
        rubric_dimensions=rubric,
        judge_model=str(eval_block.get("judge_model", DEFAULT_JUDGE_MODEL)),
    )


# --------------------------------------------------------------------------- #
# Judge output models
# --------------------------------------------------------------------------- #


class DimensionScore(BaseModel):
    """One rubric dimension scored by the structured judge."""

    dimension: str = Field(description="Rubric dimension name.")
    score: int = Field(ge=0, le=10, description="Integer quality score 0-10.")
    rationale: str = Field(description="One-line justification for the score.")


class StructuredScore(BaseModel):
    """Per-dimension structured judge output."""

    scores: list[DimensionScore] = Field(description="One entry per rubric dimension.")

    def min_score(self) -> int:
        """Return the lowest dimension score (0 when empty)."""
        return min((s.score for s in self.scores), default=0)

    def by_dimension(self) -> dict[str, DimensionScore]:
        """Return dimension name → score mapping."""
        return {s.dimension: s for s in self.scores}


class UnstructuredScore(BaseModel):
    """Holistic judge output — one overall score plus free prose."""

    score: int = Field(ge=0, le=10, description="Overall holistic quality 0-10.")
    rationale: str = Field(description="Free-form prose assessment (no rubric).")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ChangelogEntry:
    """One bullet under a category in the Unreleased block."""

    category: str
    text: str


def read_changelog(repo_root: Path, *, changelog_path: Path | None = None) -> str:
    """Read ``CHANGELOG.md`` text for a repository.

    Args:
        repo_root (Path): Repository root.
        changelog_path (Path | None): Explicit override path.

    Returns:
        str: File contents.

    Raises:
        FileNotFoundError: When the changelog does not exist.
    """
    target = changelog_path or (repo_root / "CHANGELOG.md")
    return Path(target).read_text(encoding="utf-8")


def extract_unreleased_block(changelog_text: str) -> str:
    """Return the raw markdown between ``## [Unreleased]`` and the next ``##``.

    Args:
        changelog_text (str): Full CHANGELOG.md text.

    Returns:
        str: Unreleased section body (empty string when absent).

    Examples:
        >>> extract_unreleased_block("# C\\n## [Unreleased]\\n### Added\\n- x\\n## [0.1]\\n")
        '### Added\\n- x'
    """
    match = _UNRELEASED_HEADING_RE.search(changelog_text)
    if match is None:
        return ""
    start = match.end()
    rest = changelog_text[start:]
    next_heading = _NEXT_VERSION_HEADING_RE.search(rest)
    block = rest[: next_heading.start()] if next_heading else rest
    return block.strip("\n").strip()


def extract_unreleased_entries(changelog_text: str) -> list[ChangelogEntry]:
    """Parse Unreleased bullets grouped under their category headings.

    Args:
        changelog_text (str): Full CHANGELOG.md text.

    Returns:
        list[ChangelogEntry]: One item per bullet under a ``### Category`` heading.

    Examples:
        >>> text = "## [Unreleased]\\n### Added\\n- New retry flag\\n### Fixed\\n- Crash\\n## [0.1]\\n"
        >>> [ (e.category, e.text) for e in extract_unreleased_entries(text) ]
        [('Added', 'New retry flag'), ('Fixed', 'Crash')]
    """
    block = extract_unreleased_block(changelog_text)
    entries: list[ChangelogEntry] = []
    category = "Uncategorized"
    for line in block.splitlines():
        stripped = line.strip()
        heading = _CATEGORY_HEADING_RE.match(stripped)
        if heading:
            category = heading.group(1).strip()
            continue
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            entries.append(ChangelogEntry(category=category, text=bullet.group(1).strip()))
    return entries


def format_entries(entries: Sequence[ChangelogEntry]) -> str:
    """Render entries back to grouped markdown for a judge prompt.

    Args:
        entries (Sequence[ChangelogEntry]): Parsed Unreleased entries.

    Returns:
        str: Markdown grouped by category, in first-seen order.
    """
    grouped: dict[str, list[str]] = {}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry.text)
    lines: list[str] = []
    for category, texts in grouped.items():
        lines.append(f"### {category}")
        lines.extend(f"- {text}" for text in texts)
        lines.append("")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- #
# Diff context (best-effort; informs the diff_equivalence dimension)
# --------------------------------------------------------------------------- #


def gather_diff_context(repo_root: Path, base: str, *, max_files: int = 60) -> str:
    """Return a short changed-file summary for ``base...HEAD`` (best effort).

    Never raises: on any failure (not a git repo, bad base) returns "".

    Args:
        repo_root (Path): Repository root.
        base (str): Diff base ref, e.g. ``origin/main``.
        max_files (int): Cap on listed files.

    Returns:
        str: Newline-joined changed paths, or "" when unavailable.
    """
    import subprocess  # lazy import: only at eval time

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    files = [line for line in proc.stdout.splitlines() if line.strip()]
    return "\n".join(files[:max_files])


# --------------------------------------------------------------------------- #
# Judge seam (single monkeypatch point for tests — no network here otherwise)
# --------------------------------------------------------------------------- #


def _model_access_configured(model: str) -> bool:
    """Return whether a judge model plus some credential appears configured."""
    if not model.strip():
        return False
    # A provider prefix with an obvious key env var, or a Test/function model.
    if model.startswith(("test", "function:")):
        return True
    return any(os.environ.get(var) for var in _MODEL_KEY_ENV_VARS)


def _run_judge(model: str, instructions: str, prompt: str, output_type: type[Any]) -> Any:
    """Run one pydantic-ai judge pass and return its structured output.

    This is the *only* place that touches the model. Tests monkeypatch this
    function so no network call or token is ever spent.

    Args:
        model (str): pydantic-ai model string (e.g. ``anthropic:claude-haiku-4-5-20251001``).
        instructions (str): System instructions for the judge.
        prompt (str): User prompt (the entries to score).
        output_type (type): Pydantic model the judge must return.

    Returns:
        Any: An instance of ``output_type``.

    Raises:
        ModelUnavailableError: When pydantic-ai is missing or the model errors.
    """
    try:
        from pydantic_ai import Agent  # lazy import by design
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        msg = (
            "pydantic-ai is not installed. Install the eval extra to run "
            "`make changelog-eval` (this gate needs live model access)."
        )
        raise ModelUnavailableError(msg) from exc
    try:
        agent = Agent(model, output_type=output_type, instructions=instructions)
        result = agent.run_sync(prompt)
    except Exception as exc:  # pragma: no cover - network/credential failures
        msg = f"changelog judge model {model!r} failed: {exc}"
        raise ModelUnavailableError(msg) from exc
    return result.output


# --------------------------------------------------------------------------- #
# Scoring passes
# --------------------------------------------------------------------------- #


def _structured_instructions(config: EvalConfig) -> str:
    lines = [
        "You are a meticulous release manager scoring CHANGELOG.md entries against a rubric.",
        "Score EACH dimension below independently on an integer 0-10 scale and give a",
        "one-line rationale. Do not average dimensions together. Be strict: vague,",
        "mechanism-first, or miscategorised entries score low.",
        "",
        "Dimensions:",
    ]
    for dim in config.rubric_dimensions:
        guide = _DIMENSION_GUIDE.get(dim, "Judge this dimension on its plain meaning.")
        lines.append(f"- {dim}: {guide}")
    lines.append("")
    lines.append("Return one DimensionScore per dimension listed above, in that order.")
    return "\n".join(lines)


def _structured_prompt(entries: Sequence[ChangelogEntry], diff_context: str) -> str:
    parts = ["Changelog `## [Unreleased]` entries under review:", "", format_entries(entries)]
    if diff_context:
        parts += [
            "",
            "Changed files in this branch (context for the diff_equivalence dimension):",
            "",
            diff_context,
        ]
    return "\n".join(parts)


def score_structured(
    entries: Sequence[ChangelogEntry],
    model: str,
    *,
    config: EvalConfig | None = None,
    diff_context: str = "",
) -> StructuredScore:
    """Score every rubric dimension with one structured judge pass.

    Args:
        entries (Sequence[ChangelogEntry]): Parsed Unreleased entries.
        model (str): pydantic-ai judge model string.
        config (EvalConfig | None): Thresholds/rubric; defaults applied when ``None``.
        diff_context (str): Optional changed-file summary for diff_equivalence.

    Returns:
        StructuredScore: Per-dimension scores + rationales.

    Raises:
        NoEntriesError: When ``entries`` is empty.
    """
    cfg = config or EvalConfig()
    if not entries:
        raise NoEntriesError("no Unreleased entries to score")
    result = _run_judge(
        model,
        _structured_instructions(cfg),
        _structured_prompt(entries, diff_context),
        StructuredScore,
    )
    if not isinstance(result, StructuredScore):  # pragma: no cover - defensive
        result = StructuredScore.model_validate(result)
    return result


def _unstructured_instructions() -> str:
    return (
        "You are an experienced open-source maintainer reading a project's changelog "
        "before a release. Give ONE overall quality score from 0 to 10 and a short prose "
        "assessment. Judge holistically — do not use a checklist or rubric. Ask yourself: "
        "would these entries let a user understand what changed and whether it affects them?"
    )


def score_unstructured(
    entries: Sequence[ChangelogEntry],
    model: str,
) -> UnstructuredScore:
    """Score the Unreleased entries holistically (no rubric scaffolding).

    Args:
        entries (Sequence[ChangelogEntry]): Parsed Unreleased entries.
        model (str): pydantic-ai judge model string.

    Returns:
        UnstructuredScore: Overall score + free prose.

    Raises:
        NoEntriesError: When ``entries`` is empty.
    """
    if not entries:
        raise NoEntriesError("no Unreleased entries to score")
    prompt = "Changelog `## [Unreleased]` entries:\n\n" + format_entries(entries)
    result = _run_judge(model, _unstructured_instructions(), prompt, UnstructuredScore)
    if not isinstance(result, UnstructuredScore):  # pragma: no cover - defensive
        result = UnstructuredScore.model_validate(result)
    return result


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Verdict:
    """Combined double-score result."""

    passed: bool
    structured_passed: bool
    unstructured_passed: bool
    structured: StructuredScore
    unstructured: UnstructuredScore
    config: EvalConfig
    entry_count: int
    failing_dimensions: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "passed": self.passed,
            "structured_passed": self.structured_passed,
            "unstructured_passed": self.unstructured_passed,
            "entry_count": self.entry_count,
            "thresholds": {
                "structured_min": self.config.structured_min,
                "unstructured_min": self.config.unstructured_min,
            },
            "failing_dimensions": list(self.failing_dimensions),
            "structured": {
                s.dimension: {"score": s.score, "rationale": s.rationale}
                for s in self.structured.scores
            },
            "unstructured": {
                "score": self.unstructured.score,
                "rationale": self.unstructured.rationale,
            },
        }


def build_verdict(
    structured: StructuredScore,
    unstructured: UnstructuredScore,
    config: EvalConfig,
    entry_count: int,
) -> Verdict:
    """Combine both scores into a pass/fail verdict against the thresholds.

    Pass only when every rubric dimension clears ``structured_min`` *and* the
    holistic score clears ``unstructured_min``.

    Args:
        structured (StructuredScore): Per-dimension judge output.
        unstructured (UnstructuredScore): Holistic judge output.
        config (EvalConfig): Thresholds.
        entry_count (int): Number of scored entries.

    Returns:
        Verdict: Combined result.

    Examples:
        >>> s = StructuredScore(scores=[DimensionScore(dimension="d", score=8, rationale="ok")])
        >>> u = UnstructuredScore(score=8, rationale="clear")
        >>> build_verdict(s, u, EvalConfig(), 1).passed
        True
    """
    failing = tuple(s.dimension for s in structured.scores if s.score < config.structured_min)
    structured_passed = not failing and bool(structured.scores)
    unstructured_passed = unstructured.score >= config.unstructured_min
    return Verdict(
        passed=structured_passed and unstructured_passed,
        structured_passed=structured_passed,
        unstructured_passed=unstructured_passed,
        structured=structured,
        unstructured=unstructured,
        config=config,
        entry_count=entry_count,
        failing_dimensions=failing,
    )


def evaluate(
    repo_root: Path,
    *,
    base: str = "origin/main",
    model: str | None = None,
    config: EvalConfig | None = None,
    rules_path: Path | None = None,
    changelog_path: Path | None = None,
    diff_context: str | None = None,
) -> Verdict:
    """Run the full double LLM score for a repo's Unreleased entries.

    Args:
        repo_root (Path): Repository root.
        base (str): Diff base ref for diff_equivalence context.
        model (str | None): Judge model override; falls back to env then config.
        config (EvalConfig | None): Preloaded config; else read ``rules_path``.
        rules_path (Path | None): ``changelog-rules.toml`` path; default convention.
        changelog_path (Path | None): CHANGELOG.md override path.
        diff_context (str | None): Preformatted diff context; else best-effort git.

    Returns:
        Verdict: Combined double-score verdict.

    Raises:
        NoEntriesError: When there is nothing under ``## [Unreleased]``.
        ModelUnavailableError: When no judge model / credentials are configured.
    """
    cfg = config or load_eval_config(rules_path or default_rules_path(repo_root))
    judge_model = model or os.environ.get(MODEL_ENV_VAR) or cfg.judge_model
    if not _model_access_configured(judge_model):
        msg = (
            f"no model access for changelog eval (model={judge_model!r}). "
            f"Set {MODEL_ENV_VAR} and a provider key (e.g. ANTHROPIC_API_KEY), "
            "or pass --model. This gate is advisory and never runs in CI."
        )
        raise ModelUnavailableError(msg)

    text = read_changelog(repo_root, changelog_path=changelog_path)
    entries = extract_unreleased_entries(text)
    if not entries:
        raise NoEntriesError(
            "CHANGELOG.md `## [Unreleased]` has no entries to score. "
            "Draft entries with the changelog-author skill first."
        )
    ctx = diff_context if diff_context is not None else gather_diff_context(repo_root, base)
    structured = score_structured(entries, judge_model, config=cfg, diff_context=ctx)
    unstructured = score_unstructured(entries, judge_model)
    return build_verdict(structured, unstructured, cfg, len(entries))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _render_text(verdict: Verdict) -> str:
    cfg = verdict.config
    lines = [
        "Changelog double LLM score",
        "==========================",
        f"entries scored: {verdict.entry_count}",
        "",
        f"Structured (per dimension, pass = all >= {cfg.structured_min}):",
    ]
    for s in verdict.structured.scores:
        mark = "PASS" if s.score >= cfg.structured_min else "FAIL"
        lines.append(f"  [{mark}] {s.dimension}: {s.score}/10 — {s.rationale}")
    lines += [
        "",
        f"Unstructured (holistic, pass = >= {cfg.unstructured_min}):",
        f"  [{'PASS' if verdict.unstructured_passed else 'FAIL'}] "
        f"{verdict.unstructured.score}/10 — {verdict.unstructured.rationale}",
        "",
        f"VERDICT: {'PASS' if verdict.passed else 'FAIL'}",
    ]
    if verdict.failing_dimensions:
        lines.append(f"  below bar: {', '.join(verdict.failing_dimensions)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the changelog double LLM score.

    Exit codes: 0 PASS · 1 quality FAIL · 2 no model access · 3 no entries / error.

    Args:
        argv (Sequence[str] | None): Argument vector (defaults to ``sys.argv``).

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(
        prog="changelog-eval",
        description="Advisory double LLM score for CHANGELOG.md Unreleased entries.",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root.")
    parser.add_argument("--base", default="origin/main", help="Diff base ref.")
    parser.add_argument("--model", default=None, help="pydantic-ai judge model string.")
    parser.add_argument("--rules", type=Path, default=None, help="changelog-rules.toml path.")
    parser.add_argument("--changelog", type=Path, default=None, help="CHANGELOG.md path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args(argv)

    try:
        verdict = evaluate(
            args.repo.resolve(),
            base=args.base,
            model=args.model,
            rules_path=args.rules,
            changelog_path=args.changelog,
        )
    except NoEntriesError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ModelUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, ChangelogEvalError) as exc:
        print(f"changelog eval error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2))
    else:
        print(_render_text(verdict))
    return 0 if verdict.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
