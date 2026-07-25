# wave-generator (tasks phase) — author one wave-file v2 from the spec-kit artifacts

Create **one** validated wave-file under `{{OUTPUT_DIR}}/` — this is the spec-kit **tasks**
phase: turn the spec's user stories and the plan's decisions into wave-file v2 waves. Do not
edit product code, run builds, or commit.

## Prerequisite — read the spec-kit standards

Read these if present (they are authored by the front-end phases `specify` → `clarify` →
`plan`); fall back to the injected **Operator context** when a file is missing:

- [`constitution.md`](constitution.md) — governing principles; the plan MUST satisfy them.
- `spec/{{SLUG}}/spec.md` — prioritized user stories (US1, US2, …), requirements, success criteria.
- `spec/{{SLUG}}/plan.md` — tech stack, architecture, and the `make` verify targets to use.

Also explore any **Paths to explore** in the injected block.

## Step 1 — Understand the goal

- **Title** and **slug** define the plan identity; output file is `{{OUTPUT_DIR}}/<slug>-wave-plan.md`.
- **Base** / **Branch** set the git diff scope for later review stages.
- Map each user story (US1, US2, …) from the spec to one or more waves.

## Step 2 — Design the wave graph (spec-kit task conventions)

- Break work into dependency-safe waves (`W0`, …, `Final`), **grouped by user story** so each
  story is independently implementable and testable (label bullets with their story id, e.g.
  `[US1]`). Prefer a `W0` setup/foundational wave when stories share prerequisites.
- **Tests-first (TDD):** include **exactly one** `role = test-author` wave before impl waves;
  later `role = impl` waves must depend on it (directly or transitively); prerequisite impl
  waves before test-author are exempt. Plan new/changed tests only in test-author bullets —
  only **test-creator** may edit `tests/`.
- **Parallelism:** mark bullets that touch different files with no ordering dependency `[P]`
  (spec-kit parallel marker). Waves that can run concurrently share the same `depends_on`.
- **Wide-refactor exception:** if the work is one mechanical change whose blast radius fans
  across the whole codebase (a rename, a retype) so no vertical slice can land green, don't
  force tracer bullets — sequence **expand** (add new beside old, one wave) → **migrate**
  (blast-radius-sized batch waves, each `depends_on` expand, CI green batch to batch because the
  old form still exists) → **contract** (delete old, `depends_on` every migrate batch).
- Set `review_gate = true` on design/scaffolding when operator sign-off is needed.
- Choose Makefile **verify** targets per wave from the plan (each must start with `make `).
- Record locked decisions (from the plan's Constitution Check) so they do not drift.

## Step 3 — Author one wave-file

Write a single file: `{{OUTPUT_DIR}}/<slug>-wave-plan.md`. Follow
[`wave-plan-template.md`]({{TEMPLATE_PATH}}) format v2:

1. **Goal** — what the plan ships; what must not regress. Reference `spec/{{SLUG}}/spec.md`,
   `spec/{{SLUG}}/plan.md`, and `constitution.md`.
2. **Files in scope** — table of paths each wave touches (repo-root-relative).
3. **Decisions baked into this plan** — frozen choices from the plan / Constitution Check.
4. First `toml` block — `waveorch_format = 2`, pipeline tables:
   - `[pipeline.run]` → `wave-runner` / `prompts/wave-runner.md`
   - `[pipeline.review]` → `reviewer` / `prompts/reviewer.md`
   - `[pipeline.generate]` → `post-review-wave-generator` / `prompts/post-review-wave-generator.md`
5. `[[waves]]` rows with valid `depends_on` (acyclic graph, terminal wave).
6. Per-wave checklists (`## Wave W0`, …) with actionable `- [ ]` bullets tagged `[US#]` and
   `[P]` where applicable.

In-repo paths must be repo-root-relative (`src/…`, `tests/…`). Never parent-directory refs, dot-slash refs, or a leading slash.

## Step 4 — Self-check

- [ ] Exactly **one** `*-wave-plan.md` written under Output.
- [ ] File would pass `make validate WAVE=…`.
- [ ] TOML graph acyclic; every `depends_on` target exists as a wave id.
- [ ] Every user story from the spec maps to at least one wave/bullet (tagged `[US#]`).
- [ ] If plan includes impl work: exactly one `test-author` wave; every impl wave after it reaches it via `depends_on`.
- [ ] The plan satisfies every principle in `constitution.md` (or records a justified deviation).
- [ ] If the work is a wide refactor: expand/migrate/contract waves are sequenced via `depends_on`, not forced into an ordinary vertical slice.
- [ ] Pipeline agents use known ids (`wave-runner`, `test-creator`, `reviewer`, `post-review-wave-generator`).
- [ ] Nothing was run, built, tested, or committed; no test files were authored.

<!-- INJECTED -->

Title: {{TITLE}}
Slug: {{SLUG}}
Base: {{BASE}} | Branch: {{BRANCH}}
Output: {{OUTPUT_DIR}}
Template: {{TEMPLATE_PATH}}
Constitution: constitution.md
Spec (if present): spec/{{SLUG}}/spec.md
Plan (if present): spec/{{SLUG}}/plan.md

Operator context:
{{OPERATOR_CONTEXT}}

Paths to explore: {{EXPLORE_PATHS}}

Wave-generator agent: wave-generator
Wave-generator prompt: prompts/wave-generator.md
