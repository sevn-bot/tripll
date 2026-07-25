"""Tests for verifier-setup prompt rendering."""

from __future__ import annotations

from pathlib import Path

from tripll.skw.render import (
    VERIFIER_SETUP_STAGE,
    build_verifier_setup_context,
    check_unfilled,
    render_verifier_setup_prompt,
)


def test_verifier_setup_stage_in_render_stages() -> None:
    from tripll.skw.render import RENDER_STAGES

    assert VERIFIER_SETUP_STAGE in RENDER_STAGES


def test_build_verifier_setup_context_defaults(kit_root: Path) -> None:
    ctx = build_verifier_setup_context(kit_root, repo_root=kit_root.parent)
    assert ctx["SKILL_PATH"].endswith("skills/verifier-setup/SKILL.md")
    assert "verify.template.md" in ctx["TEMPLATE_PATH"]
    assert ctx["CONTEXT_BLOCK"] == "(none provided)"
    assert ctx["PATHS_BLOCK"] == "(none)"


def test_render_verifier_setup_prompt_no_placeholders(kit_root: Path) -> None:
    rendered = render_verifier_setup_prompt(kit_root, repo_root=kit_root.parent)
    assert check_unfilled(rendered) == []
    assert "verifier-setup" in rendered
    assert "make compose-up" in rendered
