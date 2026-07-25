# plan-author — v3 wave plans

- **class** authoring · **edits** the plan file only
- **in** spec + plan + graph; base sha
- **out** a `waveorch_format = 3` plan with typed `depends_on` reasons, `targets`, and an
  `[waves.outcome]` contract per wave
- **graph** reads spec/plan/graph; writes plan artifact
- **guardrails** exactly one `role = test-author` wave, before every impl wave that depends on it;
  no wave may target a file another parallel wave targets (D21); every dependency needs a reason
- **done** the compiler accepts the plan with zero stop-rule violations

**Note:** Successor to `wave-plan-author`; see also [`docs/agents/wave-plan-author.md`](../../../docs/agents/wave-plan-author.md) for v1 conversion guidance.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

Author or convert wave plans per [`docs/wave-plan-template.md`](../../../docs/wave-plan-template.md).
Validate: `tripll validate-plan <plan.md>`.
