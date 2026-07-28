"""Dashboard PR phase panel — merge gate status and approve action (§8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tripll.loops.l1_pr import pr_status

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "PrPanelView",
    "build_pr_panel",
]


@dataclass(frozen=True, slots=True)
class PrPanelView:
    """PR phase and merge-gate summary for run detail."""

    available: bool
    state: str
    merge_gate_pending: bool
    merge_approved: bool
    ci_green: bool | None
    review_clean: bool | None
    can_approve: bool
    message: str


def build_pr_panel(*, run_dir: Path | None) -> PrPanelView:
    """Build PR panel view from run-directory markers.

    Args:
        run_dir (Path | None): Active run directory, if resolved.

    Returns:
        PrPanelView: Panel state for templates.
    """
    if run_dir is None:
        return PrPanelView(
            available=False,
            state="unknown",
            merge_gate_pending=False,
            merge_approved=False,
            ci_green=None,
            review_clean=None,
            can_approve=False,
            message="Run directory not found.",
        )

    status: dict[str, Any] = pr_status(run_dir=run_dir)
    pending = bool(status.get("merge_gate_pending"))
    approved = bool(status.get("merge_approved"))
    state = str(status.get("state", "running"))
    ci_green = status.get("ci_green")
    review_clean = status.get("review_clean")

    if approved:
        message = "Merge gate approved — merge in GitHub UI or with gh pr merge."
    elif pending:
        message = "Human merge gate — approve below before merging the PR."
    else:
        message = "PR phase not at merge gate yet (run deliver / pr shepherd)."

    return PrPanelView(
        available=True,
        state=state,
        merge_gate_pending=pending and not approved,
        merge_approved=approved,
        ci_green=ci_green if isinstance(ci_green, bool) else None,
        review_clean=review_clean if isinstance(review_clean, bool) else None,
        can_approve=pending and not approved,
        message=message,
    )
