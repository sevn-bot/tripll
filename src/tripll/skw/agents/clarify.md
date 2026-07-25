# clarify — spec disambiguation (front-end phase)

Reduce ambiguity in an existing `spec/<slug>/spec.md` before the `plan` phase. Second phase of
the spec-kit-wave front end. Not part of the LangGraph run/review/generate loop.

## Role

1. Scan the spec for `[NEEDS CLARIFICATION: …]` markers and underspecified areas.
2. Ask a small, prioritized set of coverage-based questions.
3. Record answers in a dated `## Clarifications` section and update the affected
   requirements/scenarios in place.

## Guardrails

- **Spec-only** — edit only the spec file; do not touch code, tests, or wave-files.
- Do not run builds or commit.
- Do not silently drop open items — leave unresolved unknowns tagged.

## Dispatch

Print prompt: `make clarify SLUG= TITLE= [CONTEXT=] [PATHS=]`. Headless: `make clarify-run …`
(renders `spec-kit-wave/prompts/clarify.md` via `skw render --stage clarify`).
