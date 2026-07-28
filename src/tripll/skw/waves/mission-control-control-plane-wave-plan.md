# Mission Control control plane — wave plan

**Status:** Draft
**Date:** 2026-07-06
**Source:** `plan/mission-control-critical-review-2026-07-04.md` (repo root)

Turn the Mission Control SPA from a developer debug console into an operator **control plane**: fix
self-inflicted breakages (CSP, Chat 503, Terminal), adopt shared UX primitives (human timestamps,
clickable IDs, semantic tokens, full-width layout), rebuild the three flagship views (Sessions,
Traces, Chat), then sweep editability across tabs that already have PUT/POST APIs.

## How to run this plan

Run all commands from the **repo root**. Paths below use `src/tripll/skw/` for kit-local
artifacts unless noted.

### 0. Preflight

```bash
make setup
make validate WAVE=src/tripll/skw/waves/mission-control-control-plane-wave-plan.md
uv run skw pipeline-build --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md
```

`uv run skw pipeline-build` writes gitignored local pipeline artifacts:

- `src/tripll/skw/waves/mission-control-control-plane.pipeline.json`
- `src/tripll/skw/waves/mission-control-control-plane.pipeline.html` (agent order + model params)

Open the HTML in a browser to inspect which model each pipeline agent uses before driving waves.

Create and checkout the feature branch named in the TOML block (`feature/mission-control-control-plane`)
in your sevn.bot worktree before driving waves.

### 1. Headless loop (terminal — full pipeline)

Runs validate → each wave (wave-runner / test-creator) → verify → commit → review → (on fail)
generate, until review passes or `max_turns` is exhausted:

```bash
uv run skw run --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md
```

Useful env overrides:

```bash
SKW_DRYRUN=1 uv run skw run --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md   # print argv, no agent/git
SKW_AUTO_APPROVE=1 uv run skw run --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md   # skip W0 review_gate interrupt
```

### 2. Cursor Multitask — one wave at a time (interactive)

Print a rendered prompt, paste into a **Multitask** agent on the feature branch, then follow
`uv run skw next-step --wave …` after each headless dispatch:

```bash
# W0 design (review gate — operator sign-off before tests/impl)
uv run skw render --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage run --wave-id W0

# W1 tests-first (only agent that may edit tests/)
uv run skw render --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage run --wave-id W1

# W2 … W6 impl waves
uv run skw render --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage run --wave-id W2

# Branch review after all waves
uv run skw render --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage review
```

Headless single-wave dispatch (same prompts, runs `cursor-agent` via `scripts/agent.sh`):

```bash
uv run skw agent-run --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage run --wave-id W2
uv run skw agent-run --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage run --wave-id W1
uv run skw agent-run --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage review
```

Preview prompts without running:

```bash
uv run skw render --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage run --wave-id W3
uv run skw render --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --stage review
```

### 3. Manual stepping with `next-step`

After any `agent-run`, query the next command:

```bash
uv run skw next-step --wave src/tripll/skw/waves/mission-control-control-plane-wave-plan.md --wave-id W2
```

### 4. W0 review gate

W0 sets `review_gate = true`. In `uv run skw run`, the graph **interrupts** until you approve (unless
`SKW_AUTO_APPROVE=1`). Confirm locked decisions D1–D6 before letting W1 (test-author) run.

---

## Goal

| Priority | Theme | Review refs |
|----------|-------|-------------|
| P0 | Un-break CSP/Terminal, Chat JWT, onboarding token leak, locale JSON | S1, Chat 503, Onboarding |
| P0 | Human-readable time/numbers; every ID links to a detail view | S2, S3 |
| P0 | Structured edit for every GET+PUT tab; no dead Actions columns | S4 |
| P1 | Top bar clarity; degraded badge counts configured providers only | S5 |
| P2 | AG-UI / OpenUI stream rendering in Chat + Canvas | S6 |

**Do not regress:** confirm-token discipline on destructive ops, Config tree Validate/Save, Pipelines
Run/Poll/Kill interaction quality, vanilla-JS SPA + uniform `api/v1` REST API shape.

## Files in scope

| Wave | Primary paths |
|------|----------------|
| W0 | This wave-file (locked decisions only) |
| W1 | `tests/e2e/mission-control/`, `tests/gateway/test_mission_spa_mount.py`, new unit tests under `tests/gateway/` / `tests/ui/` as needed |
| W2 | `src/sevn/ui/spa/dashboard/index.html`, `src/sevn/ui/spa/dashboard/static/` (new vendored assets), `src/sevn/gateway/http_server.py`, chat token mint in gateway boot, `src/sevn/ui/spa/dashboard/app.js` (model-params locale) |
| W3 | `src/sevn/ui/spa/dashboard/app.js`, `style.css`, shared MC components (formatters, linkify, drawer, empty-state, tokens) |
| W4 | `app.js` + mission API routers for sessions/traces/chat/canvas; `src/sevn/gateway/` session + trace handlers |
| W5 | `app.js` + API routers: permissions, providers, skills, MCP, channels, telegram-menu, budget/cron/security |
| W6 | `app.js` analytics/budget charts, alerts log viewer, config diff/undo, dark-mode audit |
| Final | integration only |

## Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Vendor xterm.js + Geist/Geist Mono WOFF2** under Mission Control static assets; **do not widen CSP** in `http_server.py`. | S1 — external jsdelivr/Google Fonts are blocked today; self-contained assets work offline/tunneled. |
| D2 | **`linkify(id, kind)`** — every rendered session/span/turn/issue/file ID is a hyperlink to its detail route; detail views link back to parent session/trace/config. | S3 — routes exist but are not surfaced. |
| D3 | **One shared formatter** for timestamps (relative + local on hover) and compact numbers; **no raw nanosecond epochs** in the UI. | S2 — fixes ~10 tabs at once. |
| D4 | **Structured forms first** for every GET+PUT tab; raw JSON textareas only under an "Advanced" toggle. | S4 — Tools & Permissions `{}` textarea is the anti-pattern. |
| D5 | **Health badge "degraded"** counts only *configured* providers; voice STT/TTS stubs excluded from the permanent amber count. | S5 — 9/10 degraded noise today. |
| D6 | **Tests-first:** exactly one `role = test-author` wave (W1) before impl; only **test-creator** edits `tests/`. | Constitution II + repo convention. |

```toml
waveorch_format = 2
title  = "Mission Control control plane"
slug   = "mission-control-control-plane"
base   = "test-pre"
branch = "feature/mission-control-control-plane"

[spec]
review = "plan/mission-control-critical-review-2026-07-04.md"

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

# Per-agent model overrides for this plan (optional — omit to use skw.toml defaults).
[pipeline.models.wave-runner]
model = "auto"

[pipeline.models.test-creator]
model = "auto"

[pipeline.models.reviewer]
model = "auto"
thinking = "high"

[pipeline.models.post-review-wave-generator]
model = "auto"

[[waves]]
id = "W0"
title = "Design + locked decisions (review gate)"
depends_on = []
review_gate = true
effort = "S"
role = "impl"
verify = ["make lint"]

[[waves]]
id = "W1"
title = "Tests for control-plane remediation"
depends_on = ["W0"]
effort = "L"
role = "test-author"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "W2"
title = "Un-break — CSP assets, Chat JWT, secrets hygiene"
depends_on = ["W1"]
effort = "M"
role = "impl"
verify = ["make lint", "make typecheck", "make ci-affected"]

[[waves]]
id = "W3"
title = "Shared UX primitives — formatters, linkify, tokens, layout"
depends_on = ["W2"]
effort = "L"
role = "impl"
verify = ["make lint", "make typecheck", "make ci-affected"]

[[waves]]
id = "W4"
title = "Core views — Sessions, Traces waterfall, Chat inbox, Canvas"
depends_on = ["W3"]
effort = "L"
role = "impl"
verify = ["make lint", "make typecheck", "make ci-affected"]

[[waves]]
id = "W5"
title = "Editability sweep — structured editors for PUT-backed tabs"
depends_on = ["W3"]
effort = "L"
role = "impl"
verify = ["make lint", "make typecheck", "make ci-affected"]

[[waves]]
id = "W6"
title = "Polish — charts, log viewer, cron output, config diff, dark mode"
depends_on = ["W4", "W5"]
effort = "M"
role = "impl"
verify = ["make lint", "make typecheck", "make ci-affected"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W6"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]
```

## Wave W0 — Design + locked decisions (review gate)

- [ ] **W0.1** [US1] Confirm D1: vendored xterm + Geist under Mission Control static; CSP stays `script-src 'self'` / `font-src 'self'`.
- [ ] **W0.2** [US1] Confirm Chat fix: gateway auto-mints `webchat_jwt_secret` at boot (same pattern as onboard token) so `POST /api/v1/chat/token` is not 503 on fresh install.
- [ ] **W0.3** [US2] Confirm D2–D3: one formatter module + `linkify(id, kind)` + detail-drawer component shared across tabs.
- [ ] **W0.4** [US4] Confirm D4 scope: Tools & Permissions, Providers, Skills actions, MCP add, Channels credentials, Telegram menu, Budget limits — structured first, JSON advanced only.
- [ ] **W0.5** [US3] Confirm session detail replaces deprecated `sessions/{id}` 410 route with a real detail API + SPA page (turn list, messages, traces, cost, export).
- [ ] **W0.6** [US3] Confirm Traces redesign: group by turn/session waterfall, suppress heartbeat kinds by default, human durations, click → detail drawer.
- [ ] **W0.7** [US3] Confirm Chat vision: unified multi-channel inbox (read-only foreign channels + composable webchat) and OpenUI/AG-UI stream slot in Chat/Canvas (stretch OK to defer pieces to W6 if needed — record here).
- [ ] **W0.8** **Review gate:** operator sign-off on D1–D6 and wave split before W1 runs.

## Wave W1 — Tests for control-plane remediation (test-author)

- [ ] **W1.1** [US1] [P] `tests/gateway/test_mission_spa_mount.py` — Mission Control HTML references **same-origin** xterm + font assets (no `cdn.jsdelivr.net` / `fonts.googleapis.com`); CSP header unchanged (D1).
- [ ] **W1.2** [US1] [P] `tests/gateway/` — `POST /api/v1/chat/token` succeeds when gateway boot mints `webchat_jwt_secret` (no `webchat_jwt_secret_unconfigured`).
- [ ] **W1.3** [US1] [P] SPA/unit — onboarding wizard URL masks the live `onboard_token` (copy button OK; cleartext display not OK).
- [ ] **W1.4** [US1] [P] Model Params — locale comma (`0,95`) serializes to valid JSON numbers on save (no comma decimal round-trip).
- [ ] **W1.5** [US2] [P] Formatter tests — ns epoch and float unix timestamps render human-relative strings; compact number formatter handles budget tile magnitudes.
- [ ] **W1.6** [US2] [P] `linkify` — session/span/turn IDs produce correct Mission Control detail hrefs; detail drawer route loads stub payload from existing GET endpoints.
- [ ] **W1.7** [US3] [P] Session detail API + SPA — `GET /api/v1/sessions/{id}` (or agreed replacement) returns metadata + turn/message summaries; deprecated 410 route not the primary link target.
- [ ] **W1.8** [US3] [P] Traces — list API filtered to exclude `channel.telegram.poll.cycle` by default; waterfall grouping uses `parent_span_id`.
- [ ] **W1.9** [US3] [P] Chat — inbox lists sessions from at least two channel kinds; webchat compose path returns a token when configured.
- [ ] **W1.10** [US4] [P] Tools & Permissions — structured toggles round-trip via PUT without requiring raw JSON textarea edit.
- [ ] **W1.11** [US4] [P] Skills — ACTIONS column invokes enable/disable (or install) API for a core skill row.
- [ ] **W1.12** [US5] [P] Providers health badge — degraded count ignores unconfigured voice stub providers (D5).

## Wave W2 — Un-break — CSP assets, Chat JWT, secrets hygiene

- [ ] **W2.1** [US1] Vendor `@xterm/xterm` JS+CSS and Geist/Geist Mono WOFF2 into `src/sevn/ui/spa/dashboard/static/`; update `index.html` to load from same origin (D1).
- [ ] **W2.2** [US1] [P] Confirm `_MISSION_CONTROL_CSP` in `src/sevn/gateway/http_server.py` needs no relaxation; extend `tests/gateway/test_mission_spa_mount.py` if asset paths change.
- [ ] **W2.3** [US1] Mint/persist `webchat_jwt_secret` during gateway boot when absent (mirror onboard token pattern); Chat tab `POST /api/v1/chat/token` returns 200 on default local install.
- [ ] **W2.4** [US1] [P] Onboarding tab — mask onboard token by default; add copy-to-clipboard control.
- [ ] **W2.5** [US1] [P] Model Params save path — normalize locale decimal commas to JSON-safe `.` before PUT; display uses operator locale but wire format stays JSON-standard.
- [ ] **W2.6** [US1] Terminal tab — xterm attaches on Connect (remove persistent CSP violation console noise); JWT+CSRF upgrade flow testable after W2.1.

## Wave W3 — Shared UX primitives — formatters, linkify, tokens, layout

- [ ] **W3.1** [US2] Add shared `formatTimestamp` / `formatNumber` helpers in `app.js`; replace raw ns/unix displays on Overview, Traces, Budget, Cron, Providers, Alerts (D3).
- [ ] **W3.2** [US2] Implement `linkify(id, kind)` + reusable detail-drawer component; wire Overview session rows, Traces span rows, Sessions table, Trajectories turn IDs (D2).
- [ ] **W3.3** [US2] [P] Semantic color tokens (ok/warn/error/info + brand accent) in `style.css`; apply to provider rows, alert severity, stat tiles.
- [ ] **W3.4** [US2] [P] Full-width dashboard grid — drop ~940px centered card constraint; section-level max-width instead.
- [ ] **W3.5** [US2] [P] `emptyState(actionLabel, onAction)` component — replace passive empty states on MCP, Jobs, Code Understanding, Canvas.
- [ ] **W3.6** [US5] Top bar — rename global search label to match ⌘K scope; disambiguate ghost "system" theme control vs "System" ops menu; fix floating label/placeholder collision.
- [ ] **W3.7** [US5] Providers summary badge — degraded count uses configured providers only (D5).

## Wave W4 — Core views — Sessions, Traces waterfall, Chat inbox, Canvas

- [ ] **W4.1** [US3] Sessions list — add first-message / last-message columns; session ID links to new detail page; replace 410 recovery route as primary navigation.
- [ ] **W4.2** [US3] Session detail page — metadata, turn list with message previews, trajectories, traces, session budget, export action; link back to related traces/config.
- [ ] **W4.3** [US3] Traces tab — turn/session waterfall grouped by `parent_span_id`; default filter hides poll/heartbeat kinds; human durations; row click opens detail drawer with payload, cost, session/turn links.
- [ ] **W4.4** [US3] [P] Audit & Analytics — demote poll noise; render `daily-volume` / `tool-frequency` as charts (not table-only below fold).
- [ ] **W4.5** [US3] Chat — unified inbox across channels; read-only Telegram (and other) sessions openable; working webchat compose when JWT configured.
- [ ] **W4.6** [US3] [P] Canvas — "render last canvas / pick from history" affordance + link to Chat; OpenUI stream hook point for agent turns (AG-UI stretch — minimal viable: render last OpenUI payload).
- [ ] **W4.7** [US3] [P] Overview — stat tiles click through to target tabs; explain Active vs listed session counts; remove empty "Live activity" placeholder or wire real feed.

## Wave W5 — Editability sweep — structured editors for PUT-backed tabs

- [ ] **W5.1** [US4] Tools & Permissions — tool registry table (enabled, allowlist, dispatch timeout, health) with toggles; JSON `{}` textarea behind Advanced (D4).
- [ ] **W5.2** [US4] [P] Agent Config — editable resolved-slots where API marks `editable`; model picker fed from providers registry.
- [ ] **W5.3** [US4] [P] Model Params — accordion by agent group; diff-vs-default indicators; link to underlying config path; keep W2 locale fix.
- [ ] **W5.4** [US4] [P] Skills — wire ACTIONS (toggle/promote/delete/install); skill detail drawer (SKILL.md preview, quarantine reason, run-script).
- [ ] **W5.5** [US4] [P] MCP Servers — add-server form wired to list/PUT API.
- [ ] **W5.6** [US4] [P] Coding Agents — enable switch on tab (not Config-only trip).
- [ ] **W5.7** [US4] [P] Providers & LLMs — RE-AUTH column runs `sevn providers oauth login …` via CLI tab or copy+deep-link; provider CRUD/credentials (align with providers-registry plan); hide/configure voice stubs.
- [ ] **W5.8** [US4] [P] Channels — split configured vs available-to-enable; inline enable/disable + credentials.
- [ ] **W5.9** [US4] [P] Telegram Menu — expand sections with actions; PUT editing; deep-link into matching MC tabs.
- [ ] **W5.10** [US4] [P] Budget & Cost — editable budget limits; per-model/per-session breakdown where API supports it.
- [ ] **W5.11** [US4] [P] Security — policy editor beyond empty `{}` toggles; Secrets list with masked values + hold-to-reveal.
- [ ] **W5.12** [US4] [P] Evolution Issues — link rows to `GET issues/{id}` detail; pipeline stage stepper highlights current stage only.

## Wave W6 — Polish — charts, log viewer, cron output, config diff, dark mode

- [ ] **W6.1** [US5] Alerts & Logs — dedupe/group repeated alerts; ACK action wired; embed log tail/filter viewer using log_query tool API.
- [ ] **W6.2** [US5] [P] Cron — human next-fire time (uses W3 formatter); last-run output/duration; delete confirm dialog; expression helper (optional stretch).
- [ ] **W6.3** [US5] [P] Config — in-tree search; schema-driven enum/description on hover (schema API); diff preview before save; link to Backup tab for undo/draft.
- [ ] **W6.4** [US5] [P] Workspace Files — two-pane tree + editor; directories clickable; syntax highlighting in editor.
- [ ] **W6.5** [US5] [P] Code Understanding — graph query box wired to knowledge/graph API; optional `graphify update` action when graphify present.
- [ ] **W6.6** [US5] [P] Self-improve Jobs — "start cycle" button wired to `self_improve_cycle` ops capability.
- [ ] **W6.7** [US5] [P] Trajectories / Feedback — link turn IDs to turn/session detail; fix `channel: unknown` ingest display if data available.
- [ ] **W6.8** [US5] [P] Proxy / Backup / sevn CLI — proxy log viewer; backup restore scary-confirm; CLI output history.
- [ ] **W6.9** [US5] Dark mode audit — re-screenshot key tabs after D1 font fix; fix contrast/token gaps.

## Wave Final — Integration gate

- [ ] **Final.1** Run `make ci-resume` to green on the feature branch.
- [ ] **Final.2** Manual smoke: open Mission Control — Terminal connects, Chat token succeeds, Geist renders, session ID opens detail, Traces waterfall navigable, at least one PUT-backed tab saves via structured form (operator).
