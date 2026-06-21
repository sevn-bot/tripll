# test-creator

Single **test owner** for tests-first tripll runs. Authors the entire suite in **Wave 1**
(`role: test-author`), right after the W0 contract gate. Counterpart to **wave-runner**
(implementation, which may not touch tests).

## Contract source (tests-first)

Author RED tests from:

1. **sevn spec rows** — `specs/NN-*.md` § sections and append-only `### 10.X` rows (assumed
   authored by a prior spec/plan agent); these are the normative contract alongside the plan.
2. **W0 locked decisions** — `## Decisions baked into this plan` / design-note locked tables;
   locked rows win over bullet prose.

Use **repo-root-relative** paths when citing specs, PRDs, and source modules (see Path
convention). Validate the plan's refs with `tripll validate-plan <plan.md>` before authoring.

## Path convention

In-repo file references in wave plans and test-plan docs must be **repo-root-relative**
(worktree root = repo root):

- Use `specs/…`, `prd/…`, `src/…`, `plan/…`, `wave-orchestrator/…`, `.cursor/agents/…`.
- **Never** use `../`, `./`, or a leading `/` for in-repo paths.
- External files outside the repo may keep **absolute** paths; tripll exposes their parent
  via `--add-dir` / workspace scope.
- Validate before dispatch: `tripll validate-plan <plan.md>`.

## When to use

| Context | Trigger |
|---------|---------|
| **Tests-first plan** | A wave plan's execution graph marks a wave `role: test-author` (always W1) |
| **Author suite up front** | Operator asks to write the full test suite for a plan before implementation |
| **Test reconciliation** | Orchestrator re-dispatches it to remove satisfied xfail markers after an impl wave, or to amend a test that an impl wave (after 5 attempts) proved wrong |

## Role split

| Agent | Responsibility |
|-------|----------------|
| **test-creator** | Owns `tests/`. Writes unit + integration + functional/E2E tests (happy path, edge cases, error handling) against W0-locked contracts; documents them; leaves them RED |
| **wave-runner** | Implements code to turn the suite green; **forbidden** from editing `tests/`; 5 attempts then escalate |
| **wave-orchestrator** | Dispatches test-creator for the `test-author` wave; on impl escalation, re-dispatches a fresh coding agent (only test-creator ever edits a test) |

## Engine enforcement (W2)

- `WaveSpec`/`WaveNode` carry a `role` field (`impl` | `test-author`, default `impl`), parsed from the
  optional 8th `role` column of the execution graph.
- `graph.TEST_PATHS` (`["tests/", "wave-orchestrator/tests/"]`) is added to every non-`test-author`
  node's `forbidden_paths` via the node-level overlay in `derive_forbidden_paths`; the `test-author`
  node owns them.
- The orchestrator dispatches `role: test-author` nodes to `OrchestratorConfig.agent_test`
  (default `test-creator`); impl nodes go to `agent_wave`.
- Impl waves get `max_attempts = 5` then escalate (`blocked`).

## Coverage matrix (beyond basic testing)

| Layer × scenario | Happy path | Edge cases | Error handling |
|------------------|-----------|------------|----------------|
| **Unit** | documented success | empty/None/boundary/invalid value | error type + message |
| **Integration** | parse→graph→engine→orchestrator wiring | overlap, missing column, ordering | scope breach, partial failure |
| **Functional / E2E** | full run lifecycle (validate→plan→dispatch→verify) | concurrency, resume | timeout, rollback |

## Marking discipline

Cross-wave not-yet-green tests use **non-strict** `xfail(reason="green after WN", strict=False)`.
Never `strict=True` (a later xpass would become a hard failure the impl wave can't fix). After each
impl wave, test-creator removes the satisfied markers (per-impl-wave reconciliation).

## Deliverables

- The full suite under `<package>/tests/`.
- A test-plan doc `<package>/docs/test-plans/<plan-slug>.md` mapping each contract → covering tests.

## Verification

`make -C wave-orchestrator lint` + `make -C wave-orchestrator typecheck` (suite must lint/typecheck
clean while RED). Pytest is red until impl waves land — do not green it by editing source.

## Agent definitions

| Surface | Path |
|---------|------|
| Cursor subagent | [`.cursor/agents/test-creator.md`](.cursor/agents/test-creator.md) |
| Operator docs (this file) | `wave-orchestrator/docs/agents/test-creator.md` |
| Wave template W1 row | [`wave-orchestrator/docs/wave-plan-template.md`](wave-orchestrator/docs/wave-plan-template.md) |

> **Duplication note:** Cursor subagent defs (`.cursor/agents/`) and operator docs
> (`wave-orchestrator/docs/agents/`) are intentionally mirrored — keep both in sync until a
> single-source consolidation lands.

## Related docs

- [`.cursor/agents/wave-runner.md`](.cursor/agents/wave-runner.md) — implementation counterpart
- [`wave-orchestrator/docs/agents/wave-orchestrator.md`](wave-orchestrator/docs/agents/wave-orchestrator.md) — coordinator
- Design: [`wave-orchestrator/docs/design-note.md`](wave-orchestrator/docs/design-note.md) §9 (tests-first model)
