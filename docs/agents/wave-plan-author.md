# wave-plan-author

Convert or author **tripll v1** wave-plan files for `wave-orchestrator`.

## Path convention

In-repo file references in wave plans must be **repo-root-relative** (worktree root = repo
root):

- Use `specs/…`, `prd/…`, `src/…`, `plan/…`, `wave-orchestrator/…`, `.cursor/agents/…`.
- **Never** use `../`, `./`, or a leading `/` for in-repo paths.
- External files outside the repo may keep **absolute** paths; tripll exposes their parent
  via `--add-dir` / workspace scope.
- Validate before dispatch: `tripll validate-plan <plan.md>`.

## When to use

- Operator has a legacy wave plan (narrative `## Execution order & parallelism` only).
- New feature needs a schedulable wave file with explicit `depends_on` edges.
- `make validate-set SET=…` failed with “missing tripll execution graph”.

## Read first

1. [`wave-orchestrator/docs/wave-plan-template.md`](wave-orchestrator/docs/wave-plan-template.md) — required sections.
2. [`wave-orchestrator/docs/examples/telegram-rich-inline-miniapps-wave-plan.v1.md`](wave-orchestrator/docs/examples/telegram-rich-inline-miniapps-wave-plan.v1.md) — reference graph.
3. Source plan to convert (keep Goal, Files in scope, Decisions, per-wave bullets).

## Deliverable

One `*-wave-plan.md` file containing:

### Required (machine-readable)

**`## tripll execution graph`** with header row (include the optional `role` column):

```markdown
| wave_id | title | depends_on | review_gate | effort | verify_targets | model | role |
```

- Extract waves from **`## Wave checklist`** or `## Wave X` headings in the source.
- **Tests-first model (design-note §9):** always insert a **W1** wave with `role: test-author`
  (title "Author full test suite") that `depends_on: W0`, and point the first implementation wave at
  `depends_on: W1`. The `role` column is `test-author` for that wave and `impl` (or blank → defaults
  to `impl`) for all others.
- Map **`## Execution order & parallelism`** prose into `depends_on`:
  - Default serial chain unless explicit “X needs Y” bullets say otherwise.
  - `W0` → `review_gate: yes`.
  - `Final` → `depends_on` = last implementation waves before integration.
- Every `depends_on` target must appear as a `wave_id` row.

Optional **`## tripll batches`** when the plan documents **parallel tracks**:

```markdown
| batch_id | waves | human_gate | parallel |
```

- Same-batch waves may run concurrently (disjoint paths / separate worktrees).
- If omitted, tripll uses serial topological layers.

### Required (human)

- `## Files in scope` table (paths for CW / lane ownership).
- Per-wave sections (`## Wave W0`, …) preserved from source for wave-runner briefs.

## Validation

From `wave-orchestrator/`:

```bash
tripll validate-plan <plan.md>   # from repo root; dead in-repo refs exit non-zero
make validate-set SET=<input-folder-name>
make plan-set SET=<input-folder-name>   # writes deterministic parallel-wave.md
```

Both must exit 0.

## Do not

- Remove operator decisions or spec/PRD references from the source plan.
- Invent `depends_on` edges not supported by the source execution section.
- Use raw `pytest`/`ruff` in `verify_targets` — Makefile targets only.
- Commit unless the operator asks.

## Example: telegram-rich conversion

Source checklist waves: W0, R1–R4, I1–I3, M1–M2, Final.

Serial graph (matches “Default: serial” in source):

| wave_id | depends_on |
|---------|------------|
| W0 | |
| R1 | W0 |
| R2 | R1 |
| … | … |
| Final | M2, I3 |

See the example file for the full table.
