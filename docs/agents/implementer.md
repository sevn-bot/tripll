# implementer

Wave-scoped executor — successor to `wave-plan-executor` / `wave-runner` (design §11.8).

## Contract

| Field | Value |
|-------|-------|
| **class** | executing |
| **edits** | the wave's `targets` only |
| **inputs** | graph-packed brief (§7.6) |
| **outputs** | code + one conventional commit per wave |
| **graph** | reads graph-packed brief; writes owned paths |
| **guardrails** | **forbidden from `tests/`**; executor-enforced paths; reconcile handoff before starting |
| **done** | outcome contract satisfied per grader — not per agent claim |

## Inherited harness

[`src/tripll/skw/agents/_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md).

## Agent definitions

| Surface | Path |
|---------|------|
| Operator docs (this file) | `docs/agents/implementer.md` |
| skw brief | [`src/tripll/skw/agents/implementer.md`](../../src/tripll/skw/agents/implementer.md) |
| Cursor subagent | [`.cursor/agents/implementer.md`](../../.cursor/agents/implementer.md) |
| Legacy alias | [`wave-runner`](../../src/tripll/skw/agents/wave-runner.md) |
