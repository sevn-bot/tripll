# ADR 007 — Exit table: wire or fail (R8)

**Status:** Accepted (2026-07-26, Wave W0)
**Decisions:** R8

## Context

`loops/exits.py` implements a complete eight-exit evaluator with unit tests, but the
Engine re-implements budget and no-progress inline and never calls `evaluate_exit`.
Exit 1 `goal_met` reads `review_success` from context, yet no production path sets
that key (`exits.py:168` is the sole occurrence). The design note advertises all eight
exits; shrinking the public table mid-remediation would hide unfinished wiring.

## Decision

1. **Wire or fail.** W7 must connect `github/reviews.py::review_merge_signal` and the
   Engine dispatch path to `evaluate_exit` so exits 1, 4, 7, and 8 fire from the main
   loop and are recorded on the run.
2. **Withdrawal is forbidden.** Removing `goal_met` from the advertised exit table is
   not an available outcome — it is listed as `forbidden` in W7's outcome contract.
3. **Honest parking.** If exit 1 cannot be wired without weakening criteria, W7 **parks**
   with a filed issue and Final reports it parked. Agents under schedule pressure must
   not shrink the public contract.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Drop exit 1 from the design note | Hides incomplete work; violates operator trust in the exit table |
| Leave the evaluator as dead code | Duplicates logic; Engine and exits drift (ARCH-exits, DIR-01) |
| Inline-only exit checks in the Engine | Already the broken state; bypasses tested evaluator |

## Consequences

- W7 owns wiring; W1.10 (tier 3) asserts Engine-path firing, not fixture-only checks.
- Thermos T.1 hunts for softened or deleted acceptance criteria.
- `docs/design-note.md` exit §0.3–0.4 marks Engine-live vs evaluator-only status after W7.
