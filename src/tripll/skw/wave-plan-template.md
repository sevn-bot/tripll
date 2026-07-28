# Wave-file template (waveorch format v2)

Copy to `waves/<slug>-wave-plan.md` and fill in. The **first fenced `toml` block** is the machine
contract; the markdown body below carries human `## Wave <id>` checklists.

**Spec-kit "tasks" artifact.** This is the wave-file the `tasks` phase (wave-generator) produces
from the spec-kit standards — `constitution.md`, `spec/…/spec.md`, `spec/…/plan.md`. Waves are
**grouped by user story** (tag bullets `[US1]`, `[US2]`, …), bullets that touch different files
with no ordering dependency are tagged `[P]` (parallel), and behavioral change uses **tests-first**
ordering via the single `role = test-author` wave. The plan must satisfy every principle in
`constitution.md`.

**Self-contained:** all paths are relative to this kit directory (`src/tripll/skw/`). Use
repo-root-relative paths when referencing project code (`src/…`, `tests/…`). Never parent-directory
refs, dot-slash refs, or absolute paths for in-repo refs.

Validate before dispatch:

```bash
make validate WAVE=waves/your-wave-plan.md
```

---

# {{TITLE}} — wave plan

**Status:** Draft
**Date:** {{YYYY-MM-DD}}

```toml
waveorch_format = 2
title  = "Tier-B quality remediation"
slug   = "tier-b-quality"
base   = "test-pre"
branch = "feature/tier-b-quality"

[pipeline]
max_turns = 3

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.review.inputs]
plugin = "thermo"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[[waves]]
id = "W0"
title = "Design + scaffolding"
depends_on = []
review_gate = true
effort = "M"
role = "impl"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "W1"
title = "Tests for remediation"
depends_on = ["W0"]
effort = "M"
role = "test-author"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "W2"
title = "Implementation wave"
depends_on = ["W1"]
effort = "M"
role = "impl"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W2"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]
```

## TOML block schema (machine contract)

| Field | Required | Type | Rules |
|-------|----------|------|-------|
| `waveorch_format` | yes | int | Must be `2`. |
| `title` | yes | string | Non-empty display title. |
| `slug` | yes | string | Non-empty short id (used in output paths). |
| `base` | yes | string | Git diff base ref (e.g. `test-pre`, `origin/main`). |
| `branch` | yes | string | Feature branch name (never auto-switched by the driver). |
| `[pipeline]` | yes | table | Loop driver settings. |
| `pipeline.max_turns` | yes | int | Max review→generate turns (≥ 1). |
| `[pipeline.run]` | yes | table | Wave execution stage. |
| `pipeline.run.agent` | yes | string | Known agent id (`wave-runner`). |
| `pipeline.run.prompt` | yes | string | Path to prompt template (must exist under kit root). |
| `[pipeline.review]` | yes | table | Review stage. |
| `pipeline.review.agent` | yes | string | Known agent id (`reviewer`). |
| `pipeline.review.prompt` | yes | string | Path to review prompt (must exist). |
| `[pipeline.review.inputs]` | optional | table | Plugin inputs (e.g. `plugin = "thermo"`). |
| `[pipeline.generate]` | yes | table | Generate stage (new wave-file on failed review). |
| `pipeline.generate.agent` | yes | string | Known agent id (`post-review-wave-generator`). |
| `pipeline.generate.prompt` | yes | string | Path to generate prompt (must exist). |
| `[pipeline.model]` | optional | table | Plan-wide model defaults (`model`, `max_tokens`, `temperature`, `thinking`, `extra_args`). |
| `[pipeline.models.<agent>]` | optional | table | Per-agent override keyed by agent id (`wave-runner`, `test-creator`, `reviewer`, …). |
| `[pipeline.<stage>.model]` | optional | table | Stage override for `run` (wave-runner only), `review`, or `generate`. |
| `[[waves]]` | yes | array | ≥ 1 wave row. |
| `waves[].id` | yes | string | Unique, non-empty wave id (`W0`, `Final`, …). |
| `waves[].title` | yes | string | Short human title. |
| `waves[].depends_on` | yes | array | List of wave ids that must finish first (may be empty). |
| `waves[].review_gate` | optional | bool | `true` stops the orchestrator for operator sign-off. |
| `waves[].effort` | optional | string | `S`, `M`, or `L` (default `M`). |
| `waves[].role` | optional | string | `impl` (default) or `test-author` — see **Tests-first** below. |
| `waves[].verify` | optional | array | Shell strings run after the wave (see verify policy). |

### Tests-first (`role = test-author`)

- Include **exactly one** `role = test-author` wave per plan when using the tests-first model.
- **Post-review remediation plans** (from **post-review-wave-generator**) always use tests-first: W0 optional,
  W1 (or T1) test-author mandatory, impl waves after test-author, then `Final`.
- That wave runs once before impl waves; the LangGraph pipeline / `skw.render` dispatch **test-creator** (not wave-runner).
- Every `role = impl` wave after test-author must depend on it (directly or transitively via `depends_on`).
- Prerequisite impl waves before test-author (in its `depends_on` chain) are exempt.
- Plan new/changed tests only in test-author wave bullets; impl waves must not assign test file authoring.
- Only **test-creator** may create or edit `tests/`; impl waves are forbidden from touching tests.

### Agent model configuration

Resolution order (later wins): `skw.toml` `[agent]` → `[agent.models.<agent>]` → wave-file
`[pipeline.model]` → `[pipeline.models.<agent>]` → `[pipeline.<stage>.model]` → env
(`SKW_MODEL`, `SKW_MODEL_<AGENT>`).

Supported keys in any model table: `model`, `max_tokens` (alias `max_token_out`), `temperature`,
`thinking` (`low` \| `medium` \| `high` \| `xhigh` \| `max`), `extra_args` (CLI passthrough list).

Kit defaults live in [`skw.toml`](skw.toml). **`make pipeline-build WAVE=…`** writes gitignored
`waves/<slug>.pipeline.json` and `waves/<slug>.pipeline.html` showing each pipeline agent in order
with resolved model parameters (`make validate` is read-only).

### Spec-kit task conventions (body bullets)

- **User-story grouping:** tag each bullet with the spec user story it serves (`[US1]`, `[US2]`,
  …) so a story can be implemented and verified independently.
- **Parallel marker:** tag bullets that touch different files with no ordering dependency `[P]`.
  Waves that can run concurrently share the same `depends_on`.
- **Optional `[spec]` table:** you may record the source artifacts in the TOML block, e.g.
  `[spec]` with `constitution = "constitution.md"`, `spec = "spec/<slug>/spec.md"`,
  `plan = "spec/<slug>/plan.md"`. The validator ignores unknown tables, so this is advisory
  provenance only.

### Checkbox reconciliation (run agents)

When **test-creator** or **wave-runner** completes a wave, it **must** edit this wave-file and flip
every satisfied bullet in **its assigned `## Wave <id>` section** from `- [ ]` to `- [x]` with
`(YYYY-MM-DD ✅: <evidence>)`. Run agents may edit only their wave section (not TOML, not other waves).
**reviewer** writes `review-result.json` only; **post-review-wave-generator** writes new wave-files;
**orchestrator** coordinates and does not flip checkboxes.

### Known agents

`wave-runner`, `test-creator`, `reviewer`, `post-review-wave-generator`, `orchestrator`, `wave-generator` — must match a file under `agents/` or be one
of these built-in ids.

### Verify policy (D6)

Each `verify` entry is a shell command string. When `skw.toml` sets `verify.make_only = true` (the
default), every entry must start with `make ` (space after make). When `make_only` is `false`, entries
without the prefix produce a **warning** only.

### Per-wave commit & push (D9 — deterministic `commit_wave` node)

When `skw.toml` sets `[git].commit_per_wave = true` (the default), the LangGraph **`commit_wave`**
node runs after each wave's agent state **and** verify pass: it stages tracked changes, commits
(`feat(<slug>)` / `test(<slug>)`: `<wave-id> — <title>`), and pushes to the plan `branch` on
`[git].remote` when `push_per_wave = true`. This is **not** an agent prompt step — wave-runner and
test-creator reconcile checkboxes only. The node resolves the branch's worktree via `git worktree list`
and never switches the current branch. Use `SKW_DRYRUN=1` to print git argv without executing.

The headless driver is **`uv run skw run --wave …`**, not a markdown orchestrator subagent.
Legacy [`scripts/orchestrate.sh`](scripts/orchestrate.sh) is retained for reference only.

### Graph rules (validator)

1. Every `depends_on` target must match a `waves[].id`.
2. The dependency graph must be **acyclic** (DFS cycle detection).
3. At least one **terminal** wave exists (a wave id not listed in any other wave's `depends_on`).
4. `review_gate`, when present, must be a boolean.
5. `effort` must be one of `S`, `M`, `L`.
6. `role` must be `impl` or `test-author`.
7. At most one `test-author` wave per file; impl waves after test-author must depend on it (directly or transitively); impl prerequisite waves before test-author are exempt.

### Body ↔ graph cross-check

1. Every `waves[].id` must have a matching markdown heading: `## Wave <id>` or `## Wave <id> — <title>`.
2. Each wave section must contain at least one task bullet (`- [ ]` or `- [x]`).
3. No **orphan** headings — every `## Wave …` id must appear in the TOML graph.

### Path hygiene

In-repo references in the markdown body (markdown links `](path)` and backtick path tokens) must not
use parent-directory refs, dot-slash refs, or absolute paths. Use kit-relative or project-root-relative paths (`prompts/…`,
`src/…`).

---

## Wave W0 — design (review gate)

- [ ] **W0.1** [US1] Example setup/foundational bullet — replace with real work items.
- [ ] **W0.5** **Review gate:** operator sign-off before the next wave.

## Wave W1 — tests for remediation (test-author)

- [ ] **W1.1** [US1] [P] Add or update tests under `tests/…` covering the remediation (RED OK before impl).
- [ ] **W1.2** [US2] [P] Assert behavior that must not regress after refactors.

## Wave W2 — implementation

- [ ] **W2.1** [US1] Example impl bullet — product code only; no new test file authoring.

## Wave Final — integration gate

- [ ] **Final.1** Run the wave's `verify` targets and confirm green.
