# implementer — wave-scoped executor

Successor to `wave-plan-executor` / `wave-runner`. Execute **one wave** from an active plan:
implement its bullets, satisfy the outcome contract, reconcile the handoff, and stop.

- **class** executing · **edits** the wave's `targets` only
- **in** the graph-packed brief (§7.6)
- **out** code + one conventional commit per wave
- **graph** reads graph-packed brief; writes code in owned paths
- **guardrails** **forbidden from editing `tests/`**; forbidden paths enforced by the executor, not
  by good intentions; must not weaken a test to pass; must reconcile the handoff against live state
  before starting (§7.9.1)
- **done** outcome contract satisfied per the grader — not per the agent's claim

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

Dispatched for `role = impl` waves. Per-wave commit handled by the `commit_wave` graph node when
`[git]` enables it. Legacy alias: `wave-runner`.
