# ADR 008 — Content-window hotspots default empty (R9)

**Status:** Accepted (2026-07-26, Wave W0)  
**Decisions:** R9

## Context

`plan/cw_buckets.py` ships `LEGACY_CW_BUCKETS` with hardcoded `src/sevn/...` paths.
`graph.py` loads them as `CW_HOTSPOTS` by default, so plans targeting non-sevn repos
inherit sevn-shaped forbidden sets (ARCH-CW). tripll is standalone; sevn paths are not
universal coordination hotspots.

## Decision

1. **Default `CW_HOTSPOTS` to empty** for production planning. W8 implements the change.
2. **Move sevn buckets to an opt-in fixture** used by corpus-replay tests so the legacy
   behaviour remains testable without polluting foreign repos.
3. **Operators may configure hotspots** in plan or repo config when they have a real
   cross-cutting set — never by hardcoding another product's tree.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Keep sevn paths as default | Wrong forbidden set on every non-sevn target (ARCH-CW) |
| Delete legacy buckets entirely | Loses regression coverage for plans that intentionally model sevn |
| Infer hotspots from repo name | Magic heuristics; fails silently on brownfield repos |

## Consequences

- W8 empties the default and adds `tests/test_cw_portability.py` (W1.11).
- W14 brownfield init must not emit sevn-shaped forbidden paths for foreign repos.
- `grep -rn 'src/sevn' src/tripll/plan/cw_buckets.py` shows paths only inside the opt-in fixture.
