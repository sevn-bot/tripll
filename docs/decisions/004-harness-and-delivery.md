# ADR 004 — Harness pillars and delivery loop

**Status:** Accepted
**Date:** 2026-07-25
**Decisions:** P11–P16 (D11–D17, D14, D15, D22)

## Context

tripll marks waves `done` when `make` verify targets pass in the **same** worktree as the implementer.
There is no outcome-contract grading, no isolated verifier, no PR phase, and no idempotency keys on
external actions. Self-reported completion and shared context violate the harness diamond (nykdotdev).

## Decision

1. **Outcome contracts** (P11/D16). Completion is a state transition with receipts. Pre-declared
   graders run `all_required AND NOT any_forbidden`. If a grader cannot run, state is **`unverified`**,
   never `done`.
2. **Isolated verifier** (P12/D17). Verify runs in a fresh adapter process + fresh worktree at the
   wave's commit, with no implementer transcript. Isolation asserted at dispatch.
3. **PR delivery loop** (P13/D11). L1 delivers branch → PR → fix loop until green → **human merge
   gate**. Auto-merge never default.
4. **Review ingestion** (P14/D12–D13). GitHub check-runs, logs, and review threads normalize to
   `Finding` nodes. Rejected findings export to `.mergecraft/learnings.md`. No mergeCraft upstream change.
5. **Idempotency** (P15/D14–D15). Decide/commit split; idempotency key written before external
   mutation; six pre-commit reconciliation checks. `destructive` actions require human approval and
   `retries: disabled`.
6. **Eight loop exits** (P16/D22). Three mandatory (success, retries-exhausted, hard ceiling) plus
   five targeted including error-threshold circuit breaker (exit 7) and external-event wait (exit 8).

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Same-worktree verify | Implementer context leaks; graders see artifacts not present at commit |
| Self-reported "done" messages | Bigger models cannot fix harness failures; receipts required |
| Local branch merge only (`--integrate`) | No CI/review loop; does not close the delivery gap |
| Retrofit idempotency after PR phase | Duplicate PRs/commits on retry; must be built in from first external action |
| Auto-merge on green CI | Irreversible without human gate; violates operator control |

## Consequences

- W7 ships harness pillars: fingerprint, reset receipts, contracts, reconcile, boundary.
- W8–W9 add GitHub ingestion and PR-phase node kinds with idempotent push/open/comment.
- New `WaveState` value `unverified` added to ledger (W6/W7).
- Env fingerprint fields added to `attempts` table.
