# ci-investigator

> **Dispatch status:** **L1 PR loop (W9)** — adapter-dispatched on the **investigate → fix** path when the `graph` extra is installed. Not dispatched by the main wave Engine.


Triages one failing CI check-run into `Finding` nodes (design §11.10).

| Field | Value |
|-------|-------|
| **class** | triaging |
| **edits** | nothing |
| **done** | every failure line has a `Finding` or is marked unexplained |

PR loop pair (metadata): `ci-investigator` → `check-fixer`. **W9 wired path:** only this
investigate→fix chain is adapter-dispatched (`graph` extra). `pr-shepherd` coordinates PR
phases via CLI but is not adapter-dispatched in that closure.

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`ci-investigator.md`](../../src/tripll/skw/agents/ci-investigator.md)
