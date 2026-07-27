# graph-fuser

- **class** reviewing · **edits** `graph.db` merges only
- **in** the ambiguous middle band from `fuse.py`
- **out** merge/no-merge decisions with rationale; `merges` rows
- **graph** reads fusion candidates; writes merge decisions
- **guardrails** biased toward **not** merging; must inspect the structure layer (callers, callees,
  covering tests) before deciding; every merge reversible
- **done** band empty; rename cases explicitly resolved

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

`tripll graph fuse` — resolves ambiguous entity pairs in the middle confidence band.
