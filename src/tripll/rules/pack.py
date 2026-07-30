"""Rules and context packing for dispatch briefs (W2.5, R31).

Exports:
    ContextModule — on-demand tacit-knowledge markdown module.
    estimate_tokens — rough token estimate for budget enforcement.
    pack_rules_for_brief — render active rules plus scoped context under budget.
    parse_context_markdown — parse a context module file.
    render_context_markdown — render a context module file.
    scope_intersects — whether module scope matches any wave target.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tripll.rules.model import Rule  # noqa: TC001 — runtime pack rendering
from tripll.skw.prd_validate import parse_frontmatter
from tripll.worktrees import path_matches_owned

__all__ = [
    "ContextModule",
    "estimate_tokens",
    "pack_rules_for_brief",
    "parse_context_markdown",
    "render_context_markdown",
    "scope_intersects",
]


@dataclass
class ContextModule:
    """On-demand tacit-knowledge markdown loaded by scope intersection.

    Args:
        topic (str): Module slug (filename stem).
        scope (list[str]): Glob patterns; packed when a wave target intersects.
        body (str): Markdown body after frontmatter.
    """

    topic: str
    scope: list[str] = field(default_factory=list)
    body: str = ""


def parse_context_markdown(text: str, *, topic: str) -> ContextModule:
    """Parse a context module markdown file.

    Args:
        text (str): Full file contents.
        topic (str): Filename stem when ``topic`` is absent from frontmatter.

    Returns:
        ContextModule: Parsed module.
    """
    meta, body, _error = parse_frontmatter(text)
    topic_val = meta.get("topic")
    resolved_topic = str(topic_val).strip() if topic_val else topic
    scope_raw = meta.get("scope")
    scope: list[str] = []
    if isinstance(scope_raw, list):
        scope = [str(item) for item in scope_raw if str(item).strip()]
    elif isinstance(scope_raw, str) and scope_raw.strip():
        scope = [scope_raw.strip()]
    return ContextModule(topic=resolved_topic, scope=scope, body=body.strip())


def render_context_markdown(module: ContextModule) -> str:
    """Render a context module to markdown with YAML frontmatter."""
    lines = ["---", f"topic: {module.topic}"]
    if module.scope:
        lines.append("scope:")
        for pattern in module.scope:
            lines.append(f'  - "{pattern}"')
    lines.extend(["---", "", module.body.rstrip(), ""])
    return "\n".join(lines)


def scope_intersects(scope_patterns: list[str], wave_targets: list[str]) -> bool:
    """Return True when any *wave_targets* path matches a *scope_patterns* glob.

    Args:
        scope_patterns (list[str]): Context module scope globs.
        wave_targets (list[str]): Wave owned-path targets.

    Returns:
        bool: ``True`` when at least one target falls under scope.
    """
    if not scope_patterns or not wave_targets:
        return False
    return any(path_matches_owned(target, scope_patterns) for target in wave_targets)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token).

    Args:
        text (str): Text to estimate.

    Returns:
        int: Estimated token count (minimum 0).
    """
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def _render_rule_entry(rule: Rule) -> str:
    header = f"### Rule `{rule.rule_id}` ({rule.state})"
    origin = f"**Origin:** `{rule.origin}`"
    return "\n".join([header, origin, "", rule.body.strip()])


def _render_context_entry(module: ContextModule) -> str:
    header = f"### Context `{module.topic}`"
    return "\n".join([header, "", module.body.strip()])


def pack_rules_for_brief(
    *,
    rules: list[Rule],
    context_modules: list[ContextModule],
    wave_targets: list[str],
    budget_tokens: int,
) -> str:
    """Pack active rules and scoped context modules under *budget_tokens*.

    Over budget drops **context modules first**; rules are never dropped (R31).

    Args:
        rules (list[Rule]): Active rules to pack (caller filters state).
        context_modules (list[ContextModule]): All context modules on disk.
        wave_targets (list[str]): Wave owned-path targets for scope intersection.
        budget_tokens (int): Maximum estimated tokens for the pack.

    Returns:
        str: Rendered markdown pack, or ``""`` when nothing to pack.
    """
    active_rules = [rule for rule in rules if rule.state == "active"]
    if not active_rules and not context_modules:
        return ""

    selected_context = [
        module for module in context_modules if scope_intersects(module.scope, wave_targets)
    ]

    if not active_rules and not selected_context:
        return ""

    rule_blocks = [_render_rule_entry(rule) for rule in active_rules]
    context_blocks = [_render_context_entry(module) for module in selected_context]

    def assemble(ctx_blocks: list[str]) -> str:
        parts: list[str] = ["## Rules and context", ""]
        if rule_blocks:
            parts.append("### Active rules")
            parts.append("")
            parts.extend(block + "\n" for block in rule_blocks)
        if ctx_blocks:
            parts.append("### Context modules (scoped)")
            parts.append("")
            parts.extend(block + "\n" for block in ctx_blocks)
        return "\n".join(parts).strip()

    packed = assemble(context_blocks)
    while estimate_tokens(packed) > budget_tokens and context_blocks:
        context_blocks.pop()
        packed = assemble(context_blocks)

    if estimate_tokens(packed) > budget_tokens:
        max_chars = max(budget_tokens * 4, 1)
        packed = packed[:max_chars].rstrip()
        if not packed.endswith("…"):
            packed = packed + "…"

    if not rule_blocks and not context_blocks:
        return ""

    return packed
