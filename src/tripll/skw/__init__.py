"""spec-kit-wave (skw) — uv-managed wave pipeline kit.

Exports:
    extract_toml_block — parse fenced TOML from wave markdown.
    topo_sort — topological wave ordering.
    load_skw_config — read ``skw.toml`` merged with defaults.
    build_context — assemble render substitution map.
    load_wave_data — parse wave-file TOML contract.
    validate_wave_file — strict wave-file v2 validation.
    render_prompt — fill one prompt template stage.
    scaffold_wave_file — create a wave-file from template.
    wave_roles — map wave id → role.
    resolve_test_author_id — sole test-author wave id.
"""

from tripll.skw.render import (
    FRONTEND_STAGES,
    PLACEHOLDER_RE,
    VALID_STAGES,
    build_context,
    check_unfilled,
    load_prompt_template,
    render_frontend_prompt,
    render_prompt,
    render_wave_generator_prompt,
    topo_sort,
)
from tripll.skw.resolve_wave import (
    load_wave_data,
    resolve_test_author_id,
    test_author_ids,
    wave_role,
    wave_roles,
)
from tripll.skw.scaffold import scaffold_wave_file
from tripll.skw.validate import (
    KNOWN_AGENTS,
    VALID_EFFORTS,
    VALID_ROLES,
    extract_toml_block,
    find_bad_path_refs,
    load_skw_config,
    validate_wave_file,
)

__all__ = [
    "FRONTEND_STAGES",
    "KNOWN_AGENTS",
    "PLACEHOLDER_RE",
    "VALID_EFFORTS",
    "VALID_ROLES",
    "VALID_STAGES",
    "build_context",
    "check_unfilled",
    "extract_toml_block",
    "find_bad_path_refs",
    "load_prompt_template",
    "load_skw_config",
    "load_wave_data",
    "render_frontend_prompt",
    "render_prompt",
    "render_wave_generator_prompt",
    "resolve_test_author_id",
    "scaffold_wave_file",
    "test_author_ids",
    "topo_sort",
    "validate_wave_file",
    "wave_role",
    "wave_roles",
]
