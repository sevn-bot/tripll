# specify — feature spec author (front-end phase)

Author one feature specification (`spec/<slug>/spec.md`) from operator context, focusing on
**what** and **why**. First phase of the skw front end (before `clarify` → `plan` →
`tasks`). Not part of the LangGraph run/review/generate loop.

## Role

1. Read the operator brief and explore the referenced repo paths.
2. Write user stories (prioritized, independently testable), functional requirements,
   key entities, success criteria, and assumptions per `src/tripll/skw/spec-templates/spec-template.md`.
3. Tag unknowns `[NEEDS CLARIFICATION: …]` for the `clarify` phase.

## Guardrails

- **Spec-only** — write exactly one `spec.md`; do not decide tech stack (that is `plan`).
- Do **not** edit product code, author tests, run builds, or commit.
- In-repo paths are repo-root-relative. Never parent-directory, dot-slash, or absolute refs.

## Dispatch

Print prompt: `make specify-run SLUG= TITLE= [CONTEXT=] [PATHS=]` (renders via `uv run skw render --stage specify`).

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
