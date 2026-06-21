# Test plan — test-creator + tests-first wave model

**Source plan:** `plan/test-creator-tests-first-wave-plan.md`
**Wave:** W1 (tests-first; red expected)
**Date:** 2026-06-17

## Contract-to-test mapping

### C1: `role` column parsing (D5, design-note §9.1)

| Layer | Test file | Class / function | Status |
|-------|-----------|------------------|--------|
| Unit | `test_role_column.py` | `TestWaveSpecRoleDefault` | xfail (W2) |
| Unit | `test_role_column.py` | `TestRoleColumnParsing` | xfail (W2) |
| Integration | `test_role_column.py` | `TestRolePropagation` | xfail (W2) |
| Edge | `test_role_column.py` | `TestBackwardCompatibility` | green now |
| Edge | `test_role_column.py` | `TestInvalidRoleValue` | xfail (W2) |

### C2: TEST_PATHS forbidden-path derivation (D7, design-note §9.2)

| Layer | Test file | Class / function | Status |
|-------|-----------|------------------|--------|
| Unit | `test_forbidden_test_paths.py` | `TestTestPathsConstant` | xfail (W2) |
| Unit | `test_forbidden_test_paths.py` | `TestPathsOverlapWithTestDirs` | green now |
| Integration | `test_forbidden_test_paths.py` | `TestDeriveForbiddenWithTestPaths` | xfail (W2) |
| Integration | `test_forbidden_test_paths.py` | `TestGraphBuildTestPathOverlay` | xfail (W2) |
| Edge | `test_forbidden_test_paths.py` | `TestEmptyTestPaths` | xfail (W2) |
| Edge | `test_forbidden_test_paths.py` | `TestTestPathsOverlapWithOwned` | xfail (W2) |
| Regression | `test_forbidden_test_paths.py` | `TestDeriveForbiddenRegressionGuard` | green now |

### C3: Agent selection (D5, design-note §9.3)

| Layer | Test file | Class / function | Status |
|-------|-----------|------------------|--------|
| Unit | `test_agent_selection.py` | `TestOrchestratorConfigAgentTest` | xfail (W2) |
| Unit | `test_agent_selection.py` | `TestParsedPromptAgentTest` | xfail (W2) |
| Integration | `test_agent_selection.py` | `TestAgentTestParsedFromPrompt` | xfail (W2) |
| Integration | `test_agent_selection.py` | `TestAgentTestInConfig` | xfail (W2) |
| Integration | `test_agent_selection.py` | `TestBriefAgentSelection` | xfail (W2) |
| Edge | `test_agent_selection.py` | `TestNoOrchestratorAgentKey` | green now |

### C4: max_attempts = 5 + escalation banner (D1/D3, design-note §9.4)

| Layer | Test file | Class / function | Status |
|-------|-----------|------------------|--------|
| Unit | `test_max_attempts.py` | `TestEngineMaxAttemptsDefault` | xfail (W2) |
| Unit | `test_max_attempts.py` | `TestEscalationBannerParameterised` | xfail (W2) |
| Integration | `test_max_attempts.py` | `TestBriefRetryPolicy` | xfail (W2) |
| Integration | `test_max_attempts.py` | `TestEngineRetryLoop5Attempts` | xfail (W2) |
| Updated | `test_engine.py` | `test_fifth_failure_escalates_to_failed` | xfail (W2, was `test_third_...`) |
| Updated | `test_brief.py` | `test_retry_policy_escalates` | xfail (W2, asserts 5 not 3) |
| Updated | `test_ledger.py` | `test_retry_escalate_pattern` | xfail (W2, asserts 5 not 3) |

### C5: cookiecutter scaffold (D4, design-note §9.5)

| Layer | Test file | Class / function | Status |
|-------|-----------|------------------|--------|
| Unit | `test_scaffold.py` | `TestScaffoldCommand` | xfail (W5) |
| Unit | `test_scaffold.py` | `TestNormalizationMap` | xfail (W5) |
| Edge | `test_scaffold.py` | `TestNormalizationIdempotent` | xfail (W5) |
| Error | `test_scaffold.py` | `TestScaffoldSubprocessFailure` | xfail (W5) |

## Coverage matrix summary

| Contract | Unit | Integration | Edge | Error | Total tests |
|----------|------|-------------|------|-------|-------------|
| C1: role column | 3 classes | 1 class | 2 classes | (in edge) | ~12 |
| C2: TEST_PATHS | 2 classes | 2 classes | 2 classes | -- | ~14 |
| C3: agent selection | 2 classes | 3 classes | 1 class | -- | ~11 |
| C4: max_attempts | 2 classes | 2 classes | -- | -- | ~10 |
| C5: scaffold | 2 classes | -- | 1 class | 1 class | ~9 |
| **Updated existing** | -- | -- | -- | -- | 3 |
| **Total** | | | | | ~59 |

## xfail wave mapping

| Target wave | What turns green |
|-------------|------------------|
| W2 | C1 (role parsing), C2 (TEST_PATHS), C3 (agent_test), C4 (max_attempts=5, escalation banner), updated existing tests |
| W5 | C5 (scaffold_package, normalization map, error handling) |

## Files created/modified

### New test files
- `wave-orchestrator/tests/test_role_column.py`
- `wave-orchestrator/tests/test_forbidden_test_paths.py`
- `wave-orchestrator/tests/test_agent_selection.py`
- `wave-orchestrator/tests/test_max_attempts.py`
- `wave-orchestrator/tests/test_scaffold.py`

### Modified existing tests (3→5)
- `wave-orchestrator/tests/test_engine.py` — `test_third_failure_escalates_to_failed` renamed to `test_fifth_failure_escalates_to_failed`, asserts 5 attempts
- `wave-orchestrator/tests/test_brief.py` — `test_retry_policy_escalates` asserts `max_attempts: 5`
- `wave-orchestrator/tests/test_ledger.py` — `test_retry_escalate_pattern` simulates 5 attempts

### Test plan doc
- `wave-orchestrator/docs/test-plans/test-creator-tests-first.md` (this file)
