# plan — technical implementation plan (front-end phase)

Author one implementation plan (`spec/<slug>/plan.md`) from the spec and the constitution.
Third phase of the skw front end (before `tasks`/wave-generator). Not part of the
LangGraph run/review/generate loop.

## Role

1. Read `spec/<slug>/spec.md` and `src/tripll/skw/constitution.md`.
2. Record tech stack, architecture, testing/verify targets, and project structure per
   `src/tripll/skw/spec-templates/plan-template.md`.
3. Complete the **Constitution Check**; justify any deviation in Complexity Tracking or
   change the plan.

## Guardrails

- **Plan-only** — write exactly one `plan.md`; do not edit code, author tests, build, or commit.
- Describe a tests-first approach (behavioral change ⇒ a `role = test-author` wave downstream).
- In-repo paths are repo-root-relative. Never parent-directory, dot-slash, or absolute refs.

## Dispatch

Print prompt: `uv run skw render --stage plan --slug … --title … [CONTEXT=] [PATHS=]`.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
