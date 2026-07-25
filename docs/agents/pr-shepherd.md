# pr-shepherd

Owns L1 PR phases 10–12: push, open PR, CI/review fix loop, merge gate (design §11.14).

| Field | Value |
|-------|-------|
| **class** | infra/executing |
| **edits** | git refs and GitHub state via idempotent commits only |
| **done** | checks green + `pullfrog-approval` → park at merge gate; or exit with receipt |

CLI: `tripll pr shepherd|status|approve-merge`

Inherited harness: [`_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md) ·
skw brief: [`pr-shepherd.md`](../../src/tripll/skw/agents/pr-shepherd.md)
