# Test plan — L1 remediation (gate integrity, security, concurrency, exit closure)

**Source plan:** `ignorelocal/tripll-l1-remediation-wave-plan.md`
**Contract:** `docs/plans/l1-remediation.md`
**Wave:** W1 (RED suite; `role: test-author`)
**Date:** 2026-07-26

## Summary

| Gate | Result (W1 close) |
|------|-------------------|
| `make test` | 940 passed, **33 xfailed**, 0 failed, 8 tier2/tier4 deselected |
| `RUN_LIVE=1 make test` | 940 passed, **36 xfailed**, tier2 collected |
| `make lint && make typecheck` | exit 0 |

Tier markers registered in `pyproject.toml`; `Makefile` deselects `tier2` unless `RUN_LIVE=1` and always deselects `tier4`.

## Pre-fix failure output (baseline before W1 xfails)

Recorded at audit baseline / pre-W1 state:

```text
# TEST-03 — agent roster (14 failures)
tests/test_agent_roster.py::test_section_11_cursor_agent_for_agentdef_hash[spec-cartographer]
  AssertionError: missing .cursor/agents/spec-cartographer.md for AgentDef hash

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
| TEST-03, ARCH-agentdef | `tests/test_agent_roster.py` | skw hash + no `.cursor/agents` in src | W2 | 1 |
| PERF-01 | `tests/test_brief_packer.py` | `_graph_brief_tokens` once per task | W10 | 1 |
| PROV-02/03, CAP-01 | `tests/test_provider_pools.py` | pool unit tests (P1 green); tier2 subprocess probe | P1 | 1/2 |
| P0.1 billing | `tests/test_world_canaries.py` | `gh run list` CI canary | manual | 4 |

## xfail schedule

| Marker reason prefix | Count (approx) | Reconcile wave |
|---------------------|----------------|----------------|
| `green after W2` | 15 | W2 |
| `green after W3` | 10 | W3 |
| `green after W4` | 18 | W4 |
| `green after W5` | 4 | W5 |
| `green after W6` | 5 | W6 |
| `green after W7` | 5 | W7 |
| `green after W8` | 3 | W8 |
| `green after W9` | 2 | W9 |
| `green after W10` | 2 | W10 |
| `green after P1` | 1 (tier2 probe) | P1 (if still red) |

All cross-wave markers use `strict=False`.

## P3 tracing boundary

- `tests/test_tracing.py` — spine (P3.12); do not duplicate.
- `tests/test_obs.py` — configurator (`tripll.obs.configure_observability`) only.

## Fixture notes (W1)

- `tests/_fakes.py`: FakeAdapter failure text uses JSON `type:result` so P1 `classify_dispatch` treats scripted failures as `failure`, not `infra` (prevents infinite retry loops in engine tests).
