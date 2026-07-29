"""Derived rules against foreign fixture repos (W1.2, R32)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.rules._helpers import require_attr

pytest_plugins = ["tests.rules._helpers"]
pytestmark = pytest.mark.tier1


def test_derive_writes_rules_with_resolving_origins(
    rules_foreign_repo: Path,
) -> None:
    """Every derived rule cites a codebase:// file:line that resolves (R26, R32)."""
    derive_rules = require_attr("tripll.rules.derive", "derive_rules")
    result = derive_rules(rules_foreign_repo)
    rules_dir = rules_foreign_repo / ".tripll" / "rules"
    written = (
        result.rules_written if hasattr(result, "rules_written") else list(rules_dir.glob("*.md"))
    )
    assert written, "derive must emit at least one rule for stdlib logging fixture"

    bad: list[str] = []
    for path in written:
        text = Path(path).read_text(encoding="utf-8")
        match = re.search(r"^origin:\s*codebase://(.+):(\d+)", text, re.MULTILINE)
        assert match, f"{path}: missing codebase origin"
        rel, line_s = match.group(1), match.group(2)
        target = rules_foreign_repo / rel
        if not target.is_file():
            bad.append(str(path))
            continue
        if len(target.read_text(encoding="utf-8").splitlines()) < int(line_s):
            bad.append(str(path))
    assert not bad, f"unresolving origins: {bad}"


def test_derive_repo_without_tests_says_so_not_coverage_standard(
    rules_foreign_repo_no_tests: Path,
) -> None:
    """R32: no invented coverage standard — artifact states absence of unit tests."""
    derive_rules = require_attr("tripll.rules.derive", "derive_rules")
    derive_rules(rules_foreign_repo_no_tests)

    rules_dir = rules_foreign_repo_no_tests / ".tripll" / "rules"
    context_dir = rules_foreign_repo_no_tests / ".tripll" / "context"
    blobs = []
    if rules_dir.is_dir():
        blobs.extend(p.read_text(encoding="utf-8") for p in rules_dir.glob("*.md"))
    if context_dir.is_dir():
        blobs.extend(p.read_text(encoding="utf-8") for p in context_dir.glob("*.md"))
    combined = "\n".join(blobs).lower()
    assert "no unit test" in combined or "no tests" in combined
    assert "coverage" not in combined
    assert "pytest --cov" not in combined
