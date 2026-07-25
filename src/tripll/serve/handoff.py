"""Handoff contract — 10-field evidence block at wave boundaries (§7.9.1)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "HANDOFF_FIELDS",
    "HANDOFF_GOVERNING_RULE",
    "build_handoff",
    "format_handoff_block",
    "validate_handoff",
]

HANDOFF_GOVERNING_RULE = (
    "The handoff is evidence, not authority — repository and external state "
    "outrank the summary. Reconcile against live state before acting."
)

HANDOFF_FIELDS = (
    "objective",
    "scope_accepted",
    "decisions_made",
    "files_changed",
    "external_state_changed",
    "tests_run_and_results",
    "known_failures",
    "git_workspace_state",
    "next_safe_action",
    "approval_still_required",
)


def build_handoff(
    *,
    objective: str,
    scope_accepted: list[str],
    decisions_made: list[str],
    files_changed: list[str],
    external_state_changed: list[str],
    tests_run_and_results: dict[str, str],
    known_failures: list[str],
    git_workspace_state: dict[str, Any],
    next_safe_action: str,
    approval_still_required: list[str],
) -> dict[str, Any]:
    """Build the 10-field handoff block plus the governing rule."""
    return {
        "objective": objective,
        "scope_accepted": list(scope_accepted),
        "decisions_made": list(decisions_made),
        "files_changed": list(files_changed),
        "external_state_changed": list(external_state_changed),
        "tests_run_and_results": dict(tests_run_and_results),
        "known_failures": list(known_failures),
        "git_workspace_state": dict(git_workspace_state),
        "next_safe_action": next_safe_action,
        "approval_still_required": list(approval_still_required),
        "governing_rule": HANDOFF_GOVERNING_RULE,
    }


def format_handoff_block(handoff: dict[str, Any]) -> str:
    """Render *handoff* as markdown for brief inclusion."""
    lines = ["## Handoff-in", "", f"**Objective:** {handoff.get('objective', '')}", ""]
    lines.append(f"**Next safe action:** {handoff.get('next_safe_action', '')}")
    lines.append("")
    lines.append(f"> {handoff.get('governing_rule', HANDOFF_GOVERNING_RULE)}")
    scope = handoff.get("scope_accepted") or []
    if scope:
        lines.append("")
        lines.append("**Scope accepted:** " + ", ".join(str(s) for s in scope))
    tests = handoff.get("tests_run_and_results") or {}
    if tests:
        lines.append("")
        lines.append("**Tests:**")
        for name, result in sorted(tests.items()):
            lines.append(f"- {name}: {result}")
    return "\n".join(lines)


def validate_handoff(handoff: dict[str, Any]) -> dict[str, bool]:
    """Validate that a handoff enables a fresh session to identify the next action."""
    action = str(handoff.get("next_safe_action") or "").strip()
    objective = str(handoff.get("objective") or "").strip()
    return {
        "action_identified": bool(action),
        "objective_present": bool(objective),
        "complete": bool(action and objective),
    }
