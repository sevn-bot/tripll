# plan — technical implementation plan (front-end phase)

Author one implementation plan (`spec/<slug>/plan.md`) from the spec and the constitution.
Third phase of the spec-kit-wave front end (before `tasks`/wave-generator). Not part of the
LangGraph run/review/generate loop.

## Role

1. Read `spec/<slug>/spec.md` and `spec-kit-wave/constitution.md`.
2. Record tech stack, architecture, testing/verify targets, and project structure per
   `spec-kit-wave/spec-templates/plan-template.md`.
3. Complete the **Constitution Check**; justify any deviation in Complexity Tracking or
   change the plan.

## Guardrails

- **Plan-only** — write exactly one `plan.md`; do not edit code, author tests, build, or commit.
- Describe a tests-first approach (behavioral change ⇒ a `role = test-author` wave downstream).
- In-repo paths are repo-root-relative. Never parent-directory, dot-slash, or absolute refs.

## Dispatch

Print prompt: `make plan SLUG= TITLE= [CONTEXT=] [PATHS=]`. Headless: `make plan-run …`
(renders `spec-kit-wave/prompts/plan.md` via `skw render --stage plan`).
