# pr-shepherd

> **Dispatch status:** **Contract only** — PR phases 10–12 via `tripll pr shepherd`; named in `l1_pr.py` metadata but **not** adapter-dispatched in the W9 closure (investigate→fix only).


Owns L1 PR phases 10–12: push, open PR, CI/review fix loop, merge gate (design §11.14).

The **`l1_pr` LangGraph loop** names `pr-shepherd` for push/open-pr steps and lists
`ci-investigator` / `check-fixer` (and review-comment agents) in agent chains. **W9 closed
only the investigate→fix adapter path** for `ci_check` findings — push, open PR, and
review-comment chains remain metadata/CLI until a later wave extends the loop.

| Field | Value |
|-------|-------|
| **class** | infra/executing |
| **edits** | git refs and GitHub state via idempotent commits only |
| **done** | checks green + `pullfrog-approval` → park at merge gate; or exit with receipt |

CLI: `tripll pr shepherd|status|approve-merge`

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`pr-shepherd.md`](../../src/tripll/skw/agents/pr-shepherd.md)
