# Anchor freeze — Wave W0

**Date:** 2026-07-25
**Baseline SHA:** `f140160`
**Purpose:** Frozen line numbers for live-code anchors referenced by the L1 wave plan. Re-grep at
each wave that touches these files.

## State and retry constants

| Anchor | File | Lines |
|--------|------|-------|
| `WaveState` literal | `src/tripll/ledger.py` | 55–65 |
| `RunState` literal (adjacent) | `src/tripll/ledger.py` | 54 |
| `Engine.__init__` `max_attempts=5` | `src/tripll/engine.py` | 919 |
| `_VERIFY_ONLY_RETRIES = 2` | `src/tripll/engine.py` | 834 |
| `_MAX_NO_PROGRESS_DISPATCHES = 1` | `src/tripll/engine.py` | 859 |
| `_DEFAULT_MAX_PARALLEL = 3` | `src/tripll/engine.py` | 861 |

## Graph model

| Anchor | File | Lines |
|--------|------|-------|
| `CW_HOTSPOTS` dict (CW-1 … CW-5) | `src/tripll/graph.py` | 31–40 |
| `RunGraph.validate()` | `src/tripll/graph.py` | 243 |
| `TEST_PATHS` | `src/tripll/graph.py` | 365 |

## Adapters and brief

| Anchor | File | Lines |
|--------|------|-------|
| `BACKENDS` mapping | `src/tripll/adapters/__init__.py` | 39–43 |
| Brief no-exploration line | `src/tripll/brief.py` | 39 |

## HITL marker protocol

| Marker / constant | File | Lines |
|-------------------|------|-------|
| `HITL_FORM_FILE = "hitl-form.json"` | `src/tripll/hitl.py` | 48 |
| `HITL_RESPONSES_FILE = "hitl-responses.json"` | `src/tripll/hitl.py` | 49 |
| `PRE0_APPROVED_MARKER = "pre0-approved"` | `src/tripll/hitl.py` | 50 |
| `REVIEW_GATE_PENDING_MARKER = "review-gate-pending.md"` | `src/tripll/hitl.py` | 51 |
| `REVIEW_GATE_APPROVED_MARKER = "review-gate-approved"` | `src/tripll/hitl.py` | 52 |
| Engine mirror: `_PRE0_MARKER` | `src/tripll/engine.py` | 828 |
| Engine mirror: `_REVIEW_GATE_MARKER` | `src/tripll/engine.py` | 832 |
| Engine mirror: `_REVIEW_GATE_APPROVED` | `src/tripll/engine.py` | 833 |

## Notes

- `cursor_cloud` is registered in `BACKENDS` but dispatch remains deferred upstream.
- `RunGraph.validate()` checks cycles, overlap, and CW seam coverage only — no stop-rule or fake-edge checks yet (W4).
