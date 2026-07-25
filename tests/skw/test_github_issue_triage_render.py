"""Tests for github-issue-triage prompt rendering."""

from __future__ import annotations

from pathlib import Path

from tripll.skw.render import (
    GITHUB_ISSUE_TRIAGE_STAGE,
    build_github_issue_triage_context,
    check_unfilled,
    render_github_issue_triage_prompt,
)


def test_github_issue_triage_stage_in_render_stages() -> None:
    from tripll.skw.render import RENDER_STAGES

    assert GITHUB_ISSUE_TRIAGE_STAGE in RENDER_STAGES


def test_build_github_issue_triage_context_issue_scope(kit_root: Path) -> None:
    ctx = build_github_issue_triage_context(
        kit_root,
        repo_root=kit_root.parent,
        issue_number="21",
    )
    assert ctx["SKILL_PATH"].endswith("skills/github-issue-triage/SKILL.md")
    assert "triage-policy.md" in ctx["POLICY_PATH"]
    assert "issue #21" in ctx["SCOPE_BLOCK"]
    assert ctx["CONTEXT_BLOCK"] == "(none provided)"


def test_build_github_issue_triage_context_queue_scope(kit_root: Path) -> None:
    ctx = build_github_issue_triage_context(
        kit_root,
        repo_root=kit_root.parent,
        queue_all=True,
    )
    assert "full open issue queue" in ctx["SCOPE_BLOCK"]


def test_render_github_issue_triage_prompt_no_placeholders(kit_root: Path) -> None:
    rendered = render_github_issue_triage_prompt(
        kit_root,
        repo_root=kit_root.parent,
        issue_number="21",
    )
    assert check_unfilled(rendered) == []
    assert "github-issue-triage" in rendered
    assert "fetch_open_issues.py" in rendered
