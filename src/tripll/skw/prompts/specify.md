# specify — feature spec author (front-end phase)

Author one feature specification at the injected Spec path from operator context, focusing on
**what** and **why**. First phase of the spec-kit front end (before `clarify` → `plan` →
`tasks`). Not part of the LangGraph run/review/generate loop.

## Step 1 — Read inputs

- Read the operator brief and explore every path listed under **Paths to explore**.
- Use the spec template at **Spec template** for structure and section order.

## Step 2 — Author the spec

Write exactly one `spec.md` at **Spec path** with:

1. User stories (prioritized, independently testable).
2. Functional requirements and key entities.
3. Success criteria and assumptions.
4. Tag unknowns as `[NEEDS CLARIFICATION: …]` for the `clarify` phase.

## Step 3 — Self-check

- [ ] Exactly one spec written at the injected Spec path.
- [ ] Open unknowns are tagged `[NEEDS CLARIFICATION: …]` (not silently omitted).
- [ ] No tech-stack or architecture decisions (those belong in `plan`).
- [ ] Only the spec file was edited; nothing built, tested, or committed.

## Guardrails

- **Spec-only** — do not edit product code, author tests, run builds, or commit.
- In-repo paths are repo-root-relative. Never parent-directory, dot-slash, or absolute refs.

<!-- INJECTED -->

Stage: {{STAGE}}
Title: {{TITLE}}
Slug: {{SLUG}}
Spec path: {{SPEC_PATH}}
Spec template: {{SPEC_TEMPLATE}}

Operator context:
{{OPERATOR_CONTEXT}}

Paths to explore: {{EXPLORE_PATHS}}
