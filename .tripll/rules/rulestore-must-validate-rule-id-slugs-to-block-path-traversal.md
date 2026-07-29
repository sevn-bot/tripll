---
rule_id: rulestore-must-validate-rule-id-slugs-to-block-path-traversal
state: active
origin: finding://thermos-gate#rule-id-traversal
scope:
  - "src/**"
---

RuleStore must validate rule_id slugs to block path traversal

**Why:** Promoted from a resolved finding.
**Evidence:** `src/tripll/rules/store.py:58`.
**Test:** `tests/test_rules.py::test_rulestore_must_validate_rule_id_slugs_to_block_path_traversal`
