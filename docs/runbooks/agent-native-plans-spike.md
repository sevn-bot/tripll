# Agent-Native Plans — Phase 0 host spike

**Date:** 2026-06-17
**Branch:** `feature/tripll-agent-native-docker-local`
**Baseline:** `test-pre` @ `58ac06494f333051e46866c22777eb66e8065830`
**Plan:** [`plan/tripll-agent-native-docker-local-wave-plan.md`](../../../plan/tripll-agent-native-docker-local-wave-plan.md) Phase 0 only

## Purpose

Validate Agent-Native Visual Plans UX on the operator machine **before** Docker sidecar work (Phase 1+). Scaffold lives gitignored per locked decision **D1**; this runbook is the only committed artefact from P0.

## Scaffold location (D1)

```text
wave-orchestrator/vendor/agent-native-plans/   # gitignored — do not commit
```

Created with:

```bash
cd wave-orchestrator/vendor
npx @agent-native/core@latest create agent-native-plans --standalone --template plan
cd agent-native-plans
npx pnpm install    # pnpm not on PATH; use npx pnpm or corepack
npx pnpm dev
```

**Package versions (spike):** `@agent-native/core` CLI **0.51.7** (create); scaffold dependency **0.49.25** (lockfile).

## Dev server notes

| Item | Observed |
|------|----------|
| UI URL | `http://localhost:8080/` (Vite default — **not** `:3000` in dev) |
| Production / Docker | Phase 1+ will use `PORT=3000` per deployment docs (D3, D5) |
| SQLite | Auto-created at `vendor/agent-native-plans/data/app.db` (D2 dev-default) |
| Env | `.env.local` generated on first dev start (`BETTER_AUTH_SECRET`); gitignored |
| MCP (dev) | `http://127.0.0.1:5173/_agent-native/mcp` per `agent-native mcp status` when dev session bound |

Dev start applies 30+ SQLite migrations automatically. One transient `NitroViteError: Vite environment "nitro" is unavailable` appeared during `.env.local` hot-restart; server recovered and served HTTP 200 afterward.

## Manual smoke — Plans UI

**Headless check (2026-06-17):** `curl -sI http://localhost:8080/` → **HTTP 200**, HTML title "Agent Native Plans".

**Operator browser check:** Open `http://localhost:8080/` after `npx pnpm dev` in the scaffold directory. Confirm plan list / home loads.

## visual-plan skill (hosted MCP first)

Installed from repo root:

```bash
npx @agent-native/core@latest skills add visual-plan
```

| Item | Result |
|------|--------|
| Skill path | `~/.claude/skills/visual-plan/` |
| MCP URL (default) | `https://plan.agent-native.com/_agent-native/mcp` |
| Auth | **Pending** in non-interactive shell — run `npx @agent-native/core@latest connect https://plan.agent-native.com --client all --scope user` in an interactive terminal |
| Clients registered | claude-code, claude-code-cli, codex (cowork URL-only skipped) |

## /visual-plan workflow (local dev substitute)

The wave-runner subagent cannot invoke Cursor `/visual-plan` slash commands. Equivalent local validation:

1. Dev server running (`npx pnpm dev` in scaffold).
2. Create plan via local action (same MCP surface the skill uses):

```bash
cd wave-orchestrator/vendor/agent-native-plans
npx @agent-native/core@latest action create-visual-plan \
  --title "tripll dashboard UI spike" \
  --brief "Extend tripll FastAPI with Jinja+htmx+SSE dashboard for run observability"
```

3. Open returned URL: `http://localhost:8080/plans/plan-51d3511d0d954ab2` → **HTTP 200**.

**Full wave-plan import:** Passing entire `plan/tripll-dashboard-ui-wave-plan.md` as `--planText` failed Zod validation (auto-generated wireframe captions/summaries exceeded 400–600 char limits). Operator should run `/visual-plan` interactively with the full file after hosted MCP auth, or import in chunks.

**Operator `/visual-plan` on dashboard plan:** In Cursor/Claude Code with skill loaded and MCP authenticated:

```
/visual-plan plan/tripll-dashboard-ui-wave-plan.md
```

Review: editable blocks, diagram section, Open Questions form, comment thread. Compare to raw markdown for W0.7 / Pre-0 gate usability.

## Gitignore (D1, D7)

Added to `wave-orchestrator/.gitignore`:

- `vendor/agent-native-plans/`
- `.env.agent-native`

Never commit: scaffold tree, `node_modules/`, `.env.local`, `.env.agent-native`, `data/app.db`.

## Phase 0 exit criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Standalone Plan template scaffolded under D1 path | Done |
| 2 | `pnpm install && pnpm dev` — UI loads | Done (port **8080** dev) |
| 3 | `visual-plan` skill installed | Done (hosted MCP; auth pending) |
| 4 | `/visual-plan` on dashboard wave-plan usable | Partial — local action + plan URL verified; full-file import needs interactive skill + auth |
| 5 | Operator approves UX before Docker | **Pending operator sign-off** |

## Next

- **Phase 1–2 (Docker):** Done — `make plans-up`, `docker-compose.agent-native-plans.yml`, `.env.agent-native.example`.
- **Phase 3 (localhost MCP):** [`agent-native-plans-localhost-mcp.md`](agent-native-plans-localhost-mcp.md) — repoint skills, curl/MCP verify, volume persistence.

## References

- [Visual Plans template](https://www.agent-native.com/docs/template-plan)
- [Agent-Native Deployment (Docker)](https://www.agent-native.com/docs/deployment)
- [`plan/tripll-agent-native-visual-plans-evaluation.md`](../../../plan/tripll-agent-native-visual-plans-evaluation.md)
