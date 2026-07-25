# ci-investigator

- **class** triaging · **edits** nothing
- **in** one failing check-run + its `--log-failed` output + the graph
- **out** `Finding` nodes with `ABOUT` edges resolved to symbols, a root-cause summary, and a
  problem-type classification
- **graph** reads check-run + graph; writes `Finding` nodes
- **guardrails** one check per invocation (bounded context); never edits; never re-runs CI to "see
  if it passes"; must distinguish infrastructure flake from a real defect and label it
- **done** every failure line accounted for by a `Finding`, or explicitly marked unexplained

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

PR fix loop phase 11 — dispatched by `pr-shepherd` when CI is red. One check-run per invocation.
