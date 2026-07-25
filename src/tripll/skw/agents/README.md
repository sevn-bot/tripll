# spec-kit-wave — agent roster (code factory L1)

Kit-local agent briefs. Every agent inherits the harness in
[`_inherited-harness.md`](_inherited-harness.md).

## L1 roster (design §11)

| Agent | Class | Path |
|-------|-------|------|
| spec-cartographer | authoring | [`spec-cartographer.md`](spec-cartographer.md) |
| graph-extractor | infra | [`graph-extractor.md`](graph-extractor.md) |
| graph-librarian | verifying | [`graph-librarian.md`](graph-librarian.md) |
| graph-fuser | reviewing | [`graph-fuser.md`](graph-fuser.md) |
| plan-author | authoring | [`plan-author.md`](plan-author.md) |
| plan-shape-critic | reviewing | [`plan-shape-critic.md`](plan-shape-critic.md) |
| test-creator | executing | [`test-creator.md`](test-creator.md) |
| implementer | executing | [`implementer.md`](implementer.md) |
| wave-verifier | verifying | [`wave-verifier.md`](wave-verifier.md) |
| ci-investigator | triaging | [`ci-investigator.md`](ci-investigator.md) |
| check-fixer | executing | [`check-fixer.md`](check-fixer.md) |
| review-comment-triager | triaging | [`review-comment-triager.md`](review-comment-triager.md) |
| review-comment-fixer | executing | [`review-comment-fixer.md`](review-comment-fixer.md) |
| pr-shepherd | infra/executing | [`pr-shepherd.md`](pr-shepherd.md) |

## Ported front-end agents (§11.15)

| Agent | Path |
|-------|------|
| wayfinder | [`wayfinder.md`](wayfinder.md) |
| specify | [`specify.md`](specify.md) |
| clarify | [`clarify.md`](clarify.md) |
| plan | [`plan.md`](plan.md) |
| prd-author | [`prd-author.md`](prd-author.md) |
| docs-folder-author | [`docs-folder-author.md`](docs-folder-author.md) |
| changelog-author | [`changelog-author.md`](changelog-author.md) |
| changelog-reviewer | [`changelog-reviewer.md`](changelog-reviewer.md) |
| reviewer | [`reviewer.md`](reviewer.md) |
| post-review-wave-generator | [`post-review-wave-generator.md`](post-review-wave-generator.md) |
| pr-verifier | [`pr-verifier.md`](pr-verifier.md) |
| github-issue-triage | [`github-issue-triage.md`](github-issue-triage.md) |
| verifier-setup | [`verifier-setup.md`](verifier-setup.md) |

## Legacy aliases

| Legacy | Successor |
|--------|-----------|
| wave-runner | implementer |
| wave-plan-author | plan-author |
| wave-plan-executor | implementer |

Operator docs mirror: [`docs/agents/`](../../../docs/agents/).

Cursor subagent defs: [`.cursor/agents/`](../../../.cursor/agents/) (content-hashed as `AgentDef`).
