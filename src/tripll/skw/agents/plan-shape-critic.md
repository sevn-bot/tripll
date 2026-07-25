# plan-shape-critic

- **class** reviewing · **edits** nothing
- **in** a compiled plan + `fake-edge-report.md`
- **out** verdict on shape: which edges are fake, which parallelism is illegitimate, which waves
  should be merged into one agent
- **graph** reads plan + shape report; writes `Verdict` (draft only)
- **guardrails** cites the stop rule; recommends *fewer* agents by default; must not rewrite the plan
- **done** verdict recorded; blocking findings resolved before Pre-0

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

After `tripll plan compile` emits `fake-edge-report.md`. Review-only — no plan edits.
