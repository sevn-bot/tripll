"""Tests for code factory L1 agent roster (Wave W11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.graphstore.task_sync import hash_agent_def
from tripll.skw.doc_score import SCORE_THRESHOLD, score_doc

REPO_ROOT = Path(__file__).resolve().parents[1]
SKW_AGENTS = REPO_ROOT / "src" / "tripll" / "skw" / "agents"
DOCS_AGENTS = REPO_ROOT / "docs" / "agents"
SRC_TRIPLL = REPO_ROOT / "src" / "tripll"

# Design §11 roster — every contract must have a skw brief.
SECTION_11_AGENTS = frozenset(
    {
        "spec-cartographer",
        "graph-extractor",
        "graph-librarian",
        "graph-fuser",
        "plan-author",
        "plan-shape-critic",
        "test-creator",
        "implementer",
        "wave-verifier",
        "ci-investigator",
        "check-fixer",
        "review-comment-triager",
        "review-comment-fixer",
        "pr-shepherd",
    }
)

PORTED_AGENTS = frozenset(
    {
        "wayfinder",
        "specify",
        "clarify",
        "plan",
        "prd-author",
        "docs-folder-author",
        "changelog-author",
        "changelog-reviewer",
        "reviewer",
        "post-review-wave-generator",
        "pr-verifier",
        "github-issue-triage",
        "verifier-setup",
    }
)

REQUIRED_SECTIONS = ("guardrails", "done", "Inherited harness")


@pytest.mark.parametrize("slug", sorted(SECTION_11_AGENTS))
def test_section_11_skw_brief_exists(slug: str) -> None:
    path = SKW_AGENTS / f"{slug}.md"
    assert path.is_file(), f"missing skw brief: {path}"


@pytest.mark.parametrize("slug", sorted(SECTION_11_AGENTS))
def test_section_11_skw_brief_has_contract_sections(slug: str) -> None:
    text = (SKW_AGENTS / f"{slug}.md").read_text(encoding="utf-8").lower()
    for section in REQUIRED_SECTIONS:
        assert section.lower() in text, f"{slug}.md missing {section!r}"


@pytest.mark.parametrize("slug", sorted(SECTION_11_AGENTS - {"test-creator"}))
def test_section_11_docs_entry_exists(slug: str) -> None:
    path = DOCS_AGENTS / f"{slug}.md"
    assert path.is_file(), f"missing docs/agents entry: {path}"


@pytest.mark.parametrize("slug", sorted(SECTION_11_AGENTS))
@pytest.mark.xfail(reason="green after W2: hash sourced from skw/agents only", strict=False)
def test_section_11_hash_agent_def_from_skw(slug: str) -> None:
    skw_path = SKW_AGENTS / f"{slug}.md"
    assert skw_path.is_file(), f"missing skw brief: {skw_path}"
    info = hash_agent_def(slug, REPO_ROOT)
    assert info is not None, f"hash_agent_def returned None for {slug}"
    _node_id, _natural_key, digest = info
    assert len(digest) >= 16


@pytest.mark.xfail(reason="green after W2: no .cursor/agents references in src", strict=False)
def test_no_source_py_references_cursor_agents() -> None:
    offenders: list[str] = []
    for path in SRC_TRIPLL.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ".cursor/agents" in text or '".cursor" / "agents"' in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


@pytest.mark.parametrize("slug", sorted(PORTED_AGENTS))
def test_ported_agents_have_inherited_harness(slug: str) -> None:
    text = (SKW_AGENTS / f"{slug}.md").read_text(encoding="utf-8")
    assert "Inherited harness" in text, f"ported agent {slug} missing inherited harness"


def test_spec_cartographer_e2e_doc_section() -> None:
    doc = (DOCS_AGENTS / "spec-cartographer.md").read_text(encoding="utf-8")
    assert "E2E proof" in doc
    assert "spec_cartographer_mini" in doc


def test_spec_cartographer_fixture_passes_spec_check() -> None:
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "spec_cartographer_mini"
    spec_path = fixture_root / "spec" / "calc-module.md"
    assert spec_path.is_file()
    result = score_doc(spec_path, kind="spec", repo_root=fixture_root)
    assert result.total >= SCORE_THRESHOLD, (
        f"fixture spec score {result.total} < {SCORE_THRESHOLD}: {result.components}"
    )
