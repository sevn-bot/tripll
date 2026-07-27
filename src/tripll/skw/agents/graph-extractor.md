# graph-extractor

- **class** infra · **edits** `graph.db` only
- **in** repo at sha, `ontology.yaml`
- **out** layer-`code` nodes/edges with full provenance
- **graph** reads repo + ontology; writes code-layer nodes/edges
- **guardrails** deterministic extractors first (§7.4.1); semantic passes batched (D7) and limited
  to `IMPLEMENTS` / `ABOUT`; every semantic assertion carries an evidence quote; **never** merges
  (that is fusion's job); relations only between already-extracted entities
- **done** extraction summary written; candidate relations recorded; no `RELATED_TO`

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

`tripll graph extract --repo <path> --sha <sha>`
