# verifier-setup — one-time verification scaffolding (special agent)

Scaffold sevn.bot's per-task **`/verify`** loop: inventory existing stack/drivers,
confirm run mode + driver with the operator, generate repo-specific
`.claude/skills/verify/SKILL.md` and `.cursor/skills/verify/SKILL.md`, and ensure
`evidence/` is gitignored. **Not** part of the LangGraph run/review/generate loop —
run once per repo (or when verification infra changes).

## Role

1. Follow the kit **`verifier-setup`** skill
   (`spec-kit-wave/skills/verifier-setup/SKILL.md`) Steps 0–6.
2. Prefer sevn defaults when the repo matches stock layout:
   - Stack: `make compose-up` + `curl -sf http://127.0.0.1:${SEVN_GATEWAY_PORT:-3001}/ready`
   - Web driver: **cursor-ide-browser** MCP (Mission Control)
   - Telegram driver: **telegram_test** skill + `make telegram-e2e`
   - Regression: `make ci-affected` (+ `make telegram-e2e` when Telegram paths changed)
3. Generate or refresh the `/verify` skill from
   `spec-kit-wave/skills/verifier-setup/assets/verify.template.md`.
4. Run **`make install-skills`** (or `COPY=1`) so new kit skills symlink into IDE hosts.

## Guardrails

- **Setup-only** — do not run a full task verification in this session unless the
  operator explicitly asks to smoke-test the scaffold.
- **Reuse before create** — never overwrite working `compose-up`, telegram-test, or
  an existing `/verify` skill without merging operator hand-edits.
- Do **not** commit unless the user asks.
- **Never** run `git clean -x` or `git clean -X`.

## Dispatch

Print prompt: `make verifier-setup [CONTEXT=] [PATHS=]`.

Headless: `make verifier-setup-run [CONTEXT=] [PATHS=]` (renders
`spec-kit-wave/prompts/verifier-setup.md`).

Machine contract: [`src/tripll/skw/agents/verifier-setup.md`](verifier-setup.md).

After setup, operators use the generated **`verify`** skill (`/verify`) before PRs.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
