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

from tripll.skw.render_core import (
    FRONTEND_STAGES,
    GITHUB_ISSUE_TRIAGE_STAGE,
    PLACEHOLDER_RE,
    PRD_AUTHOR_STAGE,
    RENDER_STAGES,
    SPECIAL_STAGES,
    VALID_STAGES,
    VERIFIER_SETUP_STAGE,
    apply_context,
    build_context,
    check_unfilled,
    load_prompt_template,
    main,
    render_prompt,
    topo_sort,
)
from tripll.skw.render_stages import (
    build_frontend_context,
    build_github_issue_triage_context,
    build_prd_author_context,
    build_verifier_setup_context,
    build_wave_generator_context,
    render_frontend_prompt,
    render_github_issue_triage_prompt,
    render_prd_author_prompt,
    render_verifier_setup_prompt,
    render_wave_generator_prompt,
    resolve_prd_path,
)

__all__ = [
    "FRONTEND_STAGES",
    "GITHUB_ISSUE_TRIAGE_STAGE",
    "PLACEHOLDER_RE",
    "PRD_AUTHOR_STAGE",
    "RENDER_STAGES",
    "SPECIAL_STAGES",
    "VALID_STAGES",
    "VERIFIER_SETUP_STAGE",
    "apply_context",
    "build_context",
    "build_frontend_context",
    "build_github_issue_triage_context",
    "build_prd_author_context",
    "build_verifier_setup_context",
    "build_wave_generator_context",
    "check_unfilled",
    "load_prompt_template",
    "main",
    "render_frontend_prompt",
    "render_github_issue_triage_prompt",
    "render_prd_author_prompt",
    "render_prompt",
    "render_verifier_setup_prompt",
    "render_wave_generator_prompt",
    "resolve_prd_path",
    "topo_sort",
]

if __name__ == "__main__":
    raise SystemExit(main())
