# ADR 001 — Graph substrate (SQLite, three layers, ledger truth, ontology)

**Status:** Accepted
**Date:** 2026-07-25
**Decisions:** P1, P2, P3, P20 (D2, D3, D4, D6)

## Context

tripll today persists run structure as a flat `graph.json` from `RunGraph.to_dict()` with no queryable
code or finding layer. The L1 code factory needs a durable, provenance-rich graph that supports
brief packing, finding attachment, and L2 telemetry seams without introducing external services.

## Decision

1. **SQLite is the system of record** behind a `GraphStore` port (P1/D2). Optional NetworkX read
   replica behind a `kg` extra; rebuildable from SQLite, never authoritative.
2. **Three cross-linked layers** in one store — Code KG, Task graph, Finding graph — discriminated
   by `layer`/`kind` in shared `nodes`/`edges` tables plus `merges` (P2/D4).
3. **`ledger.db` remains the system of record** for run/wave/attempt lifecycle. Layer `task` is
   written alongside the ledger in W2; `graph.json` emitted for one release as a compatibility shim
   (P3/D6). LangGraph checkpoints (when present) are derived caches keyed `thread_id == run_id`.
4. **`ontology.yaml` is the single source of truth** for predicates and kinds. Every extractor embeds
   it verbatim; vague verbs (`RELATED_TO`, `HAS_LINK`) are rejected by the validator (P20).

### Kùzu rejected (D3)

Kùzu is **not** adopted as system of record. Upstream was **archived 2025-10-10** (Apple acqui-hire);
PyPI `kuzu` is **frozen at 0.11.3**, uploaded that same day. `ladybugdb` is absent from PyPI. Kùzu
permits **one writer at a time**, conflicting with tripll's concurrent wave dispatch. At repo-KG scale
(~10⁴–10⁵ nodes) SQLite with recursive CTEs and optional `sqlite-vec` (via langgraph-checkpoint-sqlite)
is sufficient. A Kùzu-lineage replica port may be added later as rebuildable derived storage only.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Kùzu / LadybugDB as system of record | Archived upstream, frozen PyPI, single-writer constraint, supply-chain risk |
| NetworkX as primary store | Not durable; no provenance columns; poor concurrent write semantics |
| Separate DB per layer | Complicates cross-layer traversals (finding → symbol → requirement) |
| Flat `graph.json` only | No query API, no provenance, blocks brief packer and finding graph |

## Consequences

- W2 ships `GraphStore`, DDL, migrations, and `ontology.yaml`.
- Extractors and fusion (W3) write through `GraphStore` with mandatory provenance fields.
- Recursive CTE path queries replace ad-hoc dict walks; `paths()` hides SQL complexity from callers.
- Reversibility: replica backends can be swapped without migrating ledger truth.
