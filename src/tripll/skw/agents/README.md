# skw — agent roster (code factory L1)

Kit-local agent briefs. Every agent inherits the harness in
[`_inherited-harness.md`](_inherited-harness.md), including **Operator / CLI / CI lessons (L1–L6)**.
Normative detail: repo-root `ignorelocal/design/operator-cli-ci-lessons.md` (operator-local; not
shipped in the wheel).

## Two-tree split (R3)

| Tree | Role |
|------|------|
| **`src/tripll/skw/agents/`** (this directory) | **Machine contract** — briefs hashed into the task graph as `AgentDef` nodes via `hash_agent_def` |
| **`docs/agents/`** | **Human narrative** — operator docs, procedures, and cross-links; not hashed |

The gitignored `.cursor/` tree is IDE-local only and is **not** an identity source. Cursor may
mirror skw briefs for IDE dispatch, but graph-node digests always come from tracked files here.

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
| quality-critic | reviewing | [`quality-critic.md`](quality-critic.md) |
| smoothing-pass | reviewing | [`smoothing-pass.md`](smoothing-pass.md) |
| reference-picker | authoring | [`reference-picker.md`](reference-picker.md) |

Design extension: [`docs/design/quality-gauntlet.md`](../../../docs/design/quality-gauntlet.md).

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

## Special agents (harvested W2)

| Agent | Path | Notes |
|-------|------|-------|
| browser | [`browser.md`](browser.md) | CDP driver for dashboard visual proof |
| github-issue-manager | [`github-issue-manager.md`](github-issue-manager.md) | Full lifecycle sweep (distinct from triage) |
| wave-orchestrator | [`wave-orchestrator.md`](wave-orchestrator.md) | Serial multitask coordinator |

### Deliberately not ported (W2 harvest)

| Cursor brief | Reason |
|--------------|--------|
| wave-plan-executor | Superseded by [`implementer.md`](implementer.md) |
| wave-plan-author | Superseded by [`plan-author.md`](plan-author.md) |
| parallel-plan-implementer | Superseded by implementer / wave-runner alias |
| v1-wave | Legacy v1 format; tripll uses v3 wave plans |
| spec-implementation, spec-wave, specs-author | Not present in harvest trees |

## Legacy aliases

| Legacy | Successor |
|--------|-----------|
| wave-runner | implementer |
| wave-plan-author | plan-author |
| wave-plan-executor | implementer |

Operator docs mirror: [`docs/agents/`](../../../docs/agents/).
