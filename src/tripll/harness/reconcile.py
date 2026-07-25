"""Pre-commit reconciliation checks (§7.9.5, D14)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

__all__ = ["ReconcileResult", "reconcile_pre_commit"]

_RECON_CHECKS = (
    "attempt_still_current",
    "task_still_active",
    "no_prior_outcome",
    "target_unchanged",
    "idempotency_key_free",
    "artifact_is_latest",
)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of pre-commit reconciliation across concurrent attempts."""

    ok: bool
    committed_attempt_id: int | None
    blocked_by: str | None = None


def _raise_conflict(check: str) -> NoReturn:
    msg = f"pre-commit reconciliation blocked: {check.replace('_', ' ')}"
    raise RuntimeError(msg)


def reconcile_pre_commit(
    *,
    attempt: dict[str, Any] | None = None,
    attempts: list[dict[str, Any]] | None = None,
    conflict: str | None = None,
    task_active: bool = True,
    target_unchanged: bool = True,
    idempotency_key_free: bool = True,
    artifact_is_latest: bool = True,
    prior_outcome: bool = False,
) -> ReconcileResult:
    """Run six pre-commit checks before any external mutation.

    When *conflict* names a check, that check is forced to fail (for tests).
    When *attempts* is provided, only the current non-cancelled attempt may commit.

    Args:
        attempt (dict[str, Any] | None): Single attempt under reconciliation.
        attempts (list[dict[str, Any]] | None): Concurrent attempts; latest current wins.
        conflict (str | None): Force-fail one check by name (test hook).
        task_active (bool): Task must still be active.
        target_unchanged (bool): Target state unchanged since attempt began.
        idempotency_key_free (bool): Key has no recorded result yet.
        artifact_is_latest (bool): Graded artifact is the latest accepted version.
        prior_outcome (bool): Another attempt already produced the outcome.

    Returns:
        ReconcileResult: ``committed_attempt_id`` when reconciliation passes.

    Raises:
        RuntimeError: When any reconciliation check fails.
    """
    if conflict:
        if conflict not in _RECON_CHECKS:
            msg = f"unknown reconciliation check: {conflict}"
            raise ValueError(msg)
        _raise_conflict(conflict)

    if attempts is not None:
        current = next(
            (a for a in attempts if a.get("current") and not a.get("cancelled")),
            None,
        )
        if current is None:
            _raise_conflict("attempt_still_current")
        raw_id = current.get("id")
        if raw_id is None:
            _raise_conflict("attempt_still_current")
        attempt_id = int(raw_id)
        for other in attempts:
            if other.get("cancelled"):
                continue
            if other.get("id") != attempt_id and other.get("current"):
                _raise_conflict("attempt_still_current")
            if other.get("id") != attempt_id and other.get("tool_results"):
                delayed = any(r.get("delayed") for r in other.get("tool_results") or [])
                if delayed and other.get("current"):
                    _raise_conflict("attempt_still_current")
        return ReconcileResult(ok=True, committed_attempt_id=attempt_id)

    if attempt is None:
        _raise_conflict("attempt_still_current")

    att = attempt
    if not att.get("current", True):
        _raise_conflict("attempt_still_current")
    if not task_active:
        _raise_conflict("task_still_active")
    if prior_outcome:
        _raise_conflict("no_prior_outcome")
    if not target_unchanged:
        _raise_conflict("target_unchanged")
    if not idempotency_key_free:
        _raise_conflict("idempotency_key_free")
    if not artifact_is_latest:
        _raise_conflict("artifact_is_latest")

    single_id = att.get("id")
    return ReconcileResult(
        ok=True,
        committed_attempt_id=int(single_id) if single_id is not None else None,
    )
