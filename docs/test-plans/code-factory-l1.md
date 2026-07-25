# Test plan — code factory L1 (graph + PR loop + skw absorption)

**Source plan:** `.ignorelocal/waves/tripll-code-factory-wave-plan.md`
**Design:** `.ignorelocal/design/plan/tripll-code-factory-design.md`
**Wave:** Final (all contracts green; 0 xfails)
**Date:** 2026-07-25 (Final sweep 2026-07-25)

## Contract-to-test matrix

### W1.1 — GraphStore (P1, §7.2) → green after **W2**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_graphstore.py` | `test_upsert_idempotent_same_natural_key` | W2 |
| Unit | `test_graphstore.py` | `test_provenance_required_raises_when_omitted` | W2 |
| Integration | `test_graphstore.py` | `test_neighbors_at_sha_filter`, `test_subgraph_at_sha_filter` | W2 |
| Integration | `test_graphstore.py` | `test_paths_recursive_cte_finding_chain` | W2 |
| Integration | `test_graphstore.py` | `test_merge_and_unmerge_reversible` | W2 |

### W1.2 — Ontology (P20, §7.3) → green after **W2**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_ontology.py` | `test_ontology_yaml_loads` | W2 |
| Unit | `test_ontology.py` | `test_every_predicate_has_domain_and_range` | W2 |
| Error | `test_ontology.py` | `test_vague_verbs_rejected` | W2 |
| Functional | `test_ontology.py` | `test_competency_questions_traversable` (10 Qs) | W2 |

### W1.3 — AST extraction (P22, §7.4.1) → green after **W3**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Integration | `test_extract_ast.py` | `test_declares_imports_calls_on_fixture` | W3 |
| Integration | `test_extract_ast.py` | `test_covers_edge_from_test_fixture` | W3 |
| Unit | `test_extract_ast.py` | `test_deterministic_confidence_and_evidence` | W3 |

Fixtures: `tests/fixtures/extract_pkg/`

### W1.4 — Fusion (§7.5) → green after **W3**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_fuse.py` | `test_blocking_reduces_candidate_pairs` | W3 |
| Edge | `test_fuse.py` | `test_disjoint_neighbourhoods_do_not_merge` | W3 |
| Happy | `test_fuse.py` | `test_renamed_symbol_merges` | W3 |
| Unit | `test_fuse.py` | `test_conflicting_attributes_retained_with_provenance` | W3 |
| Integration | `test_fuse.py` | `test_every_merge_is_reversible` | W3 |

### W1.5 — Quality gate (P21, §7.4.2) → green after **W3**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_quality_gate.py` | `test_gate_applies_only_to_semantic_extractors` | W3 |
| Error | `test_quality_gate.py` | `test_low_precision_blocks_and_records_prompt_fix` | W3 |

### W1.6 — Plan v3 (P8, §7.7.1) → green after **W4**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_plan_v3.py` | `test_v3_round_trip` | W4 |
| Integration | `test_plan_v3.py` | `test_v1_fixture_reads_with_warning` | W4 |
| Integration | `test_plan_v3.py` | `test_v2_fixture_reads_with_warning_once` | W4 |
| Unit | `test_plan_v3.py` | `test_target_repo_deadline_budget_targets_outcome_parse` | W4 |

Fixtures: `tests/fixtures/plans/`

### W1.7 — Shape checks (P9/P10/P21, §7.7.2–3) → green after **W4**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_shape_checks.py` | `test_reasonless_depends_on_dropped_and_reported` | W4 |
| Error | `test_shape_checks.py` | `test_parallel_waves_same_file_fail_compile` | W4 |
| Error | `test_shape_checks.py` | `test_parallel_waves_calls_path_refused` | W4 |
| Error | `test_shape_checks.py` | `test_cross_cutting_refactor_refused` | W4 |
| Regression | `test_shape_checks.py` | `test_cw_hotspots_reproduced_by_derivation` | W4 |

### W1.8 — Outcome contracts (P11, §7.9.4) → green after **W7**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_outcome_contracts.py` | `test_all_required_and_not_forbidden` | W7 |
| Error | `test_outcome_contracts.py` | `test_grader_cannot_run_yields_unverified` | W7 |
| Functional | `test_outcome_contracts.py` | `test_completion_message_renders_grader_output` | W7 |
| Edge | `test_outcome_contracts.py` | `test_plausible_artifact_broken_outcome_fails` | W7 |

### W1.9 — Idempotency (P15, §7.9.5) → green after **W7**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Integration | `test_idempotency.py` | `test_commit_node_same_key_runs_once` | W7 |
| Unit | `test_idempotency.py` | `test_decide_node_has_no_side_effects` | W7 |
| Error | `test_idempotency.py` | `test_pre_commit_reconciliation_blocks_on_conflict` (×6) | W7 |
| Error | `test_idempotency.py` | `test_destructive_action_refuses_retry` | W7 |
| Edge | `test_idempotency.py` | `test_two_attempts_one_cancelled_one_delayed_only_current_commits` | W7 |

### W1.10 — Exits (P16, §7.10) → green after **W6**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_exits.py` | `test_exit_fires_and_records` (×8) | W6 |
| Integration | `test_exits.py` | `test_no_progress_uses_graph_delta_hash` | W6 |
| Unit | `test_exits.py` | `test_error_threshold_circuit_breaker_per_agent_problem` | W6 |

### W1.11 — Findings (P14, §7.12) → green after **W8**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_findings.py` | `test_check_run_normalizes_to_finding_schema` | W8 |
| Unit | `test_findings.py` | `test_review_comment_normalizes_to_finding_schema` | W8 |
| Unit | `test_findings.py` | `test_dedup_key_collapses_duplicates` | W8 |
| Integration | `test_findings.py` | `test_about_resolves_to_symbol` | W8 |
| Query | `test_findings.py` | `test_finding_stale_when_about_target_has_valid_to_sha` | W8 |
| Integration | `test_findings.py` | `test_rejected_findings_export_to_learnings` | W8 |

Fixtures: `tests/fixtures/github/`

### W1.12 — PR loop (P13, §8 ph.10–12) → green after **W9**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Integration | `test_pr_loop.py` | `test_external_actions_idempotent_under_replay` (×3) | W9 |
| Functional | `test_pr_loop.py` | `test_loop_dispatches_investigator_then_fixer` | W9 |
| Functional | `test_pr_loop.py` | `test_parks_at_merge_gate_never_auto_merges` | W9 |
| Error | `test_pr_loop.py` | `test_exit_8_abandons_when_pr_closed_externally` | W9 |

### W1.13 — Brief packer (P17, §7.6) → green after **W10**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Unit | `test_brief_packer.py` | `test_seeds_from_targets` | W10 |
| Unit | `test_brief_packer.py` | `test_two_hop_cap_enforced` | W10 |
| Unit | `test_brief_packer.py` | `test_findings_contribute_paths_not_neighbourhoods` | W10 |
| Unit | `test_brief_packer.py` | `test_triple_tables_with_provenance` | W10 |
| Edge | `test_brief_packer.py` | `test_token_cap_spills_to_file` | W10 |
| Functional | `test_brief_packer.py` | `test_handoff_block_has_ten_fields` | W10 |
| E2E | `test_brief_packer.py` | `test_fresh_session_identifies_next_action_from_handoff_only` | W10 |

### W1.14 — Recovery (§5.2, D6) → green after **W6**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| E2E | `test_recovery.py` | `test_kill_mid_loop_resumes_same_thread_id` | W6 |
| Integration | `test_recovery.py` | `test_deleted_checkpoint_recoverable_from_ledger` | W6 |

### W1.15 — Verifier isolation (P12, D17) → green after **W7**

| Layer | File | Tests | xfail |
|-------|------|-------|-------|
| Integration | `test_verifier_isolation.py` | `test_verify_dispatch_uses_different_process_and_worktree` | W7 |
| Error | `test_verifier_isolation.py` | `test_isolation_violation_raises` | W7 |

## xfail schedule (reconciliation)

| Impl wave | Un-xfail tests in | Status |
|-----------|-------------------|--------|
| W2 | W1.1, W1.2 | ✅ green @ 4a8b41a |
| W3 | W1.3, W1.4, W1.5 | ✅ green @ 4096e7b |
| W4 | W1.6, W1.7 | ✅ green @ 9650722 |
| W6 | W1.10, W1.14 | ✅ green @ 78a4873 |
| W7 | W1.8, W1.9, W1.15 | ✅ green @ a5da5b3 |
| W8 | W1.11 | ✅ green @ a83307c |
| W9 | W1.12 | ✅ green @ 723d272 |
| W10 | W1.13 | ✅ green @ 7ecef00 |
| Final | all satisfied xfails dropped | ✅ **0 xfails** — 905 passed @ e0a0ccb+ |

## Shared helpers

- `tests/conftest.py` — `require_module()` lazy import helper (collection-safe).
- `tests/_fakes.py` — existing adapter/worktree fakes (unchanged).

## Files created (W1)

**Test modules (15):** `test_graphstore.py`, `test_ontology.py`, `test_extract_ast.py`,
`test_fuse.py`, `test_quality_gate.py`, `test_plan_v3.py`, `test_shape_checks.py`,
`test_outcome_contracts.py`, `test_idempotency.py`, `test_exits.py`, `test_findings.py`,
`test_pr_loop.py`, `test_brief_packer.py`, `test_recovery.py`, `test_verifier_isolation.py`

**Fixtures:** `tests/fixtures/extract_pkg/`, `tests/fixtures/plans/`, `tests/fixtures/github/`

**Docs:** `docs/test-plans/code-factory-l1.md` (this file)
