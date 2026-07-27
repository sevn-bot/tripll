# build-plan-from-errors

Turn gateway **error turn bundles** into **one** runnable **tripll v1** wave-plan per
`make build-plan-from-errors` driver run.

## Path convention

In-repo file references in wave plans must be **repo-root-relative** (worktree root = repo
root):

- Use `specs/…`, `prd/…`, `src/…`, `plan/…`, `wave-orchestrator/…`, `src/tripll/skw/agents/…`.
- **Never** use `../`, `./`, or a leading `/` for in-repo paths.
- External files outside the repo may keep **absolute** paths; tripll exposes their parent
  via `--add-dir` / workspace scope.
- Validate before dispatch: `tripll validate-plan <plan.md>`.

## When to use

- The W5 driver selected one or more **unprocessed** turns with `has_error: true` from
  `<content_root>/.sevn/turns/index.json`.
- Operator wants a remediation plan that groups related failures (not one wave per turn).
- New error turns accumulated since the last successful driver run.

## Read first

1. [`wave-orchestrator/docs/prompts/build-plan-from-errors-problem-types.md`](wave-orchestrator/docs/prompts/build-plan-from-errors-problem-types.md) —
   **turn problem taxonomy** (required checklist per turn × problem kind).
2. [`wave-orchestrator/docs/prompts/build-plan-from-errors.md`](wave-orchestrator/docs/prompts/build-plan-from-errors.md) —
   invocation prompt (W5 driver substitutes `{{…}}` placeholders and appends the taxonomy).
3. [`wave-orchestrator/docs/wave-plan-template.md`](wave-orchestrator/docs/wave-plan-template.md) — required plan sections and
   `tripll_format: 1` graph rules.
4. [`wave-orchestrator/docs/agents/wave-plan-author.md`](wave-orchestrator/docs/agents/wave-plan-author.md) — graph + checklist authoring
   style when converting diagnostics into waves.
5. **Bundle explorer (W3):** `sevn turn-bundle view <turn_id>` — run from the workspace
   directory that owns `sevn.json`. Resolves `turn_id` via `index.json`; filters:
   `--stream log|message|trace`, `--grep <pat>`, `--errors-only`, `--section meta|summary`.
   Mutually exclusive: `--stream` vs `--section`.

## Deliverable

**One** `*-wave-plan.md` file written to:

`runs/input/from-errors-{{RUN_ID}}/`

Only when the driver run found **≥1** error turn (**D6**). Runs with zero new errors emit
no plan file.

The plan must:

- **Classify every error turn** against the full problem taxonomy (see taxonomy template)
  before remediation waves — include a completed **`## Turn problem matrix`** (or decisions
  table with the same columns).
- **Explore every error turn** in the batch via `sevn turn-bundle view` (full message stream
  for operator vs assistant, not only `--errors-only`; plus targeted log/trace passes).
- **Cluster** turns that share a root cause or a single fix into **shared waves** (**D11**)
  using **problem types** (not log errors alone) — cite every contributing `turn_id` in the
  relevant wave bullets.
- Include machine-readable **`## tripll execution graph`** per the template.
- Map remediation to concrete repo paths (`src/sevn/…`, `tests/…`, `wave-orchestrator/…`).

**W0 review gate:** when `review_gate: yes` on W0, human confirmation must cover the filled
taxonomy checklist and grouped problem types before implementation waves run.

## Validation

From `wave-orchestrator/` after the driver writes the plan:

```bash
tripll validate-plan <plan.md>   # from repo root
make validate-set SET=from-errors-{{RUN_ID}}
make plan-set SET=from-errors-{{RUN_ID}}
```

Both must exit 0 before `make run-set SET=from-errors-{{RUN_ID}}`.

## Do not

- Emit more than **one** plan file per `build-plan-from-errors` run (**D6**).
- Create one wave per error turn when one remediation addresses several (**D11**).
- Skip any error `turn_id` the driver passed — read each bundle before grouping.
- Skip the taxonomy checklist — every turn × every problem kind must be classified.
- Guess at root cause without evidence from logs, messages, and traces in the bundle.
- Invent `depends_on` edges not supported by the remediation ordering you derive.
- Use raw `pytest`/`ruff` in `verify_targets` — Makefile targets only.
- Commit unless the operator asks.
