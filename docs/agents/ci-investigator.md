# ci-investigator

Triages one failing CI check-run into `Finding` nodes (design §11.10).

| Field | Value |
|-------|-------|
| **class** | triaging |
| **edits** | nothing |
| **done** | every failure line has a `Finding` or is marked unexplained |

PR loop pair: `ci-investigator` → `check-fixer`. Dispatched by `pr-shepherd`.

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`ci-investigator.md`](../../src/tripll/skw/agents/ci-investigator.md)
