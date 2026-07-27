# Code factory L1 — Wave W0 baseline

**Date:** 2026-07-25
**Branch:** `wave/code-factory-l1`
**Baseline SHA:** `f140160` (`feat: add agent config and about-tripll help site`)

## Verification

| Gate | Result |
|------|--------|
| `make check` | **541 passed**, **24 skipped** |

Recorded on a clean tree at baseline SHA before any W0 product-code changes.

## Scope

W0 is documentation-only: baseline record, anchor freeze, ADRs, GitHub defect issues, and git guard.
No `src/` changes in this wave.

## Design ↔ code reconciliation (W0.3)

Re-verified 2026-07-25 against tripll @ `f140160`. The design ↔ code table in
`.ignorelocal/waves/tripll-code-factory-wave-plan.md` remains accurate — **all rows still show
drift = yes** as expected pre-implementation. No row corrections required at W0.

| Area | Status |
|------|--------|
| Graph substrate (SQLite, three layers) | missing — drift yes |
| Plan format v3 / shape checks | missing — drift yes |
| LangGraph seam | missing — drift yes |
| Outcome contracts / `unverified` | missing — drift yes |
| PR phase / findings graph | missing — drift yes |
| Ledger as system of record | present — drift no (preserve) |
| skw packaging defects | present — drift yes |

See `docs/baseline/anchor-freeze-w0.md` for frozen live-code line numbers.
