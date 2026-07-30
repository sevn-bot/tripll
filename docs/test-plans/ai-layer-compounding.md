# Test plan — AI-layer compounding

**Source plan:** `docs/plans/ai-layer-compounding.md`
**Contract:** ADRs 014–017, `## Decisions baked into this plan` (R26–R32)
**Wave:** W1 (RED) — `role: test-author`
**Date:** 2026-07-29

## Verification commands

| Command | Expected (W1 close-out) |
|---------|-------------------------|
| `make lint` | exit 0 |
| `make typecheck` | exit 0 |
| `make test` | collect 0 errors; new tests **XFAIL** (RED) |
| `grep -rn 'strict=True' tests/test_rules*.py tests/test_calibrate.py \| wc -l` | 0 |
| `grep -rc 'tier[1-4]' tests/test_rules*.py tests/test_postmortem.py tests/test_calibrate.py tests/test_trackers.py` | ≥ 1 per file |

## Finding → test → wave → tier matrix

| Finding / Decision | Layer | Test file | Test(s) | Wave greens | Tier |
|--------------------|-------|-----------|---------|-------------|------|
| **RULE-01** Rule node kind | Unit | `test_rules.py` | `test_rule_three_states_are_proposed_active_retired` | W3 | 1 |
| **R26** origin mandatory | Unit / Error | `test_rules.py` | `test_origin_*`, `test_origin_missing_rejected` | W2 | 1 |
| **R27** operator promotion only | E2E | `test_rules.py` | `test_e2e_derive_propose_promote_pack_reaches_brief` | W3 | 3 |
| **R31** scoped context pack | Integration | `test_rules.py` | `test_pack_scope_intersection_selects_context_modules` | W2 | 1 |
| **R31** pack_budget_tokens | Unit | `test_rules.py` | `test_pack_never_exceeds_budget_tokens` | W2 | 1 |
| **R31** empty pack | Edge | `test_rules.py` | `test_empty_rule_set_yields_empty_pack_not_crash` | W2 | 1 |
| **CTX-01** derive rules | Integration | `test_rules_derive.py` | `test_derive_writes_rules_with_resolving_origins` | W2 | 1 |
| **R32** honesty (no tests) | Functional | `test_rules_derive.py` | `test_derive_repo_without_tests_says_so_not_coverage_standard` | W2 | 1 |
| **AST-01** executable engine | Unit | `test_rules_executable.py` | `test_structural_match_catches_stdlib_logging_import` | W4 | 1 |
| **AST-01** ast-grep degrade | Error | `test_rules_executable.py` | `test_ast_grep_absent_degrades_warn_exit_zero` | W4 | 1 |
| **AST-01** real binary | Live | `test_rules_executable.py` | `test_real_ast_grep_binary_catches_violation` | W4 | 2 |
| **RULE-03** postmortem | Unit | `test_postmortem.py` | `test_postmortem_contract_too_vague_*` | W3 | 1 |
| **RULE-03** agent diverged | Unit | `test_postmortem.py` | `test_postmortem_agent_diverged_when_scope_breached` | W3 | 1 |
| **CAL-02** Brier score | Unit | `test_calibrate.py` | `test_brier_score_fixed_vectors` | W5 | 1 |
| **R28** advisory only | Functional | `test_calibrate.py` | `test_prediction_does_not_change_routing` | W5 | 1 |
| **CAL-01** predict probability | Unit | `test_calibrate.py` | `test_predict_first_pass_probability_bounded` | W5 | 1 |
| **PM-01** Tracker protocol | Unit | `test_trackers.py` | `test_fake_tracker_protocol_conformance_without_editing_base` | W6 | 1 |
| **PM-02** idempotent publish | Integration | `test_trackers.py` | `test_publish_idempotent_second_run_creates_nothing` | W6 | 1 |
| **PM-02** real gh | Live | `test_trackers.py` | `test_real_gh_tracker_publish_dry_run` | W6 | 2 |
| Compounding loop e2e | E2E | `test_rules.py` | `test_e2e_derive_propose_promote_pack_reaches_brief` | W3 | 3 |
| World: ast-grep | Canary | `test_rules_executable.py` | `test_ast_grep_availability_canary` | — | 4 |
| World: GitHub | Canary | `test_trackers.py` | `test_github_reachability_canary` | — | 4 |

## W1 deliverable map

| W1 item | Path | Status |
|---------|------|--------|
| W1.1 rule model + origin | `tests/test_rules.py` | RED (xfail → W2/W3) |
| W1.2 derive foreign fixture | `tests/test_rules_derive.py` | RED (xfail → W2) |
| W1.3 pack budget / scope | `tests/test_rules.py` | RED (xfail → W2) |
| W1.4 executable rules | `tests/test_rules_executable.py` | RED (xfail → W4) |
| W1.5 postmortem | `tests/test_postmortem.py` | RED (xfail → W3) |
| W1.6 calibrate + R28 | `tests/test_calibrate.py` | RED (xfail → W5) |
| W1.7 trackers fake | `tests/test_trackers.py` | RED (xfail → W6) |
| W1.8 e2e tier 3 | `tests/test_rules.py` | RED (xfail → W3) |
| W1.9 this doc | `docs/test-plans/ai-layer-compounding.md` | W1 |
| W1.10 commit + push | — | pending close-out |

## xfail reconciliation schedule

| After wave | Remove xfails tagged | Status |
|------------|---------------------|--------|
| W2 | `green after W2:` in `test_rules.py`, `test_rules_derive.py` | ✅ F.1 |
| W3 | `green after W3:` in `test_postmortem.py`, e2e in `test_rules.py` | ✅ F.1 |
| W4 | `green after W4:` in `test_rules_executable.py` | ✅ F.1 |
| W5 | `green after W5:` in `test_calibrate.py` | ✅ F.1 |
| W6 | `green after W6:` in `test_trackers.py` | ✅ F.1 |
| Final | sweep all remaining `green after W` markers | ✅ F.1 — 24 removed, 0 stale |

## F.1 reconciliation (2026-07-29, 4041f87)

**Removed:** 24 `@pytest.mark.xfail` decorators (W2–W6 tier-1 + tier-3 e2e; tier-2 xfails
converted to skip-only).

| File | Removed | Now |
|------|---------|-----|
| `test_rules.py` | 10 | 10 pass (incl. tier-3 e2e) |
| `test_rules_derive.py` | 2 | 2 pass |
| `test_rules_executable.py` | 3 | 2 pass, 1 tier-2 skip (no RUN_LIVE) |
| `test_postmortem.py` | 3 | 3 pass |
| `test_calibrate.py` | 3 | 3 pass |
| `test_trackers.py` | 3 | 2 pass, 1 tier-2 skip (no RUN_LIVE) |

**Stale `green after W` count:** 0 (`grep -rn 'xfail' tests/ | grep -c 'green after W'`).

**Tier-2/live (intentional skip without RUN_LIVE=1):**

- `test_real_ast_grep_binary_catches_violation`
- `test_real_gh_tracker_publish_dry_run`

**Remaining suite red (outside F.1 scope):** `test_orchestrator_mode_smoke.py::
test_w0_status_table_parity_terminal_and_dashboard` — CLI `--runs-root` option missing
(pre-existing; not AI-layer contract).

## Rationale log

*(Append one-line notes when orchestrator re-dispatches test-creator to amend a test.)*
