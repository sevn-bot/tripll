# wave-verifier

Isolated post-implementation verification gate (design §11.9, D17).

| Field | Value |
|-------|-------|
| **class** | verifying |
| **edits** | nothing |
| **inputs** | fresh checkout at wave commit, outcome contract, no implementer transcript |
| **done** | `Verdict` persisted and linked `GRADED_BY`; `unverified` when grader cannot run |

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`wave-verifier.md`](../../src/tripll/skw/agents/wave-verifier.md)
