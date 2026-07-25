"""RED contract tests for changelog Unreleased datestamps (D10). Green after W6.

Exports:
    test_rules_require_leading_datestamp_pattern — rules require datestamp pattern.
    test_unreleased_bullet_without_datestamp_fails — missing datestamp fails lint.
    test_unreleased_bullet_with_valid_datestamp_passes — valid datestamp passes lint.
    test_released_section_bullets_unaffected_by_datestamp_rule — released bullets exempt.
    test_datestamp_interacts_with_no_trailing_period_rule — datestamp + no-period rule.
    test_datestamp_interacts_with_issue_ref_rule — datestamp + issue ref rule.
    test_optional_time_suffix_allowed_by_pattern — optional time suffix allowed.

Examples:
    >>> DATESTAMP
    '[2026-07-14]'
"""

from __future__ import annotations

from tests.skw._helpers import require_module

UNRELEASED_HEADING = "Unreleased"
DATESTAMP = "[2026-07-14]"


def _rules_with_datestamp() -> dict:
    """Load changelog rules and assert datestamp enforcement is enabled.

    Returns:
        dict: Merged changelog rules with ``require_datestamp`` enabled.

    Examples:
        >>> rules = _rules_with_datestamp()
        >>> rules["entry"]["require_datestamp"]
        True
    """
    changelog_validate = require_module("tripll.skw.changelog_validate")
    rules = changelog_validate.load_changelog_rules()
    entry = rules["entry"]
    assert entry.get("require_datestamp") is True
    assert "datestamp_pattern" in entry
    return rules


def _lint_unreleased(text: str) -> tuple[list[str], list[str]]:
    """Lint only the Unreleased section of a changelog document.

    Args:
        text (str): Full changelog markdown text.

    Returns:
        tuple[list[str], list[str]]: ``(errors, warnings)`` for Unreleased rows.

    Examples:
        >>> errors, warnings = _lint_unreleased(_changelog(f"{DATESTAMP} Added retry"))
        >>> errors == []
        True
    """
    changelog_validate = require_module("tripll.skw.changelog_validate")
    rules = _rules_with_datestamp()
    parsed = changelog_validate.parse_changelog(text)
    version = next(v for v in parsed["versions"] if v["name"] == UNRELEASED_HEADING)
    return changelog_validate.lint_entries(version, rules)


def _changelog(*bullets: str, released_bullet: str | None = None) -> str:
    """Build a minimal Keep-a-Changelog document for tests.

    Args:
        bullets (str): Unreleased Added bullet bodies (variadic).
        released_bullet (str | None, optional): Optional released-section bullet.

    Returns:
        str: Changelog markdown text.

    Examples:
        >>> "## [Unreleased]" in _changelog("entry")
        True
    """
    released = ""
    if released_bullet is not None:
        released = f"""
## [0.0.1] - 2026-01-01

### Added

- {released_bullet}
"""
    body = "\n".join(f"- {bullet}" for bullet in bullets)
    return f"""# Changelog

## [{UNRELEASED_HEADING}]

### Added

{body}
{released}
"""


def test_rules_require_leading_datestamp_pattern() -> None:
    """D10: ``changelog-rules.toml [entry]`` enables datestamp enforcement.

    Examples:
        >>> DATESTAMP.startswith("[")
        True
    """
    rules = _rules_with_datestamp()
    pattern = rules["entry"]["datestamp_pattern"]
    assert pattern.startswith("^\\[")
    assert "require_datestamp" in rules["entry"]


def test_unreleased_bullet_without_datestamp_fails() -> None:
    """D10: Unreleased bullets without a leading ``[YYYY-MM-DD]`` stamp fail lint.

    Examples:
        >>> UNRELEASED_HEADING
        'Unreleased'
    """
    text = _changelog("New `--retry` flag on `sevn onboard`")
    errors, _warnings = _lint_unreleased(text)
    assert errors
    assert any("datestamp" in err.lower() or "[" in err for err in errors)


def test_unreleased_bullet_with_valid_datestamp_passes() -> None:
    """D10: leading ``[YYYY-MM-DD]`` datestamp satisfies the Unreleased rule.

    Examples:
        >>> DATESTAMP.count("-")
        2
    """
    text = _changelog(f"{DATESTAMP} New `--retry` flag on `sevn onboard`")
    errors, _warnings = _lint_unreleased(text)
    assert errors == []


def test_released_section_bullets_unaffected_by_datestamp_rule() -> None:
    """D10: released-version bullets remain exempt from datestamp enforcement.

    Examples:
        >>> "0.0.1" in "0.0.1"
        True
    """
    text = _changelog(
        f"{DATESTAMP} Current unreleased entry",
        released_bullet="Legacy entry without a datestamp",
    )
    changelog_validate = require_module("tripll.skw.changelog_validate")
    rules = _rules_with_datestamp()
    parsed = changelog_validate.parse_changelog(text)
    released = next(v for v in parsed["versions"] if v["name"] == "0.0.1")
    errors, _warnings = changelog_validate.lint_entries(released, rules)
    assert errors == []


def test_datestamp_interacts_with_no_trailing_period_rule() -> None:
    """D10 + existing rules: stamp precedes sentence-case body; trailing period still forbidden.

    Examples:
        >>> "Added retry support.".endswith(".")
        True
    """
    text = _changelog(f"{DATESTAMP} Added retry support.")
    errors, _warnings = _lint_unreleased(text)
    assert any("period" in err.lower() for err in errors)


def test_datestamp_interacts_with_issue_ref_rule() -> None:
    """D10 + existing rules: ``(#123)`` refs remain valid after the leading stamp.

    Examples:
        >>> "(#123)" in "Added retry support (#123)"
        True
    """
    text = _changelog(f"{DATESTAMP} Added retry support (#123)")
    errors, warnings = _lint_unreleased(text)
    assert errors == []
    assert not any("(#123)" in err for err in errors)
    assert not any("(#123)" in warn for warn in warnings)


def test_optional_time_suffix_allowed_by_pattern() -> None:
    """D10: ``YYYY-MM-DDTHH:MMZ`` suffix is allowed though date-only is the default.

    Examples:
        >>> "[2026-07-14T12:00Z]".endswith("Z]")
        True
    """
    text = _changelog("[2026-07-14T12:00Z] Added retry support")
    errors, _warnings = _lint_unreleased(text)
    assert errors == []
