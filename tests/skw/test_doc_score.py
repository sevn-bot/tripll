"""RED contract tests for ``skw.doc_score`` (D5). Green after W3.

Exports:
    test_score_weights_sum_to_one_hundred — component weights sum to 100.
    test_scaffold_body_scores_below_threshold — scaffold prose scores below 80.
    test_authored_spec_scores_at_or_above_threshold — authored spec scores at or above 80.
    test_status_honesty_component_penalizes_done_with_scaffold — status honesty penalizes done+scaffold.
    test_score_result_exposes_breakdown_and_rollup — score breakdown and rollup shape.

Examples:
    >>> from tests.skw._helpers import SCORE_THRESHOLD
    >>> SCORE_THRESHOLD
    80
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.skw._helpers import (
    SCORE_COMPONENTS,
    SCORE_THRESHOLD,
    SPEC_REQUIRED_SECTIONS,
    require_module,
)


def _score_weights(kind: str) -> dict[str, int]:
    """Load score weights for ``kind`` via the implementation module.

    Args:
        kind (str): ``"spec"`` or ``"prd"``.

    Returns:
        dict[str, int]: Component weights.

    Examples:
        >>> weights = _score_weights("spec")
        >>> sum(weights.values())
        100
    """
    doc_score = require_module("tripll.skw.doc_score")
    return doc_score.load_score_weights(kind)


def _score_doc(path: Path, *, kind: str, repo_root: Path, siblings: list[Path] | None = None):
    """Score one markdown doc via the implementation module.

    Args:
        path (Path): Markdown file to score.
        kind (str): ``"spec"`` or ``"prd"``.
        repo_root (Path): Repository root for resolution.
        siblings (list[Path] | None, optional): Sibling docs for id checks.

    Returns:
        ScoreResult: Weighted score breakdown.

    Examples:
        >>> _score_doc.__name__
        '_score_doc'
    """
    doc_score = require_module("tripll.skw.doc_score")
    return doc_score.score_doc(path, kind, repo_root=repo_root, siblings=siblings)


def _write_doc(
    directory: Path,
    *,
    kind: str,
    status: str,
    body: str,
    sources: list[str],
    interfaces: list[dict[str, str]] | None = None,
) -> Path:
    """Write a synthetic spec or PRD markdown file for scoring tests.

    Args:
        directory (Path): Output directory.
        kind (str): ``"spec"`` or ``"prd"``.
        status (str): Frontmatter status value.
        body (str): Markdown body after frontmatter.
        sources (list[str]): Frontmatter ``sources`` globs.
        interfaces (list[dict[str, str]] | None, optional): Spec interface rows.

    Returns:
        Path: Written markdown file path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     path = _write_doc(
        ...         Path(tmp),
        ...         kind="prd",
        ...         status="draft",
        ...         body="## Problem\\n",
        ...         sources=["Makefile"],
        ...     )
        ...     path.suffix
        '.md'
    """
    directory.mkdir(parents=True, exist_ok=True)
    if kind == "spec":
        doc_id = "spec-17-gateway"
        filename = "17-gateway.md"
        parent = "parent_prd: prd-01-conversational-experience"
        interface_block = ""
        if interfaces is None:
            interfaces = [
                {
                    "name": "run_turn",
                    "file": "src/sevn/gateway/agent_turn.py",
                    "symbol": "run_turn",
                }
            ]
        interface_block = "interfaces:\n" + "\n".join(
            f"  - name: {row['name']}\n    file: {row['file']}\n    symbol: {row['symbol']}"
            for row in interfaces
        )
    else:
        doc_id = "prd-01-conversational-experience"
        filename = "01-conversational-experience.md"
        parent = "parent_prd: null"
        interface_block = ""
    source_lines = "\n".join(f"  - {item}" for item in sources)
    text = f"""---
id: {doc_id}
kind: {kind}
title: Sample
status: {status}
owner: Alex
summary: Sample document for scoring.
last_updated: 2026-07-14
{parent}
sources:
{source_lines}
{interface_block}
fingerprint: sha256:abc
related: []
depends_on: []
---

{body}
"""
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("kind", ["spec", "prd"])
def test_score_weights_sum_to_one_hundred(kind: str) -> None:
    """D5: component weights in ``*-rules.toml [score]`` sum to 100.

    Args:
        kind (str): ``"spec"`` or ``"prd"``.

    Examples:
        >>> len(SCORE_COMPONENTS)
        6
    """
    weights = _score_weights(kind)
    assert set(weights) == set(SCORE_COMPONENTS)
    assert sum(weights.values()) == 100


def test_scaffold_body_scores_below_threshold(repo_root: Path, tmp_path: Path) -> None:
    """D5: scaffold placeholder prose must score below the 80 threshold.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> SCORE_THRESHOLD
        80
    """
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nOffline scaffold for gateway." for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="scaffold",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    result = _score_doc(
        path, kind="spec", repo_root=repo_root, siblings=list(docs_dir.glob("*.md"))
    )
    assert result.total < SCORE_THRESHOLD
    assert result.components["no_scaffold_phrase"] == 0


def test_authored_spec_scores_at_or_above_threshold(repo_root: Path, tmp_path: Path) -> None:
    """D5: fully authored, resolving spec scores >= 80.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> SCORE_THRESHOLD >= 80
        True
    """
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nAuthored prose for {heading.lower()}."
        for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="done",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    result = _score_doc(
        path, kind="spec", repo_root=repo_root, siblings=list(docs_dir.glob("*.md"))
    )
    assert result.total >= SCORE_THRESHOLD


def test_status_honesty_component_penalizes_done_with_scaffold(
    repo_root: Path, tmp_path: Path
) -> None:
    """D5: ``status_honesty`` component fails when ``done`` overlays scaffold prose.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> "status_honesty" in SCORE_COMPONENTS
        True
    """
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nInitial draft for gateway." for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="done",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    result = _score_doc(
        path, kind="spec", repo_root=repo_root, siblings=list(docs_dir.glob("*.md"))
    )
    assert result.components["status_honesty"] == 0
    assert result.total < SCORE_THRESHOLD


def test_score_result_exposes_breakdown_and_rollup(repo_root: Path, tmp_path: Path) -> None:
    """D5: scorer returns per-component breakdown and folder rollup helper.

    Args:
        repo_root (Path): Minimal repo fixture with gateway module.
        tmp_path (Path): Temporary directory for test docs.

    Examples:
        >>> len(SCORE_COMPONENTS)
        6
    """
    doc_score = require_module("tripll.skw.doc_score")
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(f"## {heading}\n\nAuthored prose." for heading in SPEC_REQUIRED_SECTIONS)
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="done",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    siblings = list(docs_dir.glob("*.md"))
    one = _score_doc(path, kind="spec", repo_root=repo_root, siblings=siblings)
    assert set(one.components) == set(SCORE_COMPONENTS)
    assert isinstance(one.total, int)
    rollup = doc_score.rollup_scores([one])
    assert rollup["file_count"] == 1
    assert rollup["average_total"] == one.total
    assert rollup["below_threshold"] == []
