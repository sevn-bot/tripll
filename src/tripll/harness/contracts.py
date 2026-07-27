"""Outcome contracts and code-based graders (§7.9.4, D16)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "OutcomeResult",
    "evaluate_outcome",
    "parse_outcome_contract",
    "render_completion",
]

OutcomeState = Literal["passed", "failed", "unverified"]


@dataclass(frozen=True, slots=True)
class OutcomeResult:
    """Grader verdict for a wave outcome contract."""

    passed: bool | None
    state: OutcomeState
    grader_output: dict[str, str]
    reasons: list[str]


def parse_outcome_contract(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    """Normalise a ``[waves.outcome]`` table from plan v3.

    Args:
        raw (dict[str, Any] | None): Outcome section from a wave dict.

    Returns:
        dict[str, list[str]]: ``required``, ``forbidden``, and ``evidence`` lists.
    """
    if not raw:
        return {"required": [], "forbidden": [], "evidence": []}
    return {
        "required": [str(x) for x in raw.get("required") or []],
        "forbidden": [str(x) for x in raw.get("forbidden") or []],
        "evidence": [str(x) for x in raw.get("evidence") or []],
    }


def evaluate_outcome(
    *,
    required: list[str],
    forbidden: list[str],
    grader_output: dict[str, str] | None,
    artifact_present: bool = False,
) -> OutcomeResult:
    """Grade ``all_required AND NOT any_forbidden`` from code-based grader output.

    If a required grader cannot run, the honest state is ``unverified`` — never
    ``done``. Agent claims and plausible artifacts do not override grader failure.

    Args:
        required (list[str]): Required grader keys that must pass.
        forbidden (list[str]): Forbidden conditions that must not run/pass.
        grader_output (dict[str, str] | None): Grader results keyed by requirement.
        artifact_present (bool): When True, still fail if graders report failure.

    Returns:
        OutcomeResult: Verdict with ``state`` suitable for ledger transition.
    """
    if grader_output is None:
        return OutcomeResult(
            passed=None,
            state="unverified",
            grader_output={},
            reasons=["grader output unavailable"],
        )

    output = dict(grader_output)
    reasons: list[str] = []

    for key in required:
        if key not in output:
            return OutcomeResult(
                passed=None,
                state="unverified",
                grader_output=output,
                reasons=[f"grader missing for required key: {key}"],
            )
        status = output[key].lower()
        if status not in {"pass", "passed", "ok", "skip", "skipped", "not_run"}:
            reasons.append(f"required {key!r} failed: {output[key]}")

    for key in forbidden:
        status = output.get(key, "not_run").lower()
        if status in {"pass", "passed", "ok", "run"}:
            reasons.append(f"forbidden {key!r} passed")

    if reasons:
        return OutcomeResult(
            passed=False,
            state="failed",
            grader_output=output,
            reasons=reasons,
        )

    if artifact_present and any(output.get(k, "").lower() == "fail" for k in required):
        return OutcomeResult(
            passed=False,
            state="failed",
            grader_output=output,
            reasons=["artifact present but grader reported failure"],
        )

    return OutcomeResult(
        passed=True,
        state="passed",
        grader_output=output,
        reasons=[],
    )


def render_completion(
    *,
    grader_output: dict[str, str],
    agent_claim: str = "",
) -> str:
    """Render the completion message from grader output, not the agent claim.

    Args:
        grader_output (dict[str, str]): Code-based grader results.
        agent_claim (str): Ignored agent self-report (included only when empty output).

    Returns:
        str: Operator-facing completion summary.
    """
    if not grader_output:
        return agent_claim or "no grader output"
    lines = ["## Verification (grader output)", ""]
    for key, value in sorted(grader_output.items()):
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)
