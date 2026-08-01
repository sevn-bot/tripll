# ADR 013 — God-module extraction via façade re-exports

**Status:** Accepted (2026-07-30, Wave W0)
**Decisions:** R33, R34, R38
**Issues:** [#16](https://github.com/sevn-bot/tripll/issues/16)

## Context

Several modules under `src/tripll/` exceed 1,000 lines (`engine.py`, `cli/__init__.py`,
`api/app.py`, `api/ui/router.py`, `ledger.py`). Issue #16 tracks splitting them without behaviour
change. PR #47 (`engine_scheduling.py`) and PR #51 (`cli/_run.py`, `cli/_shared.py`) already proved
the pattern: move code to a sibling module, leave a thin façade of imports plus `__all__`, and assert
`facade.name is submodule.name` in tests.

`ledger.py` alone has ~30 import sites across `engine`, `inject`, `api`, `cli`, `loops/*`, and
`tests/`. A refactor that also rewrites every caller hides two changes in one diff.

Issue #16 deferred the split until a characterization-test prerequisite exists — a suite that locks
the import surface **green at baseline** before any code moves.

## Decision

1. **Façade re-export, never a public-API break (R33).** Each oversized module becomes a thin
   module of imports plus `__all__`; implementation moves to sibling modules. Callers are **not
   edited**. Identity (`facade.name is submodule.name`) is the assertion — equality passes for a
   re-implementation.

2. **Characterization tests precede every extraction (R34).** The suite that locks a surface must be
   **green before** the refactor. The private-name table (names reached from `tests/` and production
   code via `engine._resolve_grep_brief`, `cli._orchestrator_watch_lines`, `api.app._read_config`,
   etc.) is part of the suite.

3. **`_execute_node_body` moves whole, and moves last (R38).** The ~643-line method reads and writes
   15+ `self` fields, holds `self._ledger_lock` across ledger sequences, and owns a closure
   (`_on_stream_event`) that captures the ledger connection. It moves as **one unit** after every
   leaf seam is gone. Lazy imports (`TaskGraphWriter`, `reconcile_run_graph`, `compile_l1_outer_graph`)
   stay function-local when moved.

4. **Direction of dependency must not gain a cycle:** `ledger_*` must not import `engine`; `engine_*`
   must not import `cli` or `api`.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| **Moving call sites instead of keeping a façade** | Two changes in one diff; ~30 ledger import sites alone. The second change is the one that breaks. |
| **`from x import *` in the façade** | mypy strict cannot see through it; `__all__` stops being the contract. |
| **Splitting `_execute_node_body` into phases in the same wave as the move** | Behaviour change wearing a refactor's clothes; resulting diff is unreviewable. |
| **Splitting `_execute_node_body` first because it is the biggest target** | Reads/writes 15+ `self` fields and holds `_ledger_lock`; goes last after leaf seams. |
| **Trusting the existing test suite alone** | Passes today and would still pass with a name silently dropped from a façade — nothing asserts identity. |
| **Rewriting FastAPI routes as a fresh router tree** | W7 converts nested handlers to `APIRouter` + `request.app.state`; it does not redesign the API. |

## Consequences

- Wave plan `god-module-and-ci-posture` serializes extractions W3–W8 with characterization suite W1.
- Final wave adds `make module-size-check` so the 1k rule is enforced, not prose-only.
- `inject.py` and `skw/render.py` remain on an explicit allowlist (not named in #16).
