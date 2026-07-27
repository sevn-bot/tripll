# review-comment-triager

> **Dispatch status:** **Contract only** — named in `l1_pr` agent chains for review-comment findings; **not** adapter-wired (W9 closed the `ci_check` path only).


Classifies PR review threads into findings (design §11.12).

| Field | Value |
|-------|-------|
| **class** | triaging |
| **edits** | nothing (drafts only) |
| **done** | every open thread has a disposition |

PR loop pair (metadata): `review-comment-triager` → `review-comment-fixer`. **Not adapter-wired**
in the W9 closure — only the `ci_check` investigate→fix chain is live today.

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`review-comment-triager.md`](../../src/tripll/skw/agents/review-comment-triager.md)
