# plan-author

Author **format v3** wave plans with typed `depends_on`, per-wave `targets`, and outcome contracts.

## Contract

| Field | Value |
|-------|-------|
| **class** | authoring |
| **edits** | the plan file only |
| **inputs** | spec + plan + graph; base sha |
| **outputs** | `waveorch_format = 3` plan |
| **graph** | reads spec/plan/graph; writes plan artifact |
| **guardrails** | one `test-author` wave before impl; no parallel file overlap (D21); typed dependency reasons |
| **done** | compiler accepts plan with zero stop-rule violations |

Successor to [`wave-plan-author.md`](wave-plan-author.md) for v3 plans.

## Inherited harness

[`src/tripll/skw/agents/_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md).

## Agent definitions

| Surface | Path |
|---------|------|
| Operator docs (this file) | `docs/agents/plan-author.md` |
| skw brief | [`src/tripll/skw/agents/plan-author.md`](../../src/tripll/skw/agents/plan-author.md) |
| Legacy v1 converter | [`wave-plan-author.md`](wave-plan-author.md) |
