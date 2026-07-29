# review-comment-triager

- **class** triaging · **edits** nothing (drafts only)
- **in** PR review threads (mergeCraft, human, Bugbot), the graph
- **out** each comment classified `accepted` | `rejected` | `deferred` with rationale; `Finding`
  nodes; **staleness check** per §7.12.3
- **graph** reads review threads + graph; writes `Finding` drafts
- **guardrails** never posts publicly without approval (§7.11.2); rejected findings must carry a
  rationale, which feeds `.mergecraft/learnings.md` (D13); stale comments are closed, not fixed
- **done** every open thread has a disposition

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

PR fix loop — review comment path. Dispatched by `pr-shepherd` after `tripll findings sync`.
