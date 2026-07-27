You are running **verifier-setup** for sevn.bot — a one-time scaffold that leaves the
repo with a per-task **`/verify`** skill, a documented stack launcher, and a confirmed
driver for agentic proof-before-PR.

Follow the kit skill at [`spec-kit-wave/skills/verifier-setup/SKILL.md`]({{SKILL_PATH}}).
Use the verify template at [`spec-kit-wave/skills/verifier-setup/assets/verify.template.md`]({{TEMPLATE_PATH}}).

## Operator context

{{CONTEXT_BLOCK}}

## Paths to explore (repo-root-relative)

{{PATHS_BLOCK}}

## sevn.bot defaults (use when inventory confirms stock layout)

| Item | Default |
| --- | --- |
| Stack up | `make compose-up` then readiness: `curl -sf http://127.0.0.1:${SEVN_GATEWAY_PORT:-3001}/ready` |
| Mission Control URL | `http://127.0.0.1:${SEVN_GATEWAY_PORT:-3001}/` |
| Web driver | `cursor-ide-browser` MCP (Cursor) |
| Telegram driver | `telegram_test` skill; exercise via `make telegram-e2e` after `sevn telegram-test login` |
| Mid-branch regression | `make ci-affected` |
| Python-only regression | `make lint && make typecheck` |
| Evidence dir | `evidence/` (must be gitignored) |
| Kit skills install | `make -C spec-kit-wave install-skills` |

## Instructions

### 1. Inventory (Step 0)

Read Makefile targets, `.cursor/skills/`, `.claude/skills/`, existing `verify` skill,
`docs/telegram-e2e-developer-guide.md`, and operator context above. Record reuse vs create.

### 2. Investigate (Step 1)

Hardcode real values for the generated `/verify` skill — do not leave upstream placeholders.

### 3. Prerequisites (Step 2)

Ensure stack path, driver, and `evidence/` + `.gitignore` entry exist.

### 4. Ask the operator (Steps 3–4)

Use `AskQuestion` (Cursor/Claude) for:

1. **Run mode** — local (recommended) vs sandbox (only if they already have one).
2. **Driver** — confirm web vs Telegram vs CLI for this repo's primary verification surface.

### 5. Generate `/verify` (Step 5)

Write **both**:

- `.cursor/skills/verify/SKILL.md`
- `.claude/skills/verify/SKILL.md`

from the template with all template placeholders filled. Preserve any existing hand-edits
when updating.

### 6. Hand off (Step 6)

Summarize: how to run `/verify`, run mode, driver, prerequisites, and whether
`make install-skills` was run.

## Self-check

- [ ] Did not clobber working stack or driver setup without merging edits.
- [ ] Generated `/verify` skill has no unfilled template tokens.
- [ ] `evidence/` is gitignored.
- [ ] Did not commit unless asked.
- [ ] Did not run full task verification unless explicitly requested.
