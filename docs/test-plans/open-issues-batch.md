# Test plan — open GitHub issues batch (#62 façade characterization)

**Source plan:** `ignorelocal/open-issues-wave-plan.md`
**ADRs:** `docs/decisions/013-god-module-extraction.md`
**Wave:** W1 (characterization) + W5/W6 (xfail reconciliation for identity rows)
**Date:** 2026-08-03

## Contract-to-test matrix

| Contract | Test file | Test(s) | Wave greens | Tier |
|----------|-----------|---------|-------------|------|
| ADR 013 inject façade module name | `test_inject_facade.py` | `test_inject_module_name_contract` | baseline | 1 |
| ADR 013 inject docstring exports | `test_inject_facade.py` | `test_inject_docstring_exports_match_inventory`, `test_inject_documented_export_resolves` | baseline | 1 |
| ADR 013 inject import surface | `test_inject_facade.py` | `test_inject_imported_name_resolves` | baseline | 1 |
| ADR 013 inject symbol naming | `test_inject_facade.py` | `test_inject_symbol_name_matches_attribute` | baseline | 1 |
| ADR 013 render façade module name | `test_skw_render_facade.py` | `test_render_module_name_contract` | baseline | 1 |
| ADR 013 render docstring exports | `test_skw_render_facade.py` | `test_render_docstring_exports_match_inventory`, `test_render_documented_export_resolves` | baseline | 1 |
| ADR 013 render import surface | `test_skw_render_facade.py` | `test_render_imported_name_resolves` | baseline | 1 |
| ADR 013 render symbol naming | `test_skw_render_facade.py` | `test_render_symbol_name_matches_attribute` | baseline | 1 |
| ADR 013 inject `is` re-export identity | `test_inject_facade.py` | _(add after W5 extraction)_ | **W5 reconcile** | 1 |
| ADR 013 render `is` re-export identity | `test_skw_render_facade.py` | _(add after W6 extraction)_ | **W6 reconcile** | 1 |

## Imported-name coverage (AST scan at W1)

### `tripll.inject`

Scanned roots: `src/`, `tests/`, `scripts/`.

| Name | Importers (sample) |
|------|-------------------|
| `HotfixTask`, `InjectError`, `apply_hotfix_inject`, `load_hotfix_tasks`, `reconcile_run_graph` | `api/_inject.py`, `cli/_run.py`, `tests/test_inject.py` |
| `InjectError`, `apply_wave_add` | `cli/_wave.py`, `tests/test_wave_add.py` |
| `merge_injected_artefacts` | `tests/test_inject_orchestrator_ordering.py` |

### `tripll.skw.render`

Scanned roots: `src/`, `tests/`.

| Name | Importers (sample) |
|------|-------------------|
| `topo_sort` | `skw/pipeline.py`, `skw/pipeline_diagram.py`, `skw/__init__.py` |
| `render_prompt` | `skw/driver.py`, `skw/cli.py`, `skw/__init__.py` |
| `render_frontend_prompt`, `render_prd_author_prompt`, `render_wave_generator_prompt` | `skw/cli.py`, `onboard/emitters.py`, tests |
| `FRONTEND_STAGES`, `RENDER_STAGES`, `VALID_STAGES`, `PLACEHOLDER_RE`, … | `skw/__init__.py`, `skw/cli.py`, tests |

## xfail reconciliation tracker

No xfails at W1 — characterization suite is green at baseline.

## Verification commands (W1 acceptance)

```bash
make lint
make typecheck
make test -- -k "inject_facade or skw_render_facade" -q
make test
```
