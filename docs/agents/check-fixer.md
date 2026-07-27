# check-fixer

> **Dispatch status:** **L1 PR loop (W9)** — adapter-dispatched after `ci-investigator` on the closed investigate→fix path (`graph` extra). Not dispatched by the main wave Engine.


Minimal fix for accepted CI findings (design §11.11).

| Field | Value |
|-------|-------|
| **class** | executing |
| **edits** | files named by accepted findings |
| **done** | failing check passes; no regressions |

PR loop pair (metadata): `ci-investigator` → `check-fixer`. **W9 wired path:** adapter-dispatched
on the fix step after `ci-investigator` (`graph` extra only).

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`check-fixer.md`](../../src/tripll/skw/agents/check-fixer.md)
