"""Export rejected findings and active rules to learnings markdown (D13, W3.5)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tripll.rules.model import Rule

WITHDRAWN_HEADING = "## Withdrawn review findings (known non-issues)"
ACTIVE_RULES_HEADING = "## Active rules (binding constraints)"


def _render_active_rules_lines(rules: list[Rule]) -> list[str]:
    """Render active rules as markdown bullets."""
    lines: list[str] = []
    for rule in rules:
        if rule.state != "active":
            continue
        origin = rule.origin or "unknown"
        summary = rule.body.strip().splitlines()[0] if rule.body.strip() else rule.rule_id
        lines.append(f"- **{rule.rule_id}** (origin `{origin}`): {summary}")
    return lines


def export_learnings(
    findings: list[dict[str, Any]],
    *,
    path: Path | str,
    active_rules: list[Rule] | None = None,
) -> Path:
    """Write rejected findings with rationale to ``.mergecraft/learnings.md``.

    Uses the ``## Withdrawn review findings (known non-issues)`` section that
    mergeCraft Review / AddressReviews modes consult before re-raising. When
    *active_rules* is provided, appends a second section for binding constraints
    (W3.5) without changing the rejected filter.

    Args:
        findings (list[dict[str, Any]]): Finding dicts (rejected ones are exported).
        path (Path | str): Target learnings file path.
        active_rules (list[Rule] | None): Optional active rules for the positive channel.

    Returns:
        Path: Written path.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rejected = [f for f in findings if f.get("state") == "rejected"]
    lines = [
        "# mergeCraft learnings",
        "",
        "Findings marked **rejected** by the triager — mergeCraft should not re-raise these.",
        "",
        WITHDRAWN_HEADING,
        "",
    ]
    if not rejected:
        lines.append("_No withdrawn findings yet._")
    else:
        for finding in rejected:
            rule_id = finding.get("rule_id") or "unknown"
            rationale = finding.get("rationale") or finding.get("message_raw") or ""
            file_ = finding.get("file") or ""
            # Reason-first bullet (mergeCraft AddressReviews contract): claim + why wrong.
            claim = finding.get("message_raw") or rule_id
            loc = f" (`{file_}`)" if file_ else ""
            reason = rationale if rationale else "rejected by triager"
            lines.append(f"- **{rule_id}**{loc}: claimed «{claim}»; {reason}")
        lines.append("")

    if active_rules is not None:
        active = [rule for rule in active_rules if rule.state == "active"]
        lines.extend(["", ACTIVE_RULES_HEADING, ""])
        if not active:
            lines.append("_No active rules yet._")
        else:
            lines.extend(_render_active_rules_lines(active))
            lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def ensure_learnings_template(
    path: Path | str,
    *,
    force: bool = False,
) -> Path | None:
    """Create an empty D13 learnings template when the path is missing.

    Args:
        path (Path | str): Target ``.mergecraft/learnings.md`` path.
        force (bool): Overwrite an existing file when True.

    Returns:
        Path | None: Written path, or None when skipped (already exists).
    """
    out = Path(path)
    if out.exists() and not force:
        return None
    export_learnings([], path=out)
    return out
