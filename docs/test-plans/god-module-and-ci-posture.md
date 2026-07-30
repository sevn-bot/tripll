# Test plan — god-module extraction and mergeCraft CI posture

**Source plan:** `docs/plans/god-module-and-ci-posture.md` (synced from `ignorelocal/tripll-god-module-and-ci-posture-wave-plan.md`)
**ADRs:** `docs/decisions/013-god-module-extraction.md`, `docs/decisions/018-mergecraft-ci-trigger-posture.md`
**Wave:** W1 (characterization suite) + Final (xfail sweep)
**Date:** 2026-07-30

## Contract-to-test matrix

| Finding | Test file | Test(s) | Wave greens | Tier |
|---------|-----------|---------|-------------|------|
| GOD-01…05 façade identity | `test_module_facades.py` | `test_engine_scheduling_identity_reexports`, `test_cli_run_identity_reexports` | W3–W8 extend identity rows | 1 |
| GOD-01…05 public surface | `test_module_facades.py` | `test_engine_public_surface_resolves`, `test_ledger_imported_names_resolve`, `test_api_app_create_app_resolves` | ongoing | 1 |
| GOD-05 `ledger.__all__` | `test_module_facades.py` | `test_ledger_all_contains_every_imported_name` | **W3** | 1 |
| R34 private-name table | `test_module_facades.py` | `test_private_name_table_resolves` | W3–W8 | 1 |
| GOD-02 CLI registration order | `test_module_facades.py` | `test_cli_command_inventory_snapshot`, `test_cli_help_lists_hidden_run_commands` | **W6** | 3 |
| GOD-03/04 route table | `test_module_facades.py` | `test_create_app_route_table_snapshot` | **W7**, **W8** | 3 |
| GOD-06 module size | `test_module_size.py` | `test_module_size_under_limit_outside_allowlist` | **Final** | 1 |
| CI-02 pin parity (match/drift) | `test_mergecraft_ref_parity.py` | `test_matching_pins_pass_temp_repo`, `test_drifted_pins_fail_temp_repo` | baseline green | 1 |
| CI-02 offline skip / CI fail | `test_mergecraft_ref_parity.py` | `test_unreachable_ref_offline_skips_with_warning`, `test_unreachable_ref_ci_fails` | **W2** | 1 |
| CI-02 live fetch | `test_mergecraft_ref_parity.py` | `test_real_repo_parity_check_passes` | baseline when `RUN_LIVE=1` | 2 |

## xfail reconciliation tracker

All strict xfails for completed waves were removed at Final. No rows remain.

## Post-extraction module sizes (Final)

Non-allowlisted modules named in #16 (all ≤ 1000 lines):

| Path | Lines |
|------|------:|
| `src/tripll/engine.py` | 986 |
| `src/tripll/cli/__init__.py` | 116 |
| `src/tripll/api/app.py` | 122 |
| `src/tripll/api/ui/router.py` | 90 |
| `src/tripll/ledger.py` | 117 |

Allowlisted (tracked separately, not in #16):

| Path | Lines |
|------|------:|
| `src/tripll/inject.py` | 1284 |
| `src/tripll/skw/render.py` | 1161 |

## Private-name table (W0.3 verified)

| Name | Module | Importer |
|------|--------|----------|
| `_resolve_grep_brief` | `engine` | `tests/test_brief_graph_pack.py` |
| `_MAX_NO_PROGRESS_DISPATCHES` | `engine` | `tests/test_w2_controls.py` |
| `__doc__` | `engine` | `tests/test_provider_pools.py` |
| `_run_integration` | `cli` | `tests/test_delivery_live_fixture.py` |
| `_orchestrator_watch_lines` | `cli` | `tests/test_orchestrator_mode_smoke.py` |
| `_rewrite_run_inject_argv` | `cli` | `tests/test_inject.py`, `tests/test_reconcile.py` |
| `_resolve_runs_root` | `api.app` | `tests/test_api.py` |
| `_read_config`, `_slug_profile_id`, `_tripll_argv` | `api.app` | `api/ui/router.py` |

## Verification commands (W1 acceptance)

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/test_module_facades.py tests/test_module_size.py tests/test_mergecraft_ref_parity.py
make test -- -k "module_facades" -q
make test -- -k "module_size" -q
make test -- -k mergecraft -q
grep -rn 'strict=True' tests/test_module_size.py tests/test_module_facades.py tests/test_mergecraft_ref_parity.py | wc -l  # 0
grep -c ' is ' tests/test_module_facades.py  # >= 1
grep -rn 'xfail' tests/ | grep 'green after W\|green after Final' | wc -l  # 0 after Final
```
