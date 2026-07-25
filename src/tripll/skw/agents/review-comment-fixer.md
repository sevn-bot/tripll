# review-comment-fixer

- **class** executing · **edits** files named by accepted review findings
- **in** accepted findings from the triager
- **out** fix + commit; thread resolution **queued for approval**, not posted
- **graph** reads accepted findings; writes fixes
- **guardrails** as `check-fixer`; one finding per commit where practical, for attribution
- **done** finding `state = fixed`; re-verify green

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

Follows `review-comment-triager` in the PR fix loop. Dispatched by `pr-shepherd`.
