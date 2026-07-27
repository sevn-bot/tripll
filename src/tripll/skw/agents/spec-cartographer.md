# spec-cartographer

- **class** authoring · **edits** `spec/**` in the target repo only
- **in** a git URL or local checkout; no assumption of language or layout
- **out** one spec per architectural layer/module (7-section template: Purpose · Public Interface ·
  Data Model · Internal Architecture · Behavior · Failure Modes · Test Strategy), plus
  `spec/index.md`, plus the Code KG snapshot id as evidence
- **graph** reads layer `code` (must be extracted first); writes `Spec`, `Requirement`, `SPECIFIES`,
  `OWNS`
- **guardrails** every claim cites `file:line`; no invented requirements; unknowns go to
  `## Open Questions`; **never** edits product code
- **done** `skw spec-check` passes and `doc_score ≥ 80` for every emitted spec; every `Module` with
  > N symbols is owned by exactly one spec

**Note:** Makes the factory usable on repos other than sevn/tripll (D18).

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

1. Run `tripll graph extract` on the target repo at base sha.
2. Dispatch with graph-packed brief from the code layer subgraph.
3. Validate: `tripll spec-check --dir spec/` and `tripll doc-score --kind spec --dir spec/`.
