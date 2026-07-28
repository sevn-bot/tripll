# Wave-file template (waveorch format v2)

Copy to `waves/<slug>-wave-plan.md` and fill in. The **first fenced `toml` block** is the machine
contract; the markdown body below carries human `## Wave <id>` checklists.

**Self-contained:** all paths are relative to kit paths are under `src/tripll/skw/`. Use
repo-root-relative paths when referencing project code (`src/…`, `tests/…`). Never parent-directory
refs, dot-slash refs, or absolute paths for in-repo refs.

Validate before dispatch:

```bash
make validate WAVE=waves/your-wave-plan.md
```

---

# Demo W3 scaffold — wave plan

**Status:** Draft
**Date:** 2026-06-24

```toml
waveorch_format = 2
title  = "Demo W3 scaffold"
slug   = "demo-w3"
base   = "test-pre"
branch = "feature/demo-w3"

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
id = "Final"
title = "Integration gate"
depends_on = ["W0"]
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
| `[[waves]]` | yes | array | ≥ 1 wave row. |
| `waves[].id` | yes | string | Unique, non-empty wave id (`W0`, `Final`, …). |
| `waves[].title` | yes | string | Short human title. |
| `waves[].depends_on` | yes | array | List of wave ids that must finish first (may be empty). |
| `waves[].review_gate` | optional | bool | `true` stops the orchestrator for operator sign-off. |
| `waves[].effort` | optional | string | `S`, `M`, or `L` (default `M`). |
| `waves[].role` | optional | string | `impl` (default) or `test-author`. |
| `waves[].verify` | optional | array | Shell strings run after the wave (see verify policy). |

### Known agents

`wave-runner`, `reviewer`, `post-review-wave-generator`, `orchestrator`, `wave-generator` — must match a file under `agents/` or be one
of these built-in ids.

### Verify policy (D6)

Each `verify` entry is a shell command string. When `skw.toml` sets `verify.make_only = true` (the
default), every entry must start with `make ` (space after make). When `make_only` is `false`, entries
without the prefix produce a **warning** only.

### Graph rules (validator)

1. Every `depends_on` target must match a `waves[].id`.
2. The dependency graph must be **acyclic** (DFS cycle detection).
3. At least one **terminal** wave exists (a wave id not listed in any other wave's `depends_on`).
4. `review_gate`, when present, must be a boolean.
5. `effort` must be one of `S`, `M`, `L`.
6. `role` must be `impl` or `test-author`.

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

- [ ] **W0.1** Example task bullet — replace with real work items.
- [ ] **W0.5** **Review gate:** operator sign-off before the next wave.

## Wave Final — integration gate

- [ ] **Final.1** Run the wave's `verify` targets and confirm green.
