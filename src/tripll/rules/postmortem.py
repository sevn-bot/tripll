"""Wave postmortem — contract vs attempt reconciliation (W3.2, RULE-03).

Exports:
    PostmortemVerdict — classified delta between declared contract and attempt.
    classify_wave_delta — classify which side was wrong.
    render_postmortem — markdown report for operator review.
    write_postmortem — persist ``runs/<run-id>/postmortem/<node-id>.md``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "PostmortemVerdict",
    "classify_wave_delta",
    "render_postmortem",
    "write_postmortem",
]


class PostmortemVerdict(StrEnum):
    """Classification of plan-vs-actual delta for a terminal wave."""

    CONTRACT_TOO_VAGUE = "contract-too-vague"
    AGENT_DIVERGED = "agent-diverged"
    ENVIRONMENT = "environment"
    EXTERNAL = "external"


def _verify_failed(attempt: dict[str, Any]) -> bool:
    verify = attempt.get("verify_results")
    if isinstance(verify, dict):
        return any(str(v).lower() in {"failed", "failure", "error"} for v in verify.values())
    return False


def classify_wave_delta(
    *,
    contract: dict[str, Any],
    attempt: dict[str, Any],
) -> PostmortemVerdict:
    """Classify whether the contract or the agent was wrong (RULE-03).

    Args:
        contract (dict[str, Any]): Declared wave contract (required, forbidden, targets).
        attempt (dict[str, Any]): Attempt record (outcome, scope breaches, verify results).

    Returns:
        PostmortemVerdict: ``contract-too-vague`` when verify failed in-scope;
            ``agent-diverged`` when scope was breached or forbidden paths touched.

    Examples:
        >>> classify_wave_delta(
        ...     contract={"required": [], "forbidden": [], "targets": []},
        ...     attempt={"outcome": "failed", "scope_breaches": [], "verify_results": {}},
        ... )
        <PostmortemVerdict.CONTRACT_TOO_VAGUE: 'contract-too-vague'>
    """
    breaches = attempt.get("scope_breaches") or []
    if breaches:
        return PostmortemVerdict.AGENT_DIVERGED

    touched = attempt.get("touched_paths") or []
    forbidden = contract.get("forbidden") or []
    if forbidden and touched:
        forbidden_lower = {str(item).lower() for item in forbidden}
        for path in touched:
            path_s = str(path).lower()
            if any(token in path_s for token in forbidden_lower if token):
                return PostmortemVerdict.AGENT_DIVERGED

    outcome = str(attempt.get("outcome") or "").lower()
    if outcome in {"failed", "failure", "error"} or _verify_failed(attempt):
        env_hint = attempt.get("environment_failure")
        if env_hint:
            return PostmortemVerdict.ENVIRONMENT
        external_hint = attempt.get("external_blocker")
        if external_hint:
            return PostmortemVerdict.EXTERNAL
        return PostmortemVerdict.CONTRACT_TOO_VAGUE

    return PostmortemVerdict.EXTERNAL


def render_postmortem(
    *,
    contract: dict[str, Any],
    attempt: dict[str, Any],
    verdict: PostmortemVerdict,
) -> str:
    """Render a postmortem markdown report naming which side was wrong.

    Args:
        contract (dict[str, Any]): Declared wave contract.
        attempt (dict[str, Any]): Attempt record.
        verdict (PostmortemVerdict): Classification from :func:`classify_wave_delta`.

    Returns:
        str: Markdown suitable for ``runs/<run-id>/postmortem/<node-id>.md``.
    """
    wave_id = contract.get("wave_id") or attempt.get("wave_id") or "unknown"
    lines = [
        f"# Wave postmortem — {wave_id}",
        "",
        f"**Verdict:** {verdict.value}",
        "",
    ]
    if verdict == PostmortemVerdict.CONTRACT_TOO_VAGUE:
        lines.extend(
            [
                "The attempt stayed in scope but verification failed. "
                "The **contract** was too vague or incomplete — tighten required outcomes "
                "or acceptance checks rather than blaming agent discipline.",
                "",
            ]
        )
    elif verdict == PostmortemVerdict.AGENT_DIVERGED:
        lines.extend(
            [
                "The agent **diverged** from the declared contract — scope breaches or "
                "forbidden paths were touched. The plan was clear enough; execution did not "
                "follow it.",
                "",
            ]
        )
    elif verdict == PostmortemVerdict.ENVIRONMENT:
        lines.append("Failure appears **environment**-driven (infra, credentials, or tooling).")
        lines.append("")
    else:
        lines.append("Outcome classified as **external** (outside contract vs agent control).")
        lines.append("")

    lines.extend(
        [
            "## Contract",
            "",
            f"- Required: {contract.get('required') or []}",
            f"- Forbidden: {contract.get('forbidden') or []}",
            f"- Targets: {contract.get('targets') or []}",
            "",
            "## Attempt",
            "",
            f"- Outcome: {attempt.get('outcome')}",
            f"- Attempt #: {attempt.get('attempt_n')}",
            f"- Scope breaches: {attempt.get('scope_breaches') or []}",
            f"- Verify results: {attempt.get('verify_results') or {}}",
            f"- Touched paths: {attempt.get('touched_paths') or []}",
            "",
        ]
    )
    return "\n".join(lines)


def write_postmortem(
    *,
    run_id: str,
    node_id: str,
    contract: dict[str, Any],
    attempt: dict[str, Any],
    verdict: PostmortemVerdict | None = None,
    runs_root: Path | str = "runs",
) -> Path:
    """Write ``runs/<run-id>/postmortem/<node-id>.md`` beside run logs.

    Args:
        run_id (str): Run identifier.
        node_id (str): Wave node id (filename stem).
        contract (dict[str, Any]): Declared wave contract.
        attempt (dict[str, Any]): Attempt record.
        verdict (PostmortemVerdict | None): Precomputed verdict; classified when omitted.
        runs_root (Path | str): Runs directory root.

    Returns:
        Path: Written postmortem file path.
    """
    resolved_verdict = verdict or classify_wave_delta(contract=contract, attempt=attempt)
    out = Path(runs_root) / run_id / "postmortem" / f"{node_id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_postmortem(contract=contract, attempt=attempt, verdict=resolved_verdict),
        encoding="utf-8",
    )
    return out
