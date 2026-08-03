"""spec-kit-wave renderer core — fill prompt templates from a wave-file (stdlib only).

Implementation module for :mod:`tripll.skw.render` (ADR 013 façade). Callers import
from ``tripll.skw.render``, not this module.

Exports:
    PLACEHOLDER_RE — pattern for unfilled ``{{KEY}}`` placeholders.
    VALID_STAGES — LangGraph pipeline stages renderable from a wave-file.
    FRONTEND_STAGES — spec-kit front-end phase names.
    RENDER_STAGES — union of pipeline, front-end, and special stages.
    topo_sort — topological wave order for orchestrator rendering.
    build_context — assemble substitution map for one render pass.
    load_prompt_template — resolve the prompt file for a stage.
    render_prompt — render one stage to a string.
    check_unfilled — fail when any ``{{...}}`` remains.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from tripll.skw.agent_config import resolve_agent_params
from tripll.skw.markdown_sections import wave_heading_tasks
from tripll.skw.paths import repo_root_for_kit
from tripll.skw.resolve_wave import agent_for_role
from tripll.skw.validate import extract_toml_block, load_skw_config
from tripll.skw.wave_model import WavePlan

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
VALID_STAGES = frozenset({"run", "review", "generate", "orchestrator", "wave-generator"})
# Spec-kit front-end phases (author spec/plan artifacts; not part of the LangGraph loop).
# "wayfinder" is a pre-specify phase (D1): charts/works a local-markdown map of decision
# tickets before a destination is specifiable. See build_frontend_context's wayfinder branch.
FRONTEND_STAGES = frozenset({"specify", "clarify", "plan", "wayfinder"})

PRD_AUTHOR_STAGE = "prd-author"
VERIFIER_SETUP_STAGE = "verifier-setup"
GITHUB_ISSUE_TRIAGE_STAGE = "github-issue-triage"
SPECIAL_STAGES = frozenset({PRD_AUTHOR_STAGE, VERIFIER_SETUP_STAGE, GITHUB_ISSUE_TRIAGE_STAGE})
RENDER_STAGES = VALID_STAGES | FRONTEND_STAGES | SPECIAL_STAGES


def topo_sort(wave_ids: dict[str, list[str]]) -> list[str]:
    """Return wave ids in dependency-safe order (Kahn's algorithm).

    Args:
        wave_ids (dict[str, list[str]]): Map of wave id → ``depends_on`` ids.

    Returns:
        list[str]: Sorted ids; ties broken lexicographically.

    Examples:
        >>> topo_sort({"W0": [], "Final": ["W0"]})
        ['W0', 'Final']
    """
    indegree: dict[str, int] = {wid: 0 for wid in wave_ids}
    for wid, deps in wave_ids.items():
        for dep in deps:
            if dep in wave_ids:
                indegree[wid] += 1

    ready = sorted(wid for wid, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while ready:
        wid = ready.pop(0)
        order.append(wid)
        for other, deps in wave_ids.items():
            if wid in deps:
                indegree[other] -= 1
                if indegree[other] == 0:
                    ready.append(other)
                    ready.sort()
    if len(order) != len(wave_ids):
        msg = "dependency cycle or unresolved dependency in wave graph"
        raise ValueError(msg)
    return order


def _format_list(items: list[str]) -> str:
    if not items:
        return "(none)"
    return ", ".join(items)


def _format_verify(items: list[str]) -> str:
    if not items:
        return "(none)"
    return "; ".join(items)


def _status_table_skeleton(waves: list[dict[str, Any]], branch: str) -> str:
    lines = [
        "| Wave | Status | Branch | Commit | Evidence |",
        "|------|--------|--------|--------|----------|",
    ]
    for wave in waves:
        wid = wave.get("id", "")
        lines.append(f"| {wid} | pending | {branch} | | |")
    return "\n".join(lines)


def _resolve_prompt_path(
    data: dict[str, Any],
    stage: str,
    kit_root: Path,
    *,
    wave_id: str | None = None,
    wave_by_id: dict[str, dict[str, Any]] | None = None,
) -> Path:
    if stage == "orchestrator":
        path = kit_root / "prompts" / "orchestrator.md"
    elif stage == "wave-generator":
        path = kit_root / "prompts" / "wave-generator.md"
    elif stage == "run" and wave_id and wave_by_id:
        wave = wave_by_id.get(wave_id, {})
        role = str(wave.get("role", "impl"))
        if role == "test-author":
            path = kit_root / "prompts" / "test-creator.md"
        else:
            pipeline = data.get("pipeline", {})
            if not isinstance(pipeline, dict):
                msg = f"pipeline table missing for stage {stage!r}"
                raise ValueError(msg)
            stage_data = pipeline.get(stage, {})
            if not isinstance(stage_data, dict):
                msg = f"pipeline.{stage} table missing"
                raise ValueError(msg)
            prompt = stage_data.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                msg = f"pipeline.{stage}.prompt missing"
                raise ValueError(msg)
            path = kit_root / prompt
    else:
        pipeline = data.get("pipeline", {})
        if not isinstance(pipeline, dict):
            msg = f"pipeline table missing for stage {stage!r}"
            raise ValueError(msg)
        stage_data = pipeline.get(stage, {})
        if not isinstance(stage_data, dict):
            msg = f"pipeline.{stage} table missing"
            raise ValueError(msg)
        prompt = stage_data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            msg = f"pipeline.{stage}.prompt missing"
            raise ValueError(msg)
        path = kit_root / prompt
    if not path.is_file():
        msg = f"prompt template not found: {path.relative_to(kit_root)}"
        raise FileNotFoundError(msg)
    return path


def load_prompt_template(
    data: dict[str, Any],
    stage: str,
    kit_root: Path,
    *,
    wave_id: str | None = None,
    wave_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Load the prompt markdown for *stage*.

    Args:
        data (dict[str, Any]): Parsed TOML contract.
        stage (str): One of ``run``, ``review``, ``generate``, ``orchestrator``.
        kit_root (Path): Kit root directory.
        wave_id (str | None): Target wave id (for ``run`` stage role dispatch).
        wave_by_id (dict[str, dict[str, Any]] | None): Wave rows keyed by id.

    Returns:
        str: Raw prompt template text.

    Examples:
        >>> load_prompt_template({"pipeline": {"run": {"prompt": "x"}}}, "run", Path("."))  # doctest: +SKIP
        '...'
    """
    path = _resolve_prompt_path(
        data,
        stage,
        kit_root,
        wave_id=wave_id,
        wave_by_id=wave_by_id,
    )
    return path.read_text(encoding="utf-8")


def build_context(
    wave_path: Path,
    data: dict[str, Any],
    text: str,
    kit_root: Path,
    *,
    stage: str,
    wave_id: str | None = None,
) -> dict[str, str]:
    """Build the ``{{KEY}}`` substitution map for one render pass.

    Args:
        wave_path (Path): Path to the wave markdown file.
        data (dict[str, Any]): Parsed TOML contract.
        text (str): Full wave-file markdown body.
        kit_root (Path): Kit root directory.
        stage (str): Render stage name.
        wave_id (str | None): Target wave id (required for ``run``).

    Returns:
        dict[str, str]: Placeholder → value map.

    Examples:
        >>> build_context(Path("w.md"), {"title": "T", "slug": "s", "base": "main", "branch": "b", "pipeline": {"max_turns": 1}}, "", Path("."), stage="review")  # doctest: +SKIP
        {'TITLE': 'T', ...}
    """
    pipeline = data.get("pipeline", {})
    if not isinstance(pipeline, dict):
        pipeline = {}

    waves_raw = data.get("waves", [])
    waves: list[dict[str, Any]] = (
        [w for w in waves_raw if isinstance(w, dict)] if isinstance(waves_raw, list) else []
    )
    plans = WavePlan.from_wave_data(data)
    wave_ids: dict[str, list[str]] = {plan.id: plan.depends_on for plan in plans}
    wave_by_id: dict[str, WavePlan] = {plan.id: plan for plan in plans}

    skw = load_skw_config(kit_root)
    slug = str(data.get("slug", ""))
    branch = str(data.get("branch", ""))
    output_dir = "waves"
    verdict_path = f"{output_dir}/{slug}.review-result.json"

    try:
        plan_path = wave_path.resolve().relative_to(kit_root.resolve())
        plan_path_str = plan_path.as_posix()
    except ValueError:
        plan_path_str = wave_path.name

    pipeline_max = pipeline.get("max_turns")
    max_turns_val = pipeline_max if isinstance(pipeline_max, int) else skw.get("max_turns", 1)
    ctx: dict[str, str] = {
        "PLAN_PATH": plan_path_str,
        "TITLE": str(data.get("title", "")),
        "SLUG": slug,
        "BASE": str(data.get("base", skw.get("base", ""))),
        "BRANCH": branch,
        "OUTPUT_DIR": output_dir,
        "VERDICT_PATH": verdict_path,
        "MAX_TURNS": str(max_turns_val),
    }

    git_cfg = skw.get("git", {})
    if not isinstance(git_cfg, dict):
        git_cfg = {}
    ctx["GIT_REMOTE"] = str(git_cfg.get("remote", "origin"))
    ctx["GIT_COMMIT_PER_WAVE"] = "true" if git_cfg.get("commit_per_wave", True) else "false"
    ctx["GIT_PUSH_PER_WAVE"] = "true" if git_cfg.get("push_per_wave", True) else "false"

    review = pipeline.get("review", {})
    if isinstance(review, dict):
        ctx["REVIEW_AGENT"] = str(review.get("agent", "reviewer"))
        ctx["REVIEW_PROMPT"] = str(review.get("prompt", "prompts/reviewer.md"))
        inputs = review.get("inputs", {})
        if isinstance(inputs, dict):
            ctx["REVIEW_INPUT_PLUGIN"] = str(inputs.get("plugin", ""))
        else:
            ctx["REVIEW_INPUT_PLUGIN"] = ""
    else:
        ctx["REVIEW_AGENT"] = "reviewer"
        ctx["REVIEW_PROMPT"] = "prompts/reviewer.md"
        ctx["REVIEW_INPUT_PLUGIN"] = ""

    generate = pipeline.get("generate", {})
    if isinstance(generate, dict):
        ctx["GENERATE_PROMPT"] = str(
            generate.get("prompt", "prompts/post-review-wave-generator.md")
        )
    else:
        ctx["GENERATE_PROMPT"] = "prompts/post-review-wave-generator.md"

    order = topo_sort(wave_ids)
    ctx["WAVE_ORDER"] = " → ".join(order) if order else "(none)"
    ctx["STATUS_TABLE"] = _status_table_skeleton(waves, branch)

    target_id = wave_id
    if stage == "run":
        if not target_id:
            msg = "--wave is required for stage run"
            raise ValueError(msg)
    elif target_id is None and order:
        target_id = order[0]

    if target_id and target_id in wave_by_id:
        plan = wave_by_id[target_id]
        ctx["WAVE_ID"] = target_id
        ctx["WAVE_TITLE"] = plan.title
        ctx["WAVE_DEPENDS_ON"] = _format_list(wave_ids.get(target_id, []))
        ctx["WAVE_VERIFY"] = _format_verify(plan.verify)
        ctx["WAVE_ROLE"] = plan.role
        ctx["RUN_AGENT"] = agent_for_role(plan.role)
        ctx["WAVE_REVIEW_GATE"] = str(plan.review_gate)
        ctx["WAVE_TASKS"] = wave_heading_tasks(text, target_id)
    else:
        ctx["WAVE_ID"] = target_id or ""
        ctx["WAVE_TITLE"] = ""
        ctx["WAVE_DEPENDS_ON"] = "(none)"
        ctx["WAVE_VERIFY"] = "(none)"
        ctx["WAVE_ROLE"] = "impl"
        ctx["RUN_AGENT"] = "wave-runner"
        ctx["WAVE_REVIEW_GATE"] = "false"
        ctx["WAVE_TASKS"] = "(no tasks)"

    resolved_wave_id = target_id if stage == "run" else None
    params = resolve_agent_params(
        kit_root=kit_root,
        stage=stage,
        wave_data=data,
        wave_id=resolved_wave_id,
        skw_cfg=skw,
    )
    ctx["AGENT_ID"] = params.agent_id
    ctx["AGENT_MODEL"] = params.model
    ctx["AGENT_PARAMS"] = params.display_summary()
    ctx["AGENT_BIN"] = params.bin

    return ctx


def apply_context(template: str, context: dict[str, str]) -> str:
    """Replace ``{{KEY}}`` placeholders in *template* with *context* values.

    Args:
        template (str): Prompt template text.
        context (dict[str, str]): Substitution map.

    Returns:
        str: Rendered prompt.

    Examples:
        >>> apply_context("Plan {{PLAN_PATH}}", {"PLAN_PATH": "waves/x.md"})
        'Plan waves/x.md'
    """
    rendered = template
    for key, val in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", val)
    return rendered


def check_unfilled(text: str) -> list[str]:
    """Return sorted unfilled ``{{KEY}}`` placeholders in *text*.

    Args:
        text (str): Rendered prompt text.

    Returns:
        list[str]: Unique placeholder tokens still present.

    Examples:
        >>> check_unfilled("ok {{PLAN_PATH}}")
        ['{{PLAN_PATH}}']
        >>> check_unfilled("all filled")
        []
    """
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def render_prompt(
    wave_path: Path,
    kit_root: Path,
    *,
    stage: str,
    wave_id: str | None = None,
) -> str:
    """Render one stage prompt for *wave_path*.

    Args:
        wave_path (Path): Path to the wave markdown file.
        kit_root (Path): Kit root directory.
        stage (str): ``run``, ``review``, ``generate``, or ``orchestrator``.
        wave_id (str | None): Target wave id (required for ``run``).

    Returns:
        str: Fully rendered prompt (no unfilled placeholders).

    Examples:
        >>> render_prompt(Path("tests/fixtures/good-tier-b.md"), Path("."), stage="review")  # doctest: +SKIP
        '...'
    """
    if stage not in VALID_STAGES:
        msg = f"unknown stage {stage!r} (expected one of {sorted(VALID_STAGES)})"
        raise ValueError(msg)

    text = wave_path.read_text(encoding="utf-8")
    data, toml_err = extract_toml_block(text)
    if toml_err or data is None:
        msg = toml_err or "empty TOML block"
        raise ValueError(msg)

    wave_by_id: dict[str, WavePlan] = {plan.id: plan for plan in WavePlan.from_wave_data(data)}

    template = load_prompt_template(
        data,
        stage,
        kit_root,
        wave_id=wave_id,
        wave_by_id={wid: {"role": p.role} for wid, p in wave_by_id.items()},
    )
    context = build_context(
        wave_path,
        data,
        text,
        kit_root,
        stage=stage,
        wave_id=wave_id,
    )
    rendered = apply_context(template, context)
    unfilled = check_unfilled(rendered)
    if unfilled:
        msg = "unfilled placeholder(s): " + ", ".join(unfilled)
        raise ValueError(msg)
    return rendered


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str] | None): Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        int: Exit code (0 = success, 1 = error).

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(
        description="Render a spec-kit-wave prompt from a wave-file.",
    )
    parser.add_argument(
        "wave_file",
        type=Path,
        nargs="?",
        default=None,
        help="Path to the wave markdown file (not required for --stage wave-generator)",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=sorted(RENDER_STAGES),
        help="Pipeline stage to render",
    )
    parser.add_argument(
        "--wave",
        dest="wave_id",
        default=None,
        help="Target wave id (required for --stage run)",
    )
    parser.add_argument(
        "--slug", default=None, help="Plan slug (required for --stage wave-generator)"
    )
    parser.add_argument(
        "--title", default=None, help="Plan title (required for --stage wave-generator)"
    )
    parser.add_argument("--base", default=None, help="Git diff base (wave-generator)")
    parser.add_argument("--branch", default=None, help="Feature branch (wave-generator)")
    parser.add_argument(
        "--context",
        type=Path,
        default=None,
        help="Operator brief file (wave-generator)",
    )
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated paths to explore (wave-generator / prd-author)",
    )
    parser.add_argument(
        "--prd",
        type=Path,
        default=None,
        help="Target PRD path under about-sevn.bot/prd (required for --stage prd-author)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="PRD profile override: standard | ai-native (prd-author; default auto)",
    )
    parser.add_argument(
        "--issue",
        default=None,
        help="Target issue number (github-issue-triage single-issue mode)",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Triage full open queue (github-issue-triage)",
    )
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=None,
        help="Kit root directory (default: parent of scripts/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write rendered prompt to file instead of stdout",
    )
    args = parser.parse_args(argv)

    kit_root = args.kit_root
    if kit_root is None:
        kit_root = Path(__file__).resolve().parent
    kit_root = kit_root.resolve()

    from tripll.skw.render_stages import (
        render_frontend_prompt,
        render_github_issue_triage_prompt,
        render_prd_author_prompt,
        render_verifier_setup_prompt,
        render_wave_generator_prompt,
        resolve_prd_path,
    )

    try:
        if args.stage == PRD_AUTHOR_STAGE:
            if args.prd is None:
                msg = "--prd is required for --stage prd-author"
                raise ValueError(msg)
            explore_paths = None
            if args.paths:
                explore_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
            prd_resolved = resolve_prd_path(
                args.prd,
                repo_root=repo_root_for_kit(kit_root),
                kit_root=kit_root,
            )
            rendered = render_prd_author_prompt(
                kit_root,
                prd_path=prd_resolved,
                repo_root=repo_root_for_kit(kit_root),
                context_path=args.context,
                explore_paths=explore_paths,
                profile=args.profile,
            )
        elif args.stage == VERIFIER_SETUP_STAGE:
            explore_paths = None
            if args.paths:
                explore_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
            rendered = render_verifier_setup_prompt(
                kit_root,
                repo_root=repo_root_for_kit(kit_root),
                context_path=args.context,
                explore_paths=explore_paths,
            )
        elif args.stage == GITHUB_ISSUE_TRIAGE_STAGE:
            explore_paths = None
            if args.paths:
                explore_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
            rendered = render_github_issue_triage_prompt(
                kit_root,
                repo_root=repo_root_for_kit(kit_root),
                context_path=args.context,
                explore_paths=explore_paths,
                issue_number=args.issue,
                queue_all=args.queue,
            )
        elif args.stage in FRONTEND_STAGES:
            if not args.slug or not args.title:
                msg = f"--slug and --title are required for --stage {args.stage}"
                raise ValueError(msg)
            explore_paths = None
            if args.paths:
                explore_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
            rendered = render_frontend_prompt(
                kit_root,
                stage=args.stage,
                slug=args.slug,
                title=args.title,
                base=args.base,
                branch=args.branch,
                context_path=args.context,
                explore_paths=explore_paths,
            )
        elif args.stage == "wave-generator":
            if not args.slug or not args.title:
                msg = "--slug and --title are required for --stage wave-generator"
                raise ValueError(msg)
            explore_paths = None
            if args.paths:
                explore_paths = [p.strip() for p in args.paths.split(",") if p.strip()]
            rendered = render_wave_generator_prompt(
                kit_root,
                slug=args.slug,
                title=args.title,
                base=args.base,
                branch=args.branch,
                context_path=args.context,
                explore_paths=explore_paths,
            )
        else:
            if args.wave_file is None:
                msg = "wave_file is required for this stage"
                raise ValueError(msg)
            rendered = render_prompt(
                args.wave_file.resolve(),
                kit_root,
                stage=args.stage,
                wave_id=args.wave_id,
            )
    except (ValueError, FileNotFoundError) as exc:
        print(f"render.py: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
        if not rendered.endswith("\n"):
            sys.stdout.write("\n")
    return 0
