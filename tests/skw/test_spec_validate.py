"""RED contract tests for ``skw.spec_validate`` (D2-D4). Green after W2.

Exports:
    test_spec_rules_status_enum_excludes_ready — spec status enum excludes ready.
    test_spec_rules_required_sections_are_seven — seven required H2 sections.
    test_missing_frontmatter_key_errors — missing frontmatter keys error.
    test_missing_required_section_errors — missing required sections error.
    test_scaffold_phrase_forbidden_when_done — scaffold phrase forbidden when done.
    test_duplicate_numeric_id_rejected — duplicate numeric id rejected.
    test_invalid_id_pattern_rejected — invalid id pattern rejected.
    test_unresolved_interface_errors — unresolved interface errors.
    test_whole_repo_sources_glob_rejected — whole-repo sources glob rejected.
    test_valid_authored_spec_passes — valid authored spec passes.
    test_json_output_shape — JSON output shape contract.

Examples:
    >>> len(SPEC_REQUIRED_SECTIONS)
    7
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.skw._helpers import (
    SPEC_REQUIRED_SECTIONS,
    SPEC_STATUS_ENUM,
    require_module,
)


def _rules() -> dict:
    """Load merged spec validation rules.

    Returns:
        dict: Merged rules from ``spec-rules.toml``.

    Examples:
        >>> rules = _rules()
        >>> "frontmatter" in rules
        True
    """
    spec_validate = require_module("tripll.skw.spec_validate")
    return spec_validate.load_spec_rules()


def _validate(path: Path, *, repo_root: Path, siblings: list[Path] | None = None) -> dict:
    """Validate one spec file via the implementation module.

    Args:
        path (Path): Spec markdown file.
        repo_root (Path): Repository root for interface resolution.
        siblings (list[Path] | None, optional): Sibling specs in the folder.

    Returns:
        dict: Validation report with ``ok``, ``errors``, and ``warnings``.

    Examples:
        >>> _validate.__name__
        '_validate'
    """
    spec_validate = require_module("tripll.skw.spec_validate")
    return spec_validate.validate_spec_file(
        path,
        repo_root=repo_root,
        siblings=siblings,
    )


def _write_spec(
    directory: Path,
    *,
    doc_id: str = "spec-17-gateway",
    filename: str = "17-gateway.md",
    status: str = "done",
    sources: list[str] | None = None,
    interfaces: list[dict[str, str]] | None = None,
    body: str | None = None,
    fingerprint: str = "sha256:abc",
) -> Path:
    """Write a synthetic spec markdown file for validation tests.

    Args:
        directory (Path): Output directory.
        doc_id (str, optional): Frontmatter id. Defaults to ``spec-17-gateway``.
        filename (str, optional): Output filename. Defaults to ``17-gateway.md``.
        status (str, optional): Frontmatter status. Defaults to ``done``.
        sources (list[str] | None, optional): Frontmatter sources globs.
        interfaces (list[dict[str, str]] | None, optional): Interface rows.
        body (str | None, optional): Markdown body. Defaults to seven sections.
        fingerprint (str, optional): Frontmatter fingerprint. Defaults to placeholder.

    Returns:
        Path: Written markdown file path.

    Examples:
        >>> _write_spec.__name__
        '_write_spec'
    """
    directory.mkdir(parents=True, exist_ok=True)
    if sources is None:
        sources = ["src/sevn/gateway/**"]
    if interfaces is None:
        interfaces = [
            {
                "name": "run_turn",
                "file": "src/sevn/gateway/agent_turn.py",
                "symbol": "run_turn",
            }
        ]
    if body is None:
        sections = "\n\n".join(
            f"## {heading}\n\nAuthored content for {heading}." for heading in SPEC_REQUIRED_SECTIONS
        )
        body = sections
    interface_lines = "\n".join(
        f"  - name: {row['name']}\n    file: {row['file']}\n    symbol: {row.get('symbol', row['name'])}"
        for row in interfaces
    )
    if len(sources) == 1:
        sources_block = f"sources: {sources[0]}"
    else:
        source_lines = "\n".join(f"  - {item}" for item in sources)
        sources_block = f"sources:\n{source_lines}"
    text = f"""---
id: {doc_id}
kind: spec
title: Gateway
status: {status}
owner: Alex
summary: Gateway turn spine.
last_updated: 2026-07-14
parent_prd: prd-01-conversational-experience
{sources_block}
interfaces:
{interface_lines}
fingerprint: {fingerprint}
related: []
depends_on: []
---

{body}
"""
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return path


def test_spec_rules_status_enum_excludes_ready() -> None:
    """D3: ``kind: spec`` status vocabulary has no ``ready``.

    Examples:
        >>> "ready" not in SPEC_STATUS_ENUM
        True
    """
    rules = _rules()
    status_enum = set(rules["frontmatter"]["status_enum"])
    assert status_enum == SPEC_STATUS_ENUM
    assert "ready" not in status_enum


def test_spec_rules_required_sections_are_seven() -> None:
    """D3: committed about-sevn.bot spec format uses seven H2 sections.

    Examples:
        >>> len(SPEC_REQUIRED_SECTIONS)
        7
    """
    rules = _rules()
    required = list(rules["sections"]["required"])
    assert required == list(SPEC_REQUIRED_SECTIONS)


@pytest.mark.parametrize("missing", ["fingerprint", "sources", "parent_prd"])
def test_missing_frontmatter_key_errors(
    repo_root: Path,
    tmp_path: Path,
    missing: str,
) -> None:
    """D4: required frontmatter keys must be present.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.
        missing (str): Required key to remove from frontmatter.

    Examples:
        >>> {"fingerprint", "sources", "parent_prd"} >= {"sources"}
        True
    """
    specs_dir = tmp_path / "specs"
    path = _write_spec(specs_dir)
    text = path.read_text(encoding="utf-8")
    text = text.replace(f"{missing}: ", f"# removed {missing}: ", 1)
    path.write_text(text, encoding="utf-8")
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is False
    assert any(missing in err for err in result["errors"])


def test_missing_required_section_errors(repo_root: Path, tmp_path: Path) -> None:
    """D3: all seven required sections must be present.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "Behavior" in SPEC_REQUIRED_SECTIONS
        True
    """
    specs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nContent." for heading in SPEC_REQUIRED_SECTIONS if heading != "Behavior"
    )
    path = _write_spec(specs_dir, body=body)
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is False
    assert any("Behavior" in err or "section" in err.lower() for err in result["errors"])


def test_scaffold_phrase_forbidden_when_done(repo_root: Path, tmp_path: Path) -> None:
    """D3: ``status: done`` cannot coexist with scaffold phrases.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "done" in SPEC_STATUS_ENUM
        True
    """
    specs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nOffline scaffold for gateway." for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_spec(specs_dir, status="done", body=body)
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is False
    assert any("scaffold" in err.lower() for err in result["errors"])


def test_duplicate_numeric_id_rejected(repo_root: Path, tmp_path: Path) -> None:
    """D4: folder-scoped id uniqueness catches duplicate ``spec-29-*`` ids.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "29" in "spec-29-cursor-cloud-agent"
        True
    """
    specs_dir = tmp_path / "specs"
    first = _write_spec(
        specs_dir,
        doc_id="spec-29-cursor-cloud-agent",
        filename="29-cursor-cloud-agent.md",
    )
    second = _write_spec(
        specs_dir,
        doc_id="spec-29-openui",
        filename="29-openui.md",
    )
    siblings = list(specs_dir.glob("*.md"))
    first_result = _validate(first, repo_root=repo_root, siblings=siblings)
    assert first_result["ok"] is False
    assert any(
        "29" in err and ("unique" in err.lower() or "duplicate" in err.lower())
        for err in first_result["errors"]
    )
    second_result = _validate(second, repo_root=repo_root, siblings=siblings)
    assert second_result["ok"] is False


def test_invalid_id_pattern_rejected(repo_root: Path, tmp_path: Path) -> None:
    """D4: ``id`` must match ``^spec-\\d{{2}}-[a-z0-9-]+$``.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "spec-17-gateway".startswith("spec-")
        True
    """
    specs_dir = tmp_path / "specs"
    path = _write_spec(specs_dir, doc_id="spec-gateway", filename="gateway.md")
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is False
    assert any("id" in err.lower() for err in result["errors"])


def test_unresolved_interface_errors(repo_root: Path, tmp_path: Path) -> None:
    """D4: ``interfaces[].{{file,symbol}}`` must resolve to real code.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> {"file", "symbol"} <= {"name", "file", "symbol"}
        True
    """
    specs_dir = tmp_path / "specs"
    path = _write_spec(
        specs_dir,
        interfaces=[
            {
                "name": "missing_fn",
                "file": "src/sevn/gateway/missing.py",
                "symbol": "missing_fn",
            }
        ],
    )
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is False
    assert any("interface" in err.lower() or "missing" in err.lower() for err in result["errors"])


def test_whole_repo_sources_glob_rejected(repo_root: Path, tmp_path: Path) -> None:
    """D4: ``sources`` must not be the whole-repo ``src/sevn/**`` dump.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "src/sevn/**".endswith("/**")
        True
    """
    specs_dir = tmp_path / "specs"
    path = _write_spec(specs_dir, sources=["src/sevn/**"])
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is False
    assert any("src/sevn/**" in err or "whole" in err.lower() for err in result["errors"])


def test_valid_authored_spec_passes(repo_root: Path, tmp_path: Path) -> None:
    """Happy path: fully authored spec with resolving interfaces passes.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> len(SPEC_REQUIRED_SECTIONS) == 7
        True
    """
    specs_dir = tmp_path / "specs"
    path = _write_spec(specs_dir)
    result = _validate(path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md")))
    assert result["ok"] is True
    assert result["errors"] == []


def test_json_output_shape(repo_root: Path, tmp_path: Path) -> None:
    """W2: ``--json`` report exposes ``ok``, ``errors``, ``warnings``, ``path``.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> set(["ok", "errors", "warnings", "path"]) >= {"ok"}
        True
    """
    spec_validate = require_module("tripll.skw.spec_validate")
    specs_dir = tmp_path / "specs"
    path = _write_spec(specs_dir)
    payload = spec_validate.validate_spec_file_json(
        path, repo_root=repo_root, siblings=list(specs_dir.glob("*.md"))
    )
    raw = json.dumps(payload)
    parsed = json.loads(raw)
    assert parsed["ok"] is True
    assert parsed["path"].endswith("17-gateway.md")
    assert isinstance(parsed["errors"], list)
    assert isinstance(parsed["warnings"], list)
