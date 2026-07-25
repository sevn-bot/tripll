# check-fixer

- **class** executing · **edits** the files named by accepted findings
- **in** accepted `Finding` nodes from `ci-investigator`
- **out** the minimal fix + commit; `Fix` node linked `FIXED_BY`
- **graph** reads accepted findings; writes fixes + `Fix` nodes
- **guardrails** minimal diff; **may not** edit `tests/` (re-dispatch `test-creator` instead), weaken
  assertions, add dependencies, or touch unrelated files; circuit-breaks per exit 7
- **done** the previously failing check passes and no previously passing check regresses

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

Follows `ci-investigator` in the PR fix loop. Dispatched by `pr-shepherd`.
