# plan — technical implementation plan (tech stack / architecture)

Write **one** implementation plan to the injected Plan path from the existing spec and the
project constitution. This is where tech-stack and architecture decisions live. Do **not**
edit product code, run builds, author tests, or commit.

## Step 1 — Read inputs

- Read the spec at the injected Spec path (requirements, user stories, success criteria).
- Read the [constitution]({{CONSTITUTION_PATH}}) — its principles are binding gates.
- Explore any **Paths to explore** to ground decisions in the real codebase.

## Step 2 — Author the plan

Follow the [plan template]({{PLAN_TEMPLATE}}) structure:

1. **Summary** — primary requirement + technical approach.
2. **Technical Context** — language/version, dependencies, storage, testing (name the `make`
   verify targets waves will run), platform, performance goals, constraints.
3. **Constitution Check** — evaluate the plan against every principle in the constitution;
   any deviation goes in **Complexity Tracking** with justification, or the plan changes.
4. **Project Structure** — the repo-root-relative files in scope (`src/…`, `tests/…`).

## Step 3 — Self-check

- [ ] Exactly one plan written at the injected Plan path.
- [ ] Constitution Check addresses each principle; violations justified or removed.
- [ ] A tests-first approach is described (behavioral change ⇒ a `role = test-author` wave).
- [ ] Verify targets are real `make` targets; in-repo paths are repo-root-relative.
- [ ] Nothing was built, tested, or committed; no test files authored.

<!-- INJECTED -->

Stage: {{STAGE}}
Title: {{TITLE}}
Slug: {{SLUG}}
Base: {{BASE}} | Branch: {{BRANCH}}
Spec path: {{SPEC_PATH}}
Plan path: {{PLAN_DOC_PATH}}
Plan template: {{PLAN_TEMPLATE}}
Constitution: {{CONSTITUTION_PATH}}
Wave-file template (next phase): {{WAVE_TEMPLATE}}

Operator context:
{{OPERATOR_CONTEXT}}

Paths to explore: {{EXPLORE_PATHS}}
