# ADR 003 — Plan format v3 and shape checks

**Status:** Accepted
**Date:** 2026-07-25
**Decisions:** P8, P9, P10 (D10, D19, D20, D21)

## Context

tripll reads wave plans via `parse/wave_plan_v1.py`; skw (under `src/tripll/skw/`) uses `waveorch_format = 2`.
Neither enforces typed dependency reasons, the stop rule, or one-writer-per-file constraints.
`CW_HOTSPOTS` in `graph.py` hardcodes coordination-wave path maps that should be derived from the
graph.

## Decision

1. **One canonical format: `waveorch_format = 3`** (P8/D10). Superset of skw v2 and tripll v1;
   compiled to the task graph. v1/v2 readers retained one release, then deleted.
2. **Fake-edge enforcement** (P9/D19). Every `depends_on` edge requires
   `reason ∈ {artifact, contract, gate}`. Reason-less edges are reported and dropped (parallelising
   the waves). Two parallel waves targeting the same file **fail the compile** (P9/D21).
3. **Stop rule** (P10/D20). The plan compiler **refuses** plans that parallelise sequential work
   (e.g. parallel waves joined by a 1-hop `CALLS` path, or cross-cutting refactors split across
   agents).

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Keep dual formats indefinitely | Drift between skw and tripll parsers; no single compile target |
| Soft warnings for reason-less edges | Agents ignore warnings; parallel waves run without real dependencies |
| Retain hardcoded `CW_HOTSPOTS` | Does not generalise to new repos; contradicts graph-derived one-writer rule |
| Runtime-only overlap detection | Too late — bad plans dispatch before scope breach is caught |

## Consequences

- W4 ships `plan/format_v3.py`, `compile.py`, `shape_checks.py`, and `compat_v1_v2.py`.
- `docs/wave-plan-template.md` updated to v3 schema.
- `RunGraph.validate()` gains compile-time shape checks; `CW_HOTSPOTS` retired after derivation proven on corpus.
- Existing wave plans migrate via compat readers with one-release deprecation window.
