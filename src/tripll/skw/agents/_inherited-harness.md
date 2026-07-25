# Inherited harness (all agents)

Every agent definition inherits without exception. Authoring waves must include this block
(or an equivalent summary) in each agent file.

## Tool boundary (§7.9.3)

Eight-layer boundary, `default: deny`. Classes: `read` (no approval) · `draft` (no approval,
patches/reports only) · `write` (policy approval, scoped credentials, idempotency key, audit
record) · `destructive` (**human approval, `retries: disabled`** — D15). The model proposes;
the executor decides.

## Handoff contract (§7.9.1)

The 10-field block from `serve/handoff.py`: objective · scope accepted · decisions made · files
changed · external state changed · tests run and results · known failures · git/workspace state ·
next safe action · approval still required.

**Governing rule:** the handoff is evidence, not authority — repository and external state outrank
the summary. Reconcile against live state before acting.

## Loop exits (§7.10)

Respect turn cap (`max_attempts=5`), budget cap, wall clock, no-progress (three unchanged graph
deltas), error threshold (circuit breaker per `(agent, problem_type)`), human interrupt, and
external-event exits. Stop and escalate rather than exceed caps.

## Idempotency (§7.9.5)

Decide/commit split. Write idempotency keys **before** external mutations. Pre-commit
reconciliation before push, comment, merge, or any publish action.

## Graph-packed brief (§7.6)

Briefs are assembled from the Code KG subgraph for the wave — not repo-wide grep, graphify, or
architecture tours unless the brief explicitly marks a coverage gap.
