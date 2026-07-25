"""L1 PR fix loop — stub for W9.

The conditional push → poll → investigate → fix cycle is implemented in W9.
This module exposes the entry point probed by ``tests/test_pr_loop.py``.

Exports:
    run_pr_loop_step — one PR-loop step (investigate/fix or merge gate).
"""

from __future__ import annotations

from typing import Any

__all__ = ["run_pr_loop_step"]


def run_pr_loop_step(
    *,
    findings: list[dict[str, Any]] | None = None,
    phase: str = "investigate_and_fix",
    ci_green: bool = False,
    review_clean: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Return the next PR-loop actions or merge-gate state (W9 stub).

    Args:
        findings (list[dict[str, Any]] | None): Open findings driving the loop.
        phase (str): ``investigate_and_fix`` or ``merge``.
        ci_green (bool): Whether CI is green (merge phase).
        review_clean (bool): Whether review is clean (merge phase).

    Returns:
        dict[str, Any] | list[dict[str, Any]]: Step plan or merge-gate result.
    """
    if phase == "merge":
        return {
            "state": "merge_gate_pending",
            "merged": False,
            "ci_green": ci_green,
            "review_clean": review_clean,
        }
    open_findings = [f for f in (findings or []) if f.get("state") == "open"]
    steps: list[dict[str, Any]] = []
    if open_findings:
        steps.append({"agent": "ci-investigator", "action": "investigate"})
        steps.append({"agent": "check-fixer", "action": "fix"})
    return steps
