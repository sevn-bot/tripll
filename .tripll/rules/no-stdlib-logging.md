---
rule_id: no-stdlib-logging
state: active
origin: codebase://about-tripll/_standards/coding-standards.md:271
scope:
  - "src/tripll/**"
executable: ast-grep
severity: error
pattern: import logging
---

Use loguru; never stdlib `logging`.

**Why:** `logging` bypasses `log_redact`, so a redacted key ships to disk unredacted.
**Evidence:** `about-tripll/_standards/coding-standards.md:271`, CLAUDE.md logging rule.
**Test:** `tests/test_rules.py::test_no_stdlib_logging`
