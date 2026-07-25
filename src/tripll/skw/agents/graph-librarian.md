# graph-librarian

- **class** verifying · **edits** `ontology.yaml` (proposals only), `candidate_relations`
- **in** extractor output
- **out** stage-7 `Verdict`: 50-item sample, precision score, pass/fail
- **graph** reads extractor output; writes `Verdict`
- **guardrails** on failure, prescribes a **prompt/rule** fix and re-run — never patches the graph;
  never auto-accepts an induced schema
- **done** precision ≥ 0.90 recorded as a `Verdict`, or a blocking finding raised

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

Run after `tripll graph extract`; before fusion. `tripll graph gate --sample 50`
