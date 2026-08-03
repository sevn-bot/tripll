"""spec-kit-wave extended stage renderers (front-end and special stages).

Implementation helpers for :mod:`tripll.skw.render` — wave-generator, front-end phases,
PRD author, verifier setup, and GitHub issue triage prompts.

Exports:
    build_wave_generator_context — wave-generator substitution map.
    render_wave_generator_prompt — render wave-generator prompt.
    build_frontend_context — spec-kit front-end substitution map.
    render_frontend_prompt — render one front-end phase prompt.
    resolve_prd_path — resolve PRD path against repo/kit roots.
    build_prd_author_context — PRD author substitution map.
    render_prd_author_prompt — render PRD author prompt.
    build_verifier_setup_context — verifier-setup substitution map.
    render_verifier_setup_prompt — render verifier-setup prompt.
    build_github_issue_triage_context — github-issue-triage substitution map.
    render_github_issue_triage_prompt — render github-issue-triage prompt.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from tripll.skw.render_core import (
    FRONTEND_STAGES,
    apply_context,
    check_unfilled,
)
from tripll.skw.validate import load_skw_config

# Defaults mirrored from scripts/context_paths.py (see render_core for rationale).
_DEFAULT_GLOSSARY = "about-sevn.bot/GLOSSARY.md"
_DEFAULT_DECISIONS_DIR = "about-sevn.bot/decisions"
_DEFAULT_WAYFINDER_MAPS_DIR = "spec/{slug}/wayfinder"


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
