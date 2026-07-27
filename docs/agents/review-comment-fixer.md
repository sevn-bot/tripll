# review-comment-fixer

> **Dispatch status:** **Contract only** — follows `review-comment-triager` in PR-loop metadata; **not** adapter-wired in the W9 closure.


Fixes accepted review findings; resolution queued for approval (design §11.13).

Follows `review-comment-triager` in PR-loop **metadata** only — **not** adapter-dispatched
until a future loop extension (W9 closed `ci_check` investigate→fix only).

| Field | Value |
|-------|-------|
| **class** | executing |
| **edits** | files named by accepted review findings |
| **done** | finding `state = fixed`; re-verify green |

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`review-comment-fixer.md`](../../src/tripll/skw/agents/review-comment-fixer.md)
