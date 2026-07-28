# smoothing-pass — post-gauntlet consistency (§11.18)

- **class** reviewing · **edits** wave `targets` only (minimal)
- **in** full artifact after quality rounds, optional reference, handoff
- **out** zero or one commit; consistency `Verdict`
- **guardrails** no redesign; no tests/; fix cross-piece conflicts and drift only
- **done** coherent whole artifact or explicit no-op

Runs when `quality_gauntlet.smoothing = true`, after quality loop, before `wave-verifier`.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md).

Design: [`docs/design/quality-gauntlet.md`](../../../../docs/design/quality-gauntlet.md)
