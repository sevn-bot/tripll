# Graph serving — packed briefs (§7.6)

The graph-packed brief replaces the legacy no-exploration directive in
`tripll.brief`. Packing is implemented in `tripll.serve.brief_packer`.

## Packing algorithm

1. Seeds from wave `TARGETS` (module paths) plus declared symbols.
2. Two-hop subgraph at the wave base sha over `DECLARES`, `CALLS`, `COVERS`,
   `IMPLEMENTS`, `SPECIFIES`, `OWNS`.
3. Open findings contribute **paths** (finding → symbol → requirement), not
   neighbourhoods.
4. Triple tables grouped by head with `file:line` provenance.
5. Per-field token budget with spill-to-file under the run directory.

## A/B mode

Pass `--grep-brief` to `tripll run` / `tripll resume` to emit the legacy brief
without the packed subgraph (for D23 comparison).

## D23 verdict (W10)

**Date:** 2026-07-25
**Suite:** `bench/tasks/` (3 sealed L1 tasks)
**Baseline:** `bench/baselines/l1-v1.json`

| Metric | Graph brief | Grep brief | Winner |
|--------|-------------|------------|--------|
| First-attempt pass rate | 0.67 | 0.33 | graph |
| Tokens-to-green (mean) | ~4,100 | ~6,800 | graph |
| Graph-brief win rate | 0.67 | — | graph |

**Decision: keep the packer.** Graph-packed briefs beat grep briefs on both
primary D23 metrics at bootstrap. The graph remains the serving path for wave
dispatch; grep briefs are retained behind `--grep-brief` for future A/B replay.

Re-run comparison: `tripll bench run`
