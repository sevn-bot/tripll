# post-review-wave-generator — author one wave-file from review findings

Read the structured review verdict and, **only when changes are required**, produce **one**
new wave-file under `waves/`. Do not edit code, tests, or commit.

## Prerequisite

Read **Verdict path** below. If missing or `verdict: pass`, **stop** — report clean pass and
write no wave-file.

## Step 1 — Load findings

Parse `review-result.json`:

```json
{"verdict": "changes_required", "findings": [...]}
```

Every finding has `id`, `severity`, `file`, `summary`, `evidence`. Do not add findings not
in this file.

## Step 2 — Classify findings

Using [`problem-types.md`](problem-types.md), fill the per-file checklist: for **every**
affected module × **every** problem kind, mark `yes`/`no`; every `yes` needs an evidence
pointer from the review. Record line counts for the 1k-line rule where relevant.

## Step 3 — Group by problem type

Cluster files that share a root cause or a single refactor into shared waves. For each cluster
record: problem type id(s), contributing paths, one-sentence refactor summary, and a
behavior-preservation note (what must not change / which tests guard it). Unrelated clusters
become separate waves in the **same** plan file.

## Step 4 — Author one wave-file

Write a single file under **Output** (injected block below): `<slug>-wave-plan.md` (choose a slug
from the plan title). Follow [`wave-plan-template.md`](wave-plan-template.md) format v2:

1. **Goal** — what the refactor ships; what must not regress.
2. **`## Code-quality problem matrix`** — the Step 2 checklist (file × problem_type × present × evidence).
3. **Files in scope** — table of paths each wave touches.
4. **Decisions baked into this plan** — locked refactor choices.
5. First `toml` block — `waveorch_format = 2`, `[pipeline]`, `[[waves]]` with valid `depends_on`.
6. Per-wave checklists (`## Wave W0`, …) — `- [ ]` bullets citing files + evidence.
7. **`## Wave Final`** — integration gate; `verify` are **Makefile targets only**.

In-repo paths must be repo-root-relative (`src/…`, `tests/…`). Never parent-directory refs, dot-slash refs, or a leading slash.

### Tests-first wave (mandatory)

Every remediation plan **must** include exactly one tests-first wave for **test-creator**. Plan new/changed
tests **only** in that wave's bullets — never assign test file authoring to impl waves.

Example TOML (optional W0, mandatory test-author, then impl):

```toml
[[waves]]
id = "W0"
title = "Design + scaffolding"
depends_on = []
review_gate = true
role = "impl"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "W1"
title = "Tests for remediation"
depends_on = ["W0"]  # or [] if no W0
role = "test-author"
verify = ["make lint", "make typecheck"]  # or make test on touched paths

[[waves]]
id = "W2"
title = "Refactor cluster A"
depends_on = ["W1"]
role = "impl"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W2"]
role = "impl"
verify = ["make ci-resume"]
```

Test-author wave bullets must list paths under `tests/`, assertions to add or change, and note RED is OK
before impl waves. Impl waves cite existing tests by path only — no new test paths or test-writing tasks.

## Step 5 — Self-check

- [ ] Verdict was `changes_required` before writing.
- [ ] Exactly **one** `*-wave-plan.md` written under Output.
- [ ] Every finding maps to a problem type with evidence.
- [ ] Related findings grouped; all cited paths appear in the plan.
- [ ] TOML graph acyclic; every `depends_on` target exists as a wave id.
- [ ] Exactly **one** `role = test-author` wave; test bullets live only in that wave section.
- [ ] Every `role = impl` wave after test-author reaches test-author via `depends_on` (directly or transitively).
- [ ] No impl wave assigns test file authoring — only **test-creator** may edit `tests/`.
- [ ] Nothing was run, built, tested, or committed.

<!-- INJECTED -->

Plan: {{PLAN_PATH}}
Title: {{TITLE}} (slug: {{SLUG}})
Base: {{BASE}} | Branch: {{BRANCH}}
Output: {{OUTPUT_DIR}}
Verdict path: {{VERDICT_PATH}}
Max turns: {{MAX_TURNS}}

Generate prompt: {{GENERATE_PROMPT}}
Review plugin: {{REVIEW_INPUT_PLUGIN}}

Review context: {{WAVE_ID}} — {{WAVE_TITLE}}
