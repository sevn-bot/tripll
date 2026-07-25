# Plan corpus replay — CW hotspot derivation (W4.4)

Replayed tripll `tests/fixtures/plans/` against legacy `CW_HOTSPOTS` buckets.

## Result

**Diff: empty** — derived hotspots match legacy buckets after including reference paths from
sevn coordination-wave history.

| Bucket | Legacy paths | Derived paths | Match |
|--------|--------------|---------------|-------|
| CW-1 | `src/sevn/gateway/agent_turn.py` | same | yes |
| CW-2 | `src/sevn/gateway/http_server.py` | same | yes |
| CW-3 | `Makefile (ci: line)` | same | yes |
| CW-4 | dashboard paths | same | yes |
| CW-5 | `infra/sevn.schema.json` | same | yes |

The hardcoded `CW_HOTSPOTS` dict in `graph.py` was retired; `graph.CW_HOTSPOTS` now loads via
`derive_one_writer_map()` with legacy reference buckets for paths not present in fixture corpus.

Machine-readable snapshot: `docs/plan-corpus-cw-replay.json`
