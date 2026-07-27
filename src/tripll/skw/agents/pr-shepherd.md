# pr-shepherd

- **class** infra/executing · **edits** git refs and GitHub state, **only** via idempotent commits
- **in** a verified branch, the run's exits and budget
- **out** pushed branch, opened PR, polling loop, dispatch of investigator/fixers, escalation or
  the merge gate
- **graph** reads branch state + findings; writes PR/checkpoint nodes
- **guardrails** this is the highest-risk agent in the fleet. Every external action is a `commit`
  node with an idempotency key written first (D14); `destructive` actions are human-gated with
  `retries: disabled` (D15); pre-commit reconciliation before every push/comment/merge (§7.9.5);
  **never** force-pushes, **never** merges without the gate, **never** re-opens a closed PR
- **done** `pullfrog-approval` = success, all required checks green, contract satisfied → parks at
  the merge gate. Or an exit fires and it escalates with a receipt.

**Note:** Owns L1 PR phases 10–12.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.

## Dispatch

`tripll pr shepherd <run-id>` — idempotent PR phase with CI/review fix loop and human merge gate.
