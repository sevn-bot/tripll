# ADR 011 — Code graph activation without mandatory extras (R18)

**Status:** Accepted (2026-07-26, Wave W0)  
**Decisions:** R18, R15

## Context

tripll ships a code graph (`graphstore/`, NetworkX replica behind extras) but
`compile_plan` historically passed no `code_graph` into `check_stop_rule`, so only a
crude target-count proxy ran (SHAPE-01). Making the graph mandatory would force every
install to pull `langgraph`/`networkx` for basic plan validation — too heavy for repos
that only need dispatch.

P2 activated the graph for stop-rule precision and brief packing while keeping extras
optional for runs.

## Decision

1. **Activate the graph for planning and briefs** — `compile_plan` supplies
   `code_graph`; graph briefs default on when extras are present (P2, GRAPH-01).
2. **Keep the graph an optional extra** — base install completes runs without `graph`/`kg`;
   stop rule falls back to per-wave target thresholds (P0.10), not group union.
3. **Do not raise `_CROSS_CUTTING_MODULE_LIMIT` to silence SHAPE-01** (R15). Fix the
   proxy (per-wave threshold + real graph), not the constant.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Mandatory graph dependency | Breaks minimal installs; violates standalone tripll posture |
| Leave graph unwired | Precise D20 stop rule never fires; false refusals and false allows |
| Raise module limit from 5 to 25 | Disables guard for every future plan tripll runs |

## Consequences

- P2 landed `code_graph.py` and tests; W0 records the ADR only.
- Plans declare `[pipeline] extras = ["graph", "kg"]` when they need graph-derived routing hints.
- Runs without extras still complete; graph briefs and precise stop rule degrade gracefully.
