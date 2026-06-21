# wave-plan template (tripll format v1)

Copy to `your-feature-wave-plan.md` and fill in. Required for execution-order
awareness: the **`## tripll execution graph`** table (and optional
**`## tripll batches`**). Run `make validate-set SET=…` before `make plan-set`.

**Normative:** human sections (Goal, Specs, Decisions) follow sevn wave-plan
house style. **Machine sections** (`tripll execution graph`, `tripll batches`)
drive `tripll` scheduling.

## Path convention

In-repo file references in wave plans, orchestrator prompts, and agent briefs must be
**repo-root-relative** (worktree root = repo root):

- Use paths from the repository root: `specs/…`, `prd/…`, `src/…`, `plan/…`,
  `wave-orchestrator/…`, `.cursor/agents/…`.
- **Never** use `../`, `./`, or a leading `/` for in-repo paths.
- External files outside the repo may keep **absolute** paths; tripll exposes their
  parent via `--add-dir` (claude) / workspace scope (cursor).
- Validate before dispatch: `tripll validate-plan <plan.md>` (from repo root).
  Dead in-repo refs abort the run with `<plan> → <bad_ref> (try: <suggested>)`.

## Canonical invocation

Operator runs from repo root or `wave-orchestrator/`:

```bash
make resume-run RUN=<id> PROVIDER=cursor_local MODEL=auto
make run-set SET=<set> PROVIDER=cursor_local MODEL=auto
```

`run` and `resume` honor `--provider`/`--backend` + `--model` end-to-end (no silent
fallback). Cursor-auto = `cursor_local` + `--model auto`.

## Role-dispatch toggle

When `role_dispatch` is effective (`--role-dispatch`, `TRIPLL_ROLE_DISPATCH=1`, plan
`OrchestratorConfig.role_dispatch`, or orchestrator mode implied): `role:test-author` →
`test-creator`, `role:impl` → `wave-runner`. Precedence: CLI > env > plan config >
orchestrator-implied. `tests/` remains forbidden to non-test-author waves regardless.

---

# {{TITLE}} — wave plan

**Status:** Draft
**Date:** {{YYYY-MM-DD}}
**Branch base:** `test-pre`
**Feature branch:** `feature/{{slug}}`

## Goal

One paragraph: what ships and what must not regress.

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Example | `src/sevn/example/module.py` |

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| D1 | Example | Lock at W0 review gate if needed (confirm at W0 review gate). |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets | model | role |
|---------|-------|------------|-------------|--------|----------------|-------|------|
| W0 | Design + scaffolding | | yes | M | make lint, make typecheck | composer-2.5-fast | impl |
| W1 | Author full test suite (RED) | W0 | | L | make lint, make typecheck | | test-author |
| W2 | First implementation wave | W1 | | M | make ci-affected | | impl |
| Final | Integration gate | W2 | | L | make ci-resume | | impl |

Rules:

- `wave_id` — short label (`W0`, `R1`, `Final`, …). Must be unique within the file.
- `depends_on` — comma-separated `wave_id` values that must finish first.
- `review_gate` — `yes` for human-gated waves (typically `W0` only).
- `verify_targets` — Makefile targets only (no raw pytest/ruff).
- `model` — optional per-wave backend model (CLI `MODEL=` overrides when set).
- `role` — `test-author` for the **W1** tests-first wave (dispatched to `test-creator`); `impl`
  (default; blank cell ok) for all others. Tests-first: W0 locks contracts → W1 writes the full RED
  suite → impl waves turn it green and may not edit `tests/` (design-note §9).

## tripll batches (optional)

When omitted, tripll assigns **one batch per topological layer** (serial default).

| batch_id | waves | human_gate | parallel |
|----------|-------|------------|----------|
| Pre-0 | W0 | yes | no |
| A | W1 | | no |
| B | W2 | | yes |
| Final | Final | | no |

## tripll hitl (optional)

Override auto-generated HITL questions for specific gate ids. JSON array; each
object replaces or extends the question with matching `id` (e.g. `gate-1`).

```json
[
  {
    "id": "gate-1",
    "type": "multiple_choice",
    "prompt": "Custom W0.7 review prompt for this plan",
    "options": [
      {
        "id": "confirm",
        "label": "Confirm D1 as written",
        "recommended": true,
        "value": "Lock structured tree + Markdown fast path."
      },
      {
        "id": "other",
        "label": "Other",
        "allow_free_text": true
      }
    ]
  }
]
```

See [`wave-orchestrator/docs/hitl-form-template.md`](wave-orchestrator/docs/hitl-form-template.md) for the full schema.

## Wave W0 — design (review gate)

Allocate the integration worktree and stage ``plan/tripll/`` before any impl wave
dispatches. Agents must confirm branch + staged slice before editing.

- [ ] **W0.0** Allocate worktree on feature branch; stage ``plan/tripll/*-wave-W0.md`` and execution-graph excerpt.
- [ ] **W0.1** …
- [ ] **W0.7** **Review gate:** operator sign-off before W1.

## Wave W1 — author full test suite (test-creator; tests-first, RED)

Dispatched to **test-creator** (`role: test-author`). **Tests must be the first or second
task** in every impl wave checklist (only a setup/scaffold task may precede tests).

- [ ] **W1.0** Read W0 staged plan slice and confirm worktree branch (when not first).
- [ ] **W1.1** Unit tests — pure functions, dataclasses, parsers (happy + edge + error).
- [ ] **W1.2** Integration tests — module wiring, storage/config, adapters.
- [ ] **W1.3** Functional/E2E tests — full user-facing paths / run lifecycle.
- [ ] **W1.4** Error handling — invalid input, scope breach, timeouts (assert type + message).
- [ ] **W1.5** Test-plan doc `docs/test-plans/<slug>.md` mapping each contract → covering tests.
- [ ] Cross-wave reds use non-strict `xfail(reason="green after WN")`; suite lints + typechecks.

## Wave W2 — first implementation wave (wave-runner; turn the suite green)

`role: impl`. May not edit `tests/`; 5 attempts then escalate.

- [ ] **W2.1** …

## Wave Final — integration

- [ ] **Final.1** `make ci-resume` green; one Conventional Commit.

---

See [`wave-orchestrator/docs/examples/telegram-rich-inline-miniapps-wave-plan.v1.md`](wave-orchestrator/docs/examples/telegram-rich-inline-miniapps-wave-plan.v1.md)
for a full execution graph derived from the telegram rich plan.

Use agent [`wave-orchestrator/docs/agents/wave-plan-author.md`](wave-orchestrator/docs/agents/wave-plan-author.md) to convert
legacy wave plans into this format.
