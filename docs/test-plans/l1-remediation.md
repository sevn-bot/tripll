# Test plan — L1 remediation (gate integrity, security, concurrency, exit closure)

**Source plan:** `ignorelocal/tripll-l1-remediation-wave-plan.md`
**Contract:** `docs/plans/l1-remediation.md`
**Wave:** W1 (RED suite; `role: test-author`)
**Date:** 2026-07-26

## Summary

| Gate | Result (Final close) |
|------|----------------------|
| `make test` | tier1 green; 0 `green after W*` xfails; CAP-01 tier2 probe skipped |
| `make ci` (×2) | green on Final commit |
| `RUN_LIVE=1 make test` | tier2 collected; CAP-01 probe skipped |

Tier markers registered in `pyproject.toml`; `Makefile` deselects `tier2` unless `RUN_LIVE=1` and always deselects `tier4`.

## Pre-fix failure output (baseline before W1 xfails)

Recorded at audit baseline / pre-W1 state:

```text
# TEST-03 — agent roster (14 failures)
tests/test_agent_roster.py::test_section_11_cursor_agent_for_agentdef_hash[spec-cartographer]
  AssertionError: hash_agent_def returned None for spec-cartographer (IDE tree was wrongly required)

# P1 infra classifier — FakeAdapter short failures misclassified as infra (hang)
tests/test_engine.py::test_fifth_failure_escalates_to_failed  # hung >15min

# MODEL-01 — stale default model assertions
tests/test_adapters.py::test_claude_argv_default_model
  AssertionError: assert 'claude-sonnet-5' == 'claude-sonnet-4-6'
```

## Finding → test → wave → tier matrix

| Finding | Test file | Key tests | Green after | Tier |
|---------|-----------|-----------|-------------|------|
| SEC-01, SEC-05, SEC-06 | `tests/test_ui_auth.py` | mutating POST + page shell auth, CSRF, open mode | W3 | 1 |
| SEC-02 | `tests/test_run_id_safety.py` | traversal, symlink, API guard | W4 | 1 |
| SEC-03, SEC-04, R6 | `tests/test_ui_auth.py` | `test_token_transport_*`, `test_base_html_emits_token_via_tojson` | W4 | 1 |
| SEC-07 | `tests/test_log_redact.py` | secret keys, nested keys, env-shaped lines | W4 | 1 |
| OBS-01, TRACE-04 | `tests/test_obs.py` | configurator no-op, httpx guard, local sinks vs exporter | W4/W10 | 1 |
| BUG-01, BUG-03 | `tests/test_cancellation.py` | sibling isolation, no stranded `running` | W5 | 1 |
| BUG-02 | `tests/test_cancellation.py` | `test_cancel_dispatch_leaves_no_surviving_child_process` | W5 | 2 |
| BUG-03 resume | `tests/test_cancellation.py` | kill mid-batch resume | W5 | 2 |
| BUG-cost | `tests/test_cost_accounting.py` | reset + retry cost sum | W6 | 1 |
| BUG-07, DEBT-02 | `tests/test_exits.py` | per-run breaker, `updated_at` on exit record | W6 | 1 |
| BUG-10 | `tests/test_integrate_resume.py` | double integrate, dirty branch | W6 | 2 |
| BUG-06, ARCH-exits, DIR-01 | `tests/test_exit_wiring.py` | Engine `evaluate_exit` wiring | W7 | 3 |
| ARCH-CW, R9 | `tests/test_cw_portability.py` | empty default hotspots, no sevn forbidden paths | W8 | 1 |
| L1-scaffold | `tests/test_pr_loop.py` | adapter invocation in investigate/fix | W9 | 3 |
| TEST-03, ARCH-agentdef | `tests/test_agent_roster.py` | skw hash + no IDE agent path refs in src | W2 | 1 |
| PERF-01 | `tests/test_brief_packer.py` | `_graph_brief_tokens` once per task | W10 | 1 |
| PROV-02/03, CAP-01 | `tests/test_provider_pools.py` | pool unit tests (P1 green); tier2 subprocess probe | P1 | 1/2 |
| P0.1 billing | `tests/test_world_canaries.py` | `gh run list` CI canary | manual | 4 |

## xfail schedule

**Final sweep (2026-07-27):** all `green after W*` xfails removed. W3 auth-success tests now
prime CSRF via `_post_with_auth_and_csrf`. CAP-01 tier2 subprocess probe converted to
`pytest.skip` (pool limits covered by `test_provider_never_exceeds_max_parallel`).

| Marker | Status |
|--------|--------|
| `green after W2`–`W10` | removed at respective wave close-out |
| `green after W3` auth-success (4) | removed Final — CSRF helper |
| `green after P1` tier2 probe | removed Final — skip (CAP-01 deferred) |
| tier4 world canaries | deselected by default (`test_world_canaries.py`) |

All cross-wave markers used `strict=False` while active.

## P3 tracing boundary

- `tests/test_tracing.py` — spine (P3.12); do not duplicate.
- `tests/test_obs.py` — configurator (`tripll.obs.configure_observability`) only.

## Fixture notes (W1)

- `tests/_fakes.py`: FakeAdapter failure text uses JSON `type:result` so P1 `classify_dispatch` treats scripted failures as `failure`, not `infra` (prevents infinite retry loops in engine tests).
