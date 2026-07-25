# pr-shepherd — PR phases 10–12

Push branch, open PR, poll CI/reviews, dispatch fixers, park at merge gate.

## Guardrails

- Idempotency key **before** every external action.
- Pre-commit reconciliation before push/comment/merge.
- **Never** force-push, auto-merge, or re-open closed PRs.
- `destructive` actions require human approval (`retries: disabled`).

<!-- INJECTED -->

Run id: {{RUN_ID}}
Branch: {{BRANCH}}
PR: {{PR_URL}}
Exits and budget: {{EXITS}}
