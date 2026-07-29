"""Rule model — frontmatter schema, lifecycle states, origin validation (W2.1).

Exports:
    RULE_STATES — valid lifecycle states.
    Rule — durable repo-scoped constraint dataclass.
    OriginValidationError — raised when an origin ref does not resolve.
    parse_rule_markdown — parse a rule markdown file into a :class:`Rule`.
    render_rule_markdown — render a :class:`Rule` to committed markdown.
    validate_origin — verify a ``codebase://`` or ``finding://`` origin ref.
    validate_rule — full rule validation including mandatory origin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — runtime origin resolution

from tripll.skw.prd_validate import parse_frontmatter

__all__ = [
    "RULE_STATES",
    "OriginValidationError",
    "Rule",
    "parse_rule_markdown",
    "render_rule_markdown",
    "validate_origin",
    "validate_rule",
]

RULE_STATES = frozenset({"proposed", "active", "retired"})

_CODEBASE_ORIGIN_RE = re.compile(r"^codebase://(.+):(\d+)$")
_FINDING_ORIGIN_RE = re.compile(r"^finding://([^#]+)#(.+)$")


class OriginValidationError(ValueError):
    """Raised when a rule origin reference does not resolve."""


@dataclass
class Rule:
    """A durable, repo-scoped constraint with provenance.

    Args:
        rule_id (str): Stable slug identifier.
        state (str): ``proposed``, ``active``, or ``retired``.
        origin (str): ``codebase://<file>:<line>`` or ``finding://<run>#<id>``.
        scope (list[str]): Glob patterns describing where the rule applies.
        body (str): Prose constraint markdown (after frontmatter).
        executable (str | None): Executable backend hint (``ast-grep``) when set.
        severity (str | None): Violation severity when executable.
        pattern (str | None): Structural ``ast-grep`` pattern when executable (W4).
    """

    rule_id: str
    state: str
    origin: str
    scope: list[str] = field(default_factory=list)
    body: str = ""
    executable: str | None = None
    severity: str | None = None
    pattern: str | None = None


def parse_rule_markdown(text: str) -> Rule:
    """Parse rule markdown with YAML frontmatter into a :class:`Rule`.

    Args:
        text (str): Full rule file contents.

    Returns:
        Rule: Parsed rule (origin may be empty — call :func:`validate_rule`).

    Raises:
        ValueError: When frontmatter is missing or required keys are absent.

    Examples:
        >>> raw = "---\\nrule_id: r1\\nstate: active\\norigin: codebase://a.py:1\\n---\\n\\nBody"
        >>> parse_rule_markdown(raw).rule_id
        'r1'
    """
    meta, body, error = parse_frontmatter(text)
    if error:
        msg = f"rule frontmatter: {error}"
        raise ValueError(msg)
    rule_id = meta.get("rule_id")
    state = meta.get("state")
    if not isinstance(rule_id, str) or not rule_id.strip():
        msg = "rule frontmatter missing rule_id"
        raise ValueError(msg)
    if not isinstance(state, str) or state not in RULE_STATES:
        msg = f"rule state must be one of {sorted(RULE_STATES)!r}, got {state!r}"
        raise ValueError(msg)
    origin = meta.get("origin")
    origin_str = str(origin).strip() if origin is not None else ""
    scope_raw = meta.get("scope")
    scope: list[str] = []
    if isinstance(scope_raw, list):
        scope = [str(item) for item in scope_raw if str(item).strip()]
    elif isinstance(scope_raw, str) and scope_raw.strip():
        scope = [scope_raw.strip()]
    executable = meta.get("executable")
    severity = meta.get("severity")
    pattern_raw = meta.get("pattern")
    return Rule(
        rule_id=rule_id.strip(),
        state=state,
        origin=origin_str,
        scope=scope,
        body=body.strip(),
        executable=str(executable).strip() if executable else None,
        severity=str(severity).strip() if severity else None,
        pattern=str(pattern_raw).strip() if pattern_raw else None,
    )


def render_rule_markdown(rule: Rule) -> str:
    """Render a :class:`Rule` to committed markdown with YAML frontmatter.

    Args:
        rule (Rule): Rule to serialize.

    Returns:
        str: Markdown file contents.

    Examples:
        >>> render_rule_markdown(Rule("r1", "active", "codebase://a.py:1", body="Do X.")).startswith("---")
        True
    """
    lines = [
        "---",
        f"rule_id: {rule.rule_id}",
        f"state: {rule.state}",
        f"origin: {rule.origin}",
    ]
    if rule.scope:
        lines.append("scope:")
        for pattern in rule.scope:
            lines.append(f'  - "{pattern}"')
    if rule.executable:
        lines.append(f"executable: {rule.executable}")
    if rule.severity:
        lines.append(f"severity: {rule.severity}")
    if rule.pattern:
        lines.append(f"pattern: {rule.pattern}")
    lines.extend(["---", "", rule.body.rstrip(), ""])
    return "\n".join(lines)


def validate_origin(origin: str, *, repo_root: Path) -> None:
    """Verify that *origin* resolves to a real reference.

    Args:
        origin (str): ``codebase://<file>:<line>`` or ``finding://<run>#<id>``.
        repo_root (Path): Repository root for ``codebase://`` resolution.

    Raises:
        OriginValidationError: When the ref is missing, malformed, or unresolving.

    Examples:
        >>> validate_origin("finding://run-a#F-1", repo_root=Path("."))
    """
    ref = origin.strip()
    if not ref:
        msg = "origin is required — a rule without origin is an opinion, not a constraint"
        raise OriginValidationError(msg)

    finding_match = _FINDING_ORIGIN_RE.fullmatch(ref)
    if finding_match:
        return

    codebase_match = _CODEBASE_ORIGIN_RE.fullmatch(ref)
    if not codebase_match:
        msg = f"origin {ref!r} must be codebase://<file>:<line> or finding://<run>#<id>"
        raise OriginValidationError(msg)

    rel_path, line_s = codebase_match.group(1), codebase_match.group(2)
    target = repo_root / rel_path
    if not target.is_file():
        msg = f"origin {ref!r} does not resolve: file not found ({rel_path})"
        raise OriginValidationError(msg)
    try:
        line_no = int(line_s)
    except ValueError as exc:
        msg = f"origin {ref!r} has invalid line number {line_s!r}"
        raise OriginValidationError(msg) from exc
    if line_no < 1 or len(target.read_text(encoding="utf-8").splitlines()) < line_no:
        msg = f"origin {ref!r} does not resolve: {rel_path}:{line_no} out of range"
        raise OriginValidationError(msg)


def validate_rule(rule: Rule, *, repo_root: Path) -> None:
    """Validate *rule* including mandatory, resolving origin.

    Args:
        rule (Rule): Rule to validate.
        repo_root (Path): Repository root for ``codebase://`` resolution.

    Raises:
        ValueError: When state is invalid or origin is missing.
        OriginValidationError: When origin does not resolve.

    Examples:
        >>> validate_rule.__name__
        'validate_rule'
    """
    if rule.state not in RULE_STATES:
        msg = f"invalid rule state {rule.state!r}"
        raise ValueError(msg)
    if not rule.origin.strip():
        msg = "origin is required — a rule without origin is an opinion, not a constraint"
        raise ValueError(msg)
    validate_origin(rule.origin, repo_root=repo_root)
