"""Harness pillars — fingerprint, reset, contracts, reconcile, boundary (§7.9)."""

from tripll.harness.boundary import (
    VerifyDispatchContext,
    assert_verify_isolation,
    build_verify_dispatch,
    classify_action,
    require_approval,
)
from tripll.harness.contracts import (
    OutcomeResult,
    evaluate_outcome,
    parse_outcome_contract,
    render_completion,
)
from tripll.harness.fingerprint import EnvFingerprint, capture_env_fingerprint
from tripll.harness.reconcile import ReconcileResult, reconcile_pre_commit
from tripll.harness.reset import ResetReceipt, capture_reset_receipt

__all__ = [
    "EnvFingerprint",
    "OutcomeResult",
    "ReconcileResult",
    "ResetReceipt",
    "VerifyDispatchContext",
    "assert_verify_isolation",
    "build_verify_dispatch",
    "capture_env_fingerprint",
    "capture_reset_receipt",
    "classify_action",
    "evaluate_outcome",
    "parse_outcome_contract",
    "reconcile_pre_commit",
    "render_completion",
    "require_approval",
]
