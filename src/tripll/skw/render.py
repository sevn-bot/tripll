"""spec-kit-wave render — fill prompt templates from a wave-file (stdlib only).

Exports:
    PLACEHOLDER_RE — pattern for unfilled ``{{KEY}}`` placeholders.
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
import tomllib
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

# Defaults mirrored from scripts/context_paths.py (kept duplicated deliberately — that
# script is stdlib-only and importable with no ``skw`` package on ``sys.path``, so a
# vendored skill invoked raw by an IDE can resolve these paths without ``uv``/the kit
# installed; render.py cannot depend on it without breaking that contract).
_DEFAULT_GLOSSARY = "about-sevn.bot/GLOSSARY.md"
_DEFAULT_DECISIONS_DIR = "about-sevn.bot/decisions"
_DEFAULT_WAYFINDER_MAPS_DIR = "spec/{slug}/wayfinder"
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


def build_wave_generator_context(
    kit_root: Path,
    *,
    slug: str,
    title: str,
    base: str | None = None,
    branch: str | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
) -> dict[str, str]:
    """Build the ``{{KEY}}`` substitution map for wave-generator rendering.

    Args:
        kit_root (Path): Kit root directory.
        slug (str): Plan slug (output filename stem).
        title (str): Display title.
        base (str | None): Git diff base (``skw.toml`` default when omitted).
        branch (str | None): Feature branch (``feature/<slug>`` when omitted).
        context_path (Path | None): Optional operator brief file.
        explore_paths (list[str] | None): Optional paths to explore.

    Returns:
        dict[str, str]: Placeholder → value map.

    Examples:
        >>> ctx = build_wave_generator_context(Path("."), slug="s", title="T")  # doctest: +SKIP
        >>> ctx["SLUG"]
        's'
    """
    skw = load_skw_config(kit_root)
    resolved_base = base or str(skw.get("base", "origin/main"))
    resolved_branch = branch or f"feature/{slug}"
    output_dir = "waves"
    template_path = "wave-plan-template.md"

    if context_path is not None and context_path.is_file():
        operator_context = context_path.read_text(encoding="utf-8").strip()
        if not operator_context:
            operator_context = "(empty CONTEXT file)"
    else:
        operator_context = "(none provided)"

    explore_str = ", ".join(explore_paths) if explore_paths else "(none)"

    return {
        "SLUG": slug,
        "TITLE": title,
        "BASE": resolved_base,
        "BRANCH": resolved_branch,
        "OPERATOR_CONTEXT": operator_context,
        "EXPLORE_PATHS": explore_str,
        "OUTPUT_DIR": output_dir,
        "TEMPLATE_PATH": template_path,
    }


def render_wave_generator_prompt(
    kit_root: Path,
    *,
    slug: str,
    title: str,
    base: str | None = None,
    branch: str | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
) -> str:
    """Render the wave-generator prompt (no wave-file required).

    Args:
        kit_root (Path): Kit root directory.
        slug (str): Plan slug.
        title (str): Display title.
        base (str | None): Git diff base.
        branch (str | None): Feature branch.
        context_path (Path | None): Optional operator brief file.
        explore_paths (list[str] | None): Optional paths to explore.

    Returns:
        str: Fully rendered prompt (no unfilled placeholders).

    Examples:
        >>> render_wave_generator_prompt(Path("."), slug="s", title="T")  # doctest: +SKIP
        '...'
    """
    template_path = kit_root / "prompts" / "wave-generator.md"
    if not template_path.is_file():
        msg = f"prompt template not found: {template_path.relative_to(kit_root)}"
        raise FileNotFoundError(msg)
    template = template_path.read_text(encoding="utf-8")
    context = build_wave_generator_context(
        kit_root,
        slug=slug,
        title=title,
        base=base,
        branch=branch,
        context_path=context_path,
        explore_paths=explore_paths,
    )
    rendered = apply_context(template, context)
    unfilled = check_unfilled(rendered)
    if unfilled:
        msg = "unfilled placeholder(s): " + ", ".join(unfilled)
        raise ValueError(msg)
    return rendered


def _resolve_wayfinder_context(kit_root: Path, *, slug: str) -> dict[str, str]:
    """Resolve glossary/ADR/wayfinder paths for the ``wayfinder`` front-end phase.

    Reads ``skw.toml`` ``[context]``/``[wayfinder]`` directly with stdlib ``tomllib``
    (same tables, same defaults, same resolution rule as ``scripts/context_paths.py``
    — see that module's docstring for why the logic is duplicated rather than
    imported). Falls back to documented defaults when ``skw.toml`` is missing or the
    tables are absent, so this phase stays usable before Wave 0's seam is configured.

    Args:
        kit_root (Path): Kit root directory (contains ``skw.toml``).
        slug (str): Plan slug substituted for ``{slug}`` in ``wayfinder.maps_dir``.

    Returns:
        dict[str, str]: ``GLOSSARY_PATH``, ``DECISIONS_DIR``, ``WAYFINDER_MAPS_DIR``,
        ``MAP_PATH``, ``TICKETS_DIR`` — all absolute, resolved paths.
    """
    raw_glossary = _DEFAULT_GLOSSARY
    raw_decisions_dir = _DEFAULT_DECISIONS_DIR
    raw_maps_dir = _DEFAULT_WAYFINDER_MAPS_DIR

    skw_path = kit_root / "skw.toml"
    if skw_path.is_file():
        try:
            data = tomllib.loads(skw_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        context = data.get("context")
        if isinstance(context, dict):
            glossary = context.get("glossary")
            if isinstance(glossary, str) and glossary.strip():
                raw_glossary = glossary.strip()
            decisions_dir = context.get("decisions_dir")
            if isinstance(decisions_dir, str) and decisions_dir.strip():
                raw_decisions_dir = decisions_dir.strip()
        wayfinder = data.get("wayfinder")
        if isinstance(wayfinder, dict):
            maps_dir = wayfinder.get("maps_dir")
            if isinstance(maps_dir, str) and maps_dir.strip():
                raw_maps_dir = maps_dir.strip()

    from tripll.skw.paths import repo_root_for_kit

    repo_root = repo_root_for_kit(kit_root)
    glossary_path = (repo_root / raw_glossary).resolve()
    decisions_dir_path = (repo_root / raw_decisions_dir).resolve()
    wayfinder_maps_dir = (kit_root / raw_maps_dir.format(slug=slug)).resolve()

    return {
        "GLOSSARY_PATH": str(glossary_path),
        "DECISIONS_DIR": str(decisions_dir_path),
        "WAYFINDER_MAPS_DIR": str(wayfinder_maps_dir),
        "MAP_PATH": str(wayfinder_maps_dir / "MAP.md"),
        "TICKETS_DIR": str(wayfinder_maps_dir / "tickets"),
    }


def build_frontend_context(
    kit_root: Path,
    *,
    stage: str,
    slug: str,
    title: str,
    base: str | None = None,
    branch: str | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
) -> dict[str, str]:
    """Build the ``{{KEY}}`` map for a spec-kit front-end phase (``specify``/``clarify``/``plan``).

    Reuses the wave-generator context and adds spec-kit artifact paths so the phase prompts
    can point at ``spec/<slug>/`` outputs, the templates, and ``constitution.md``.

    Args:
        kit_root (Path): Kit root directory.
        stage (str): One of ``FRONTEND_STAGES``.
        slug (str): Plan slug (spec directory stem).
        title (str): Display title.
        base (str | None): Git diff base.
        branch (str | None): Feature branch.
        context_path (Path | None): Optional operator brief file.
        explore_paths (list[str] | None): Optional paths to explore.

    Returns:
        dict[str, str]: Placeholder → value map.
    """
    ctx = build_wave_generator_context(
        kit_root,
        slug=slug,
        title=title,
        base=base,
        branch=branch,
        context_path=context_path,
        explore_paths=explore_paths,
    )
    spec_dir = f"spec/{slug}"
    ctx.update(
        {
            "STAGE": stage,
            "SPEC_DIR": spec_dir,
            "SPEC_PATH": f"{spec_dir}/spec.md",
            "PLAN_DOC_PATH": f"{spec_dir}/plan.md",
            "CHECKLIST_PATH": f"{spec_dir}/checklist.md",
            "CONSTITUTION_PATH": "constitution.md",
            "SPEC_TEMPLATE": "spec-templates/spec-template.md",
            "PLAN_TEMPLATE": "spec-templates/plan-template.md",
            "CHECKLIST_TEMPLATE": "spec-templates/checklist-template.md",
            "WAVE_TEMPLATE": "wave-plan-template.md",
        }
    )
    if stage == "wayfinder":
        ctx.update(_resolve_wayfinder_context(kit_root, slug=slug))
    return ctx


def render_frontend_prompt(
    kit_root: Path,
    *,
    stage: str,
    slug: str,
    title: str,
    base: str | None = None,
    branch: str | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
) -> str:
    """Render one spec-kit front-end phase prompt (``prompts/<stage>.md``).

    Args:
        kit_root (Path): Kit root directory.
        stage (str): One of ``FRONTEND_STAGES``.
        slug (str): Plan slug.
        title (str): Display title.
        base (str | None): Git diff base.
        branch (str | None): Feature branch.
        context_path (Path | None): Optional operator brief file.
        explore_paths (list[str] | None): Optional paths to explore.

    Returns:
        str: Fully rendered prompt (no unfilled placeholders).
    """
    if stage not in FRONTEND_STAGES:
        msg = f"unknown front-end stage {stage!r} (expected one of {sorted(FRONTEND_STAGES)})"
        raise ValueError(msg)
    template_path = kit_root / "prompts" / f"{stage}.md"
    if not template_path.is_file():
        msg = f"prompt template not found: {template_path.relative_to(kit_root)}"
        raise FileNotFoundError(msg)
    template = template_path.read_text(encoding="utf-8")
    context = build_frontend_context(
        kit_root,
        stage=stage,
        slug=slug,
        title=title,
        base=base,
        branch=branch,
        context_path=context_path,
        explore_paths=explore_paths,
    )
    rendered = apply_context(template, context)
    unfilled = check_unfilled(rendered)
    if unfilled:
        msg = "unfilled placeholder(s): " + ", ".join(unfilled)
        raise ValueError(msg)
    return rendered


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


def resolve_prd_path(prd: str | Path, *, repo_root: Path, kit_root: Path) -> Path:
    """Resolve a PRD path against cwd, kit root, or repo root."""
    raw = Path(prd)
    if raw.is_file():
        return raw.resolve()
    for base in (Path.cwd(), kit_root, repo_root):
        candidate = (base / raw).resolve()
        if candidate.is_file():
            return candidate
    return (repo_root / raw).resolve()


def _derive_prd_id(prd_path: Path) -> str:
    stem = prd_path.stem
    return stem if stem.startswith("prd-") else f"prd-{stem}"


def _human_prd_title(prd_path: Path) -> str:
    slug = prd_path.stem.removeprefix("prd-")
    words = slug.split("-")
    if words and words[0].isdigit():
        words = words[1:]
    title = " ".join(word.capitalize() for word in words if word)
    return f"{title} — PRD" if title else "PRD"


def build_prd_author_context(
    kit_root: Path,
    *,
    prd_path: Path,
    repo_root: Path | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
    profile: str | None = None,
) -> dict[str, str]:
    """Build substitution map for ``prompts/prd-author.md``."""
    from tripll.skw.paths import repo_root_for_kit
    from tripll.skw.prd_validate import parse_frontmatter

    resolved_repo = (repo_root or repo_root_for_kit(kit_root)).resolve()
    prd_resolved = prd_path.resolve()
    try:
        prd_rel = prd_resolved.relative_to(resolved_repo).as_posix()
    except ValueError:
        prd_rel = prd_resolved.as_posix()

    prd_id = _derive_prd_id(prd_resolved)
    mode = "update" if prd_resolved.is_file() else "draft"
    resolved_profile = profile or "auto"

    title = _human_prd_title(prd_resolved)
    if prd_resolved.is_file():
        meta = parse_frontmatter(prd_resolved.read_text(encoding="utf-8"))[0]
        if isinstance(meta.get("title"), str) and meta["title"].strip():
            title = meta["title"].strip()
        if resolved_profile == "auto":
            resolved_profile = str(meta.get("prd_profile") or "standard")
    elif resolved_profile == "auto":
        resolved_profile = "standard"

    if context_path is not None and context_path.is_file():
        context_block = context_path.read_text(encoding="utf-8").strip() or "(empty CONTEXT file)"
    else:
        context_block = "(none provided)"

    paths_block = "\n".join(f"- `{p}`" for p in explore_paths) if explore_paths else "(none)"

    if prd_resolved.is_file():
        body_preview = prd_resolved.read_text(encoding="utf-8")
        if len(body_preview) > 4000:
            body_preview = body_preview[:4000] + "\n\n… (truncated — read full file on disk)"
        existing_block = f"```markdown\n{body_preview}\n```"
    else:
        existing_block = "(file does not exist yet — **draft** mode; create from template)"

    kit_rel = kit_root.resolve()
    try:
        kit_prefix = kit_rel.relative_to(resolved_repo).as_posix()
    except ValueError:
        kit_prefix = "src/tripll/skw"

    return {
        "PRD_PATH": prd_rel,
        "PRD_ID": prd_id,
        "PRD_TITLE": title,
        "MODE": mode,
        "PRD_PROFILE": resolved_profile,
        "CONTEXT_BLOCK": context_block,
        "PATHS_BLOCK": paths_block,
        "EXISTING_BLOCK": existing_block,
        "PRD_STANDARDS_PATH": f"{kit_prefix}/PRD-STANDARDS.md",
        "PRD_TEMPLATE_PATH": f"{kit_prefix}/prd-templates/prd-template.md",
        "PRD_RULES_PATH": f"{kit_prefix}/prd-templates/prd-rules.toml",
        "EARS_TEMPLATE_PATH": f"{kit_prefix}/spec-templates/acceptance-criteria-ears.md",
    }


def build_verifier_setup_context(
    kit_root: Path,
    *,
    repo_root: Path | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
) -> dict[str, str]:
    """Build substitution map for ``prompts/verifier-setup.md``."""
    from tripll.skw.paths import repo_root_for_kit

    resolved_repo = (repo_root or repo_root_for_kit(kit_root)).resolve()
    kit_rel = kit_root.resolve()
    try:
        kit_prefix = kit_rel.relative_to(resolved_repo).as_posix()
    except ValueError:
        kit_prefix = "src/tripll/skw"

    if context_path is not None and context_path.is_file():
        context_block = context_path.read_text(encoding="utf-8").strip() or "(empty CONTEXT file)"
    else:
        context_block = "(none provided)"

    paths_block = "\n".join(f"- `{p}`" for p in explore_paths) if explore_paths else "(none)"

    return {
        "SKILL_PATH": f"{kit_prefix}/skills/verifier-setup/SKILL.md",
        "TEMPLATE_PATH": f"{kit_prefix}/skills/verifier-setup/assets/verify.template.md",
        "CONTEXT_BLOCK": context_block,
        "PATHS_BLOCK": paths_block,
    }


def render_verifier_setup_prompt(
    kit_root: Path,
    *,
    repo_root: Path | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
) -> str:
    """Render ``prompts/verifier-setup.md`` for one-time verification scaffolding."""
    template_path = kit_root / "prompts" / "verifier-setup.md"
    if not template_path.is_file():
        msg = f"prompt template not found: {template_path.relative_to(kit_root)}"
        raise FileNotFoundError(msg)
    template = template_path.read_text(encoding="utf-8")
    context = build_verifier_setup_context(
        kit_root,
        repo_root=repo_root,
        context_path=context_path,
        explore_paths=explore_paths,
    )
    rendered = apply_context(template, context)
    unfilled = check_unfilled(rendered)
    if unfilled:
        msg = "unfilled placeholder(s): " + ", ".join(unfilled)
        raise ValueError(msg)
    return rendered


def build_github_issue_triage_context(
    kit_root: Path,
    *,
    repo_root: Path | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
    issue_number: str | None = None,
    queue_all: bool = False,
) -> dict[str, str]:
    """Build substitution map for ``prompts/github-issue-triage.md``."""
    from tripll.skw.paths import repo_root_for_kit

    resolved_repo = (repo_root or repo_root_for_kit(kit_root)).resolve()
    kit_rel = kit_root.resolve()
    try:
        kit_prefix = kit_rel.relative_to(resolved_repo).as_posix()
    except ValueError:
        kit_prefix = "src/tripll/skw"

    if context_path is not None and context_path.is_file():
        context_block = context_path.read_text(encoding="utf-8").strip() or "(empty CONTEXT file)"
    else:
        context_block = "(none provided)"

    paths_block = "\n".join(f"- `{p}`" for p in explore_paths) if explore_paths else "(none)"

    if issue_number:
        scope_block = f"Triage **issue #{issue_number}** (single-issue mode)."
    elif queue_all:
        scope_block = "Triage the **full open issue queue** (queue mode)."
    else:
        scope_block = (
            "Scope not pinned — ask the operator: single issue number, full queue, or a filter."
        )

    return {
        "SKILL_PATH": f"{kit_prefix}/skills/github-issue-triage/SKILL.md",
        "POLICY_PATH": f"{kit_prefix}/skills/github-issue-triage/references/triage-policy.md",
        "BRIEF_TEMPLATE_PATH": (
            f"{kit_prefix}/skills/github-issue-triage/assets/issue-wave-brief.template.md"
        ),
        "SCOPE_BLOCK": scope_block,
        "CONTEXT_BLOCK": context_block,
        "PATHS_BLOCK": paths_block,
    }


def render_github_issue_triage_prompt(
    kit_root: Path,
    *,
    repo_root: Path | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
    issue_number: str | None = None,
    queue_all: bool = False,
) -> str:
    """Render ``prompts/github-issue-triage.md`` for GitHub issue triage."""
    template_path = kit_root / "prompts" / "github-issue-triage.md"
    if not template_path.is_file():
        msg = f"prompt template not found: {template_path.relative_to(kit_root)}"
        raise FileNotFoundError(msg)
    template = template_path.read_text(encoding="utf-8")
    context = build_github_issue_triage_context(
        kit_root,
        repo_root=repo_root,
        context_path=context_path,
        explore_paths=explore_paths,
        issue_number=issue_number,
        queue_all=queue_all,
    )
    rendered = apply_context(template, context)
    unfilled = check_unfilled(rendered)
    if unfilled:
        msg = "unfilled placeholder(s): " + ", ".join(unfilled)
        raise ValueError(msg)
    return rendered


def render_prd_author_prompt(
    kit_root: Path,
    *,
    prd_path: Path,
    repo_root: Path | None = None,
    context_path: Path | None = None,
    explore_paths: list[str] | None = None,
    profile: str | None = None,
) -> str:
    """Render ``prompts/prd-author.md`` for one target PRD file."""
    template_path = kit_root / "prompts" / "prd-author.md"
    if not template_path.is_file():
        msg = f"prompt template not found: {template_path.relative_to(kit_root)}"
        raise FileNotFoundError(msg)
    template = template_path.read_text(encoding="utf-8")
    context = build_prd_author_context(
        kit_root,
        prd_path=prd_path,
        repo_root=repo_root,
        context_path=context_path,
        explore_paths=explore_paths,
        profile=profile,
    )
    rendered = apply_context(template, context)
    unfilled = check_unfilled(rendered)
    if unfilled:
        msg = "unfilled placeholder(s): " + ", ".join(unfilled)
        raise ValueError(msg)
    return rendered


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


if __name__ == "__main__":
    raise SystemExit(main())
