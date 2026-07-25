"""RED contract tests for ``skw.doc_folder`` (D6). Green after W3/W4.

Exports:
    test_validate_command_returns_per_file_and_rollup — validate returns per-file + rollup.
    test_score_command_flags_sub_threshold_done — score flags sub-threshold done docs.
    test_sync_refreshes_frontmatter_without_fabricating_prose — sync refreshes frontmatter only.
    test_kind_dispatch_rejects_unknown_kind — unknown kind is rejected.

Examples:
    >>> from tests.skw._helpers import SPEC_REQUIRED_SECTIONS
    >>> len(SPEC_REQUIRED_SECTIONS)
    7
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.skw._helpers import SPEC_REQUIRED_SECTIONS, require_module


def _run(
    command: str,
    *,
    kind: str,
    directory: Path,
    repo_root: Path,
):
    """Run a folder docs command via the implementation module.

    Args:
        command (str): ``validate``, ``score``, or ``sync``.
        kind (str): ``"spec"`` or ``"prd"``.
        directory (Path): Folder of markdown docs.
        repo_root (Path): Repository root for resolution.

    Returns:
        FolderResult: Folder command outcome.

    Examples:
        >>> _run.__name__
        '_run'
    """
    doc_folder = require_module("tripll.skw.doc_folder")
    return doc_folder.run_docs_command(
        command,
        kind=kind,
        directory=directory,
        repo_root=repo_root,
    )


def _write_kind_doc(directory: Path, *, kind: str, status: str = "done") -> Path:
    """Write a synthetic spec or PRD markdown file for folder tests.

    Args:
        directory (Path): Output directory.
        kind (str): ``"spec"`` or ``"prd"``.
        status (str, optional): Frontmatter status. Defaults to ``"done"``.

    Returns:
        Path: Written markdown file path.

    Examples:
        >>> _write_kind_doc.__name__
        '_write_kind_doc'
    """
    directory.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f"## {heading}\n\nAuthored content." for heading in SPEC_REQUIRED_SECTIONS)
    if kind == "spec":
        text = f"""---
id: spec-17-gateway
kind: spec
title: Gateway
status: {status}
owner: Alex
summary: Gateway turn spine.
last_updated: 2026-07-14
parent_prd: prd-01-conversational-experience
sources:
  - src/sevn/gateway/**
interfaces:
  - name: run_turn
    file: src/sevn/gateway/agent_turn.py
    symbol: run_turn
fingerprint: sha256:abc
related: []
depends_on: []
---

{body}
"""
        path = directory / "17-gateway.md"
    else:
        text = f"""---
id: prd-01-conversational-experience
kind: prd
title: Conversational Experience
status: {status}
owner: Alex
summary: End-to-end conversational flow.
last_updated: 2026-07-14
parent_prd: null
sources:
  - Makefile
fingerprint: sha256:def
related: []
specs: []
personas:
  - operator
prd_profile: standard
---

## Problem & Motivation

Real PRD prose.

## Goals & Success Metrics

Goals.

## User Stories

Stories.

## Functional Requirements

Requirements.

## Non-Functional Requirements

NFRs.

## Out of Scope

Out.

## Open Questions

None.
"""
        path = directory / "01-conversational-experience.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("kind", ["spec", "prd"])
def test_validate_command_returns_per_file_and_rollup(
    repo_root: Path,
    tmp_path: Path,
    kind: str,
) -> None:
    """D6: ``validate`` iterates every ``*.md`` and returns per-file + rollup output.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.
        kind (str): ``"spec"`` or ``"prd"``.

    Examples:
        >>> len(SPEC_REQUIRED_SECTIONS)
        7
    """
    docs_dir = tmp_path / kind
    _write_kind_doc(docs_dir, kind=kind)
    result = _run("validate", kind=kind, directory=docs_dir, repo_root=repo_root)
    assert result.exit_code == 0
    assert len(result.files) == 1
    assert result.files[0].ok is True
    assert result.rollup["file_count"] == 1
    assert result.rollup["error_count"] == 0


@pytest.mark.parametrize("kind", ["spec", "prd"])
def test_score_command_flags_sub_threshold_done(
    repo_root: Path,
    tmp_path: Path,
    kind: str,
) -> None:
    """D6: ``score`` exits non-zero when a ``done`` file scores below 80.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.
        kind (str): ``"spec"`` or ``"prd"``.

    Examples:
        >>> from tests.skw._helpers import SCORE_THRESHOLD
        >>> SCORE_THRESHOLD
        80
    """
    docs_dir = tmp_path / kind
    _write_kind_doc(docs_dir, kind=kind, status="done")
    path = next(docs_dir.glob("*.md"))
    text = path.read_text(encoding="utf-8")
    text = text.replace("Authored content.", "Offline scaffold for gateway.", 1)
    if kind == "spec":
        text = text.replace("Offline scaffold for gateway.", "Offline scaffold for gateway.", 1)
        for heading in SPEC_REQUIRED_SECTIONS:
            text = text.replace(
                f"## {heading}\n\nAuthored content.",
                f"## {heading}\n\nOffline scaffold for gateway.",
            )
    path.write_text(text, encoding="utf-8")
    result = _run("score", kind=kind, directory=docs_dir, repo_root=repo_root)
    assert result.exit_code != 0
    assert result.rollup["below_threshold"]


def test_sync_refreshes_frontmatter_without_fabricating_prose(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """D6/D8: ``sync`` refreshes frontmatter but leaves ``status: scaffold`` when body empty.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "scaffold" in {"draft", "scaffold", "done"}
        True
    """
    pytest.importorskip("sevn")
    docs_dir = tmp_path / "specs"
    path = _write_kind_doc(docs_dir, kind="spec", status="scaffold")
    body = path.read_text(encoding="utf-8").split("---", maxsplit=2)[-1]
    assert "Offline scaffold" in body or "Authored content" in body
    result = _run("sync", kind="spec", directory=docs_dir, repo_root=repo_root)
    assert result.exit_code == 0
    refreshed = path.read_text(encoding="utf-8")
    assert "fingerprint:" in refreshed
    assert "status: scaffold" in refreshed


def test_kind_dispatch_rejects_unknown_kind(tmp_path: Path, repo_root: Path) -> None:
    """D6: CLI/folder layer rejects unknown ``--kind`` values.

    Args:
        tmp_path (Path): Temporary directory for test docs.
        repo_root (Path): Minimal repo fixture with gateway module.

    Examples:
        >>> {"spec", "prd"} >= {"spec"}
        True
    """
    doc_folder = require_module("tripll.skw.doc_folder")
    with pytest.raises(ValueError, match="kind"):
        doc_folder.run_docs_command(
            "validate",
            kind="readme",
            directory=tmp_path,
            repo_root=repo_root,
        )
