"""Wave postmortem — contract vs attempt reconciliation (W3.2, RULE-03).

Exports:
    PostmortemVerdict — classified delta between declared contract and attempt.
    classify_wave_delta — classify which side was wrong.
    render_postmortem — markdown report for operator review.
    write_postmortem — persist ``runs/<run-id>/postmortem/<node-id>.md``.
    finalize_wave_compounding — postmortem + optional auto-propose after terminal wave.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from tripll.config import RulesConfig
    from tripll.ledger import AttemptRow

__all__ = [
    "PostmortemVerdict",
    "classify_wave_delta",
    "finalize_wave_compounding",
    "render_postmortem",
    "write_postmortem",
]

_SAFE_NODE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_node_id(node_id: str) -> str:
    """Sanitize *node_id* for use as a postmortem filename stem."""
    cleaned = _SAFE_NODE_ID_RE.sub("_", node_id.strip()).strip("._")
    return cleaned or "wave"


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
    safe_id = _safe_node_id(node_id)
    out = Path(runs_root) / run_id / "postmortem" / f"{safe_id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_postmortem(contract=contract, attempt=attempt, verdict=resolved_verdict),
        encoding="utf-8",
    )
    return out


_PROPOSE_VERDICTS = frozenset(
    {PostmortemVerdict.AGENT_DIVERGED, PostmortemVerdict.CONTRACT_TOO_VAGUE}
)


def _attempt_dict_from_rows(
    *,
    wave_id: str,
    wave_outcome: str,
    attempts: list[AttemptRow],
) -> dict[str, Any]:
    """Build a postmortem attempt dict from ledger rows."""
    last = attempts[-1] if attempts else None
    scope_breaches: list[str] = []
    verify_results: dict[str, str] = {}
    evidence = (last.evidence or "") if last else ""
    if evidence and "scope breach" in evidence.lower():
        scope_breaches = [evidence]
    outcome = (last.outcome if last and last.outcome else wave_outcome) or wave_outcome
    if outcome == "done" and wave_outcome == "done":
        verify_results = {"isolated_verify": "passed"}
    elif outcome in {"failed", "scope_breach"}:
        verify_results = {"isolated_verify": "failed"}
    return {
        "wave_id": wave_id,
        "outcome": outcome,
        "attempt_n": last.attempt_n if last else 0,
        "scope_breaches": scope_breaches,
        "verify_results": verify_results,
        "touched_paths": [],
        "evidence": evidence,
    }


def finalize_wave_compounding(
    *,
    run_id: str,
    node_id: str,
    wave_id: str,
    contract: dict[str, Any],
    attempts: list[AttemptRow],
    wave_outcome: str,
    runs_root: Path | str,
    repo_root: Path,
    rules_config: RulesConfig,
) -> Path | None:
    """Write postmortem and optionally propose a rule after a terminal wave (W3).

    Args:
        run_id (str): Run identifier.
        node_id (str): Wave node id.
        wave_id (str): Human wave id (e.g. ``W3``).
        contract (dict[str, Any]): Declared wave contract fields.
        attempts (list[AttemptRow]): Ledger attempts for this node.
        wave_outcome (str): Terminal node outcome from the engine.
        runs_root (Path | str): Runs directory root.
        repo_root (Path): Repository root for rule store.
        rules_config (RulesConfig): Rules configuration (``auto_propose`` gate).

    Returns:
        Path | None: Postmortem path when written, else ``None`` when rules disabled.
    """
    if not rules_config.enabled:
        return None

    attempt = _attempt_dict_from_rows(
        wave_id=wave_id,
        wave_outcome=wave_outcome,
        attempts=attempts,
    )
    contract_with_wave = {**contract, "wave_id": wave_id}
    verdict = classify_wave_delta(contract=contract_with_wave, attempt=attempt)
    postmortem_path = write_postmortem(
        run_id=run_id,
        node_id=node_id,
        contract=contract_with_wave,
        attempt=attempt,
        verdict=verdict,
        runs_root=runs_root,
    )

    if rules_config.auto_propose and verdict in _PROPOSE_VERDICTS:
        from tripll.rules.promote import propose_rule_from_finding
        from tripll.rules.store import RuleStore

        targets = contract.get("targets") or []
        first_target = targets[0] if targets else None
        finding: dict[str, Any] = {
            "run_id": run_id,
            "finding_id": f"pm-{_safe_node_id(node_id)}",
            "state": "resolved",
            "message_raw": f"Wave {wave_id} postmortem: {verdict.value}",
            "file": first_target,
        }
        store = RuleStore(
            repo_root,
            rules_dir=repo_root / rules_config.dir,
            context_dir=repo_root / rules_config.context_dir,
        )
        try:
            propose_rule_from_finding(finding, store=store)
        except ValueError as exc:
            logger.debug("auto_propose skipped for {}: {}", node_id, exc)

    return postmortem_path
