# smoothing-pass

> **Dispatch status:** **Contract + design** — optional post-gauntlet consistency pass; engine
> dispatch pending implementation wave.

Consistency pass after parallel or multi-round quality gauntlets (design §11.18).

| Field | Value |
|-------|-------|
| **class** | reviewing |
| **edits** | wave `targets` only — minimal diffs for consistency |
| **inputs** | full artifact after quality rounds, reference (optional), handoff |
| **outputs** | at most one conventional commit fixing conflicts/inconsistency across pieces |
| **graph** | reads packed subgraph for wave scope |
| **guardrails** | **no redesign**; no new features; no test edits; fix integration conflicts and tone/layout drift only |
| **done** | artifact reads as one coherent unit; or explicit no-op verdict when already consistent |

Runs when `[waves.outcome.quality_gauntlet].smoothing = true`, after inner loop, before
`wave-verifier`.

## Inherited harness

[`src/tripll/skw/agents/_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md)

## Agent definitions

| Surface | Path |
|---------|------|
| Operator docs (this file) | `docs/agents/smoothing-pass.md` |
| skw brief | [`src/tripll/skw/agents/smoothing-pass.md`](../../src/tripll/skw/agents/smoothing-pass.md) |
| Design | [`docs/design/quality-gauntlet.md`](../design/quality-gauntlet.md) |
