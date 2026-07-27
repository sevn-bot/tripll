# wave-orchestrator — operator runbook

Day-to-day operation of a wave-orchestrator run: Pre-0 approval, escalation
handling, resume after a crash, and switching backends.

## 1. Start a run

From **`wave-orchestrator/`** (use Make — `tripll` is not installed globally):

```bash
cd wave-orchestrator
make init
cp -r ../plan/<wave-set> runs/input/
make tripll ARGS='plan runs/input/<set> --dry-run'   # sanity-check
make tripll ARGS='run runs/input/<set> --backend claude_code'
```

Backend auth and model selection: see [`../.env.example`](../.env.example) (tripll
has no secrets file of its own).

The run claims the input directory into `runs/processing/<run-id>/` and **stops
at the Pre-0 human gate** before dispatching any implementation wave.

## 2. Pre-0 approval (HITL)

Pre-0 pauses the run for **operator decisions only** — the W0 batch has
`human_gate: yes` and is **not** agent-dispatched. After approve, the first
dispatched wave is typically **R1** (or W1 in tests-first plans), not W0
scaffolding execution.

On pause, tripll writes:

- `hitl-form.json` — machine-readable questionnaire
- `pre0-decisions.md` — checklist (regenerated when you submit responses)

### Option A — Dashboard (recommended)

1. `make serve` (control plane on `http://localhost:8765`).
2. Start the run (`make run-set SET=…` or **Launch** from the home page).
3. Open the run detail page → **Open HITL** (or **Resolve gate** on the W0 row).
4. Complete the modal wizard → **Save draft** as needed → **Submit & approve**.
5. Click **Resume** (or use `WAIT_FOR_HITL=1 make run-set` so the CLI auto-resumes).

See [`../hitl-form-template.md`](../hitl-form-template.md) for the JSON schema.

### Option B — CLI wait mode

```bash
make serve   # terminal 1
WAIT_FOR_HITL=1 make run-set SET=<set>   # terminal 2 — blocks until HITL complete
```

The CLI prints the dashboard URL, polls `hitl-responses.json` every
`TRIPLL_HITL_POLL_S` seconds (default 2), then runs `approve` + `resume`.
Ctrl-C leaves the run paused safely.

### Option C — Terminal interview

```bash
make pre0-interview RUN=<run-id>
make continue-run RUN=<run-id>   # approve + resume
# or: make finish-pre0 RUN=<run-id>
```

`approve` requires complete HITL responses when `hitl-form.json` exists; it
writes `pre0-approved`. Nothing is dispatched until that marker exists.

After approve, **resume** auto-completes human-gate waves (e.g. W0 in the Pre-0
batch) without agent dispatch; the first implementation wave (e.g. R1) runs next.

### Reset a run back to input/

To abandon a run and restore its plan files under `runs/input/` (for a fresh
`make run-set`):

```bash
make reset-run RUN=<run-id>
# restores runs/input/<slug>/ and deletes processing|failed|processed copy
```

### Legacy manual edit

You may still edit `pre0-decisions.md` directly, but you must also submit
answers via the dashboard or `make pre0-interview` so `hitl-responses.json`
is complete before approve.

### Human-gate modes (`human_gates`)

v3 plans may set ``[pipeline] human_gates`` to one of:

| Mode | Behaviour |
|------|-----------|
| ``prompt`` | Default — pause at Pre-0 for operator approval (dashboard / CLI). |
| ``auto_accept`` | Skip the Pre-0 prompt when tier-4 canaries pass; a **red** canary resolves to **PARKED**, not proceed. |
| ``fail`` | Reject the run at Pre-0 without prompting. |

Environment override: ``TRIPLL_HUMAN_GATES=auto_accept`` (same three values). The override
wins over the plan file. Tier-4 canaries (for example ``gh run list --workflow=CI --limit 1``)
still run under ``auto_accept`` — they gate whether auto-accept may proceed.

## 3. Monitor progress

```bash
make tripll ARGS='status <run-id>'
```

Wave states advance `queued → dispatched → running → verifying → done`. Blocked
waves are listed under **Escalated (blocked) waves** with their latest-attempt
evidence. Per-attempt logs live in `runs/processing/<run-id>/logs/`.

## 3a. Tracing

Tracing is **on by default** for pipeline runs. Local sinks require **no**
`LOGFIRE_TOKEN` — they always write beside the run:

```text
runs/processing/<run-id>/traces/traces.db       # queryable SQLite (join on attempt_id)
runs/processing/<run-id>/traces/<YYYY-MM-DD>.jsonl
```

Enable/disable via env or plan:

```bash
TRIPLL_TRACE=1 make tripll ARGS='run …'    # force on (default when unset)
TRIPLL_TRACE=0 make tripll ARGS='run …'    # force off
```

Plan block (v3 TOML):

```toml
[tracing]
enabled = true
service_name = "tripll"
sinks = ["sqlite", "jsonl"]
retention_days = 30
capture = "shape"              # off | shape | full — default shape (no prompt text)

[[tracing.exporters]]
type = "logfire"               # cloud — LOGFIRE_TOKEN

[[tracing.exporters]]
type = "logfire"
base_url = "http://localhost:8080"   # self-hosted Logfire server

[[tracing.exporters]]
type = "otlp"
endpoint = "http://127.0.0.1:4318/v1/traces"
```

**Reading spans:** query `traces.db` for `tripll.run` → `tripll.wave` →
`tripll.agent.dispatch`. Each dispatch span carries `backend`, `model`, token
counts, and `cost_usd`. Compare dispatch span count to ledger attempts:

```bash
sqlite3 runs/processing/<run-id>/traces/traces.db \
  "select kind, count(*) from trace_events where status='closed' group by kind"
sqlite3 runs/processing/<run-id>/ledger.db \
  "select count(*) from attempts"
```

**Capture policy:** `shape` (default) records role/block-type/char-count only —
never prompt or completion text. Use `full` only for deliberate debugging.

Cloud export requires the `obs` extra (`uv sync --extra obs`) and optional
exporters/token above. See `docs/decisions/012-tracing-spine.md`.

## 4. Escalation handling

Each wave gets up to **5 attempts** (4 retries; tests-first model, D1). The corrected brief
appends prior-attempt failure evidence on each retry. On the 5th failure the wave is marked
`blocked`, the run moves to `runs/failed/<run-id>/`, and:

- `escalation.md` lists the blocked waves and evidence.
- `report.md` summarises phases, wave states, escalations, and deferred/manual
  prerequisites.

To act on an escalation: inspect the wave's logs + brief, fix the underlying
cause, then re-run the set (or resume — completed waves are skipped).

## 5. Resume after a crash

```bash
make tripll ARGS='resume <run-id>'
```

Resume rebuilds the graph from the run directory and seeds completed waves from
the ledger, so it dispatches only the waves that had not finished. It re-stops at
the Pre-0 gate if it was never approved.

## 6. Switching backends

Pass `--backend` to `run`/`resume`:

- `claude_code` (default) — requires the `claude` CLI on PATH.
- `cursor_local` — requires `cursor-agent` on PATH (capability-gated).
- `cursor_cloud` — requires the `tripll[cloud]` extra; cloud live dispatch is
  deferred (manual smoke).

### Per-wave provider routing (v3 plans)

v3 plans declare routing in TOML:

```toml
[pipeline]
max_parallel = 10
default_provider = "cursor_local"

[providers.cursor_local]
max_parallel = 5              # extension-host ceiling (CAP-01)
cooldown_s = 30
default_model = "auto"

[providers.claude_code]
max_parallel = 3
default_model = "claude-sonnet-5"

[[waves]]
id = "W1"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
reasoning_effort = "high"     # Claude Code only — see below
max_budget_usd = 12.0         # Claude Code process-level backstop
```

| Provider | Concurrency | Reasoning effort |
|----------|-------------|------------------|
| `cursor_local` | Capped at `[providers.cursor_local] max_parallel` (default **5**). Adaptive throttle halves the pool after repeated **infra** failures. | Part of the **model string** (`claude-opus-5-thinking-high`, `claude-opus-5[effort=high]`, or `auto`). |
| `claude_code` | `[providers.claude_code] max_parallel` (default **3**). | `reasoning_effort` wave key → `claude --effort <level>`. |
| `cursor_cloud` | `[providers.cursor_cloud] max_parallel` (default **8**). | Same as Cursor local — model string only. |

**Infra events** (`Couldn't start`, `Workspace Disconnected`, auth/session hangs) are classified
separately from wave failures. They do **not** consume an attempt slot and do **not** trip the
exit-7 breaker. The dashboard/ledger shows them under phase `infra`.

**Failover** uses the wave's `fallback` list when the primary provider is in cooldown. Failover
changes the **provider only** — the wave's model intent is preserved (ADR 010). tripll never
passes `claude --fallback-model`.

**Auth preflight** runs at run start for every provider the plan routes to. If `claude` or
`cursor-agent` is missing or unauthenticated, the run fails fast with a named provider instead
of hanging mid-wave (especially under `human_gates = "auto_accept"`).

**CAP-01 calibration:** `max_parallel = 5` for `cursor_local` is the operator starting point.
Run the tier-2 concurrency probe (`RUN_LIVE=1 make test -- -k test_cursor_pool_ceiling`) on your
machine and record the level where infra first appears. As of 2026-07-26 on the reference
developer machine, tier-1 fake-clock tests enforce the contract at 2/3/5/8 probe levels; live
calibration is operator-specific.

## 7. Integration (optional)

Dispatch-only is the default (branches + `report.md`, no merges). To integrate:

```bash
make tripll ARGS='run <set> --integrate --dry-run'   # preview merges/gates/commits
make tripll ARGS='run <set> --integrate'             # merge → docs → make ci → 1 commit
```

Pre-0 / review-gate batches never auto-commit; a failing gate aborts the batch
before committing.

## 8. PR loop and merge gate (code factory L1)

After implementation waves, the **PR phase** pushes the branch, opens a pull request,
ingests CI failures and review comments as `Finding` nodes, and dispatches fix agents until
required checks pass. The loop **stops at the human merge gate** — tripll never auto-merges.

```bash
tripll pr shepherd <run-id>              # idempotent push/open/fix loop
tripll findings sync --pr <n>            # check-runs + review threads → graph
tripll findings list [--state open]      # inspect findings
tripll pr status <run-id>                # checks + pullfrog-approval
tripll pr approve-merge <run-id>         # operator merge gate
```

Dashboard run detail shows **Code factory L1** panels: wave subgraph, findings grouped by
state, and exit caps approaching limits (§12).

Rejected findings export to `.pullfrog/learnings.md` (D13). Optional CI review:
`.github/workflows/pullfrog.yml` (requires `CLAUDE_CODE_OAUTH_TOKEN` secret).
Local advisory review: `make review`.

See [`../harness-checks.md`](../harness-checks.md) and [`../graph-serving.md`](../graph-serving.md).

## 9. Orchestrator mode (headless Multitask parity)

Orchestrator mode is **opt-in** when an input set contains `*-orchestrator-prompt.md`
and the wave plan declares serial orchestration (design-note §8, D1). The engine
formatter owns status tables and wave dispatch; an optional LLM **`wave-orchestrator`**
agent runs only at review gates when enabled.

### Cursor Multitask vs tripll orchestrator mode

| Dimension | Cursor Multitask | tripll orchestrator mode |
|-----------|------------------|----------------------------|
| Session | Cursor chat + subagents | Detached engine (`make run-set`, dashboard) |
| Coordinator | You + `wave-orchestrator` agent in chat | Engine formatter + optional gate agent |
| Status table | Chat turns | `orchestrator-status.md` + terminal + dashboard §11 |
| Wave implementer | `wave-runner` subagent | `wave-runner` via adapter (`--agent wave-runner`) |
| Branch policy | Single feature branch in prompt | Same — `OrchestratorConfig.single_branch` (D8) |
| Verify / commit | Per-wave in orchestrator prompt | Engine brief overrides + commit-per-wave (D7) |
| Review gates | STOP in chat | Run `paused` + `review-gate-pending.md` + `review_gate` turn |
| Model policy | Omit `model` on wave-runner (D11) | Same — use `MODEL=auto` for `cursor_local` only |
| Parallel lanes | N/A (serial orchestrator) | Default lane mode unchanged when prompt absent |

Use **Multitask** when you want interactive steering every turn. Use **tripll
orchestrator mode** for overnight/detached runs with the same table-shaped updates in
terminal and dashboard.

**Implementing teams:** [`plan/tripll-orchestrator-mode-orchestrator-prompt.md`](../../../plan/tripll-orchestrator-mode-orchestrator-prompt.md)

### Start an orchestrator-mode run

```bash
cd wave-orchestrator
make seed-orchestrator-smoke-set   # or copy docs/examples/orchestrator-mode-input-set/
make validate-set SET=orchestrator-mode-smoke
make run-set SET=orchestrator-mode-smoke PROVIDER=cursor_local MODEL=auto
```

Input layout and naming: README **Orchestrator mode**; example set README in
`docs/examples/orchestrator-mode-input-set/`.

### Monitor orchestrator status

```bash
make status-watch RUN=<run-id>
```

Prints an **Orchestrator** block (status table + last three turns) above the
per-node agent table (D12). For the status file only:

```bash
make orchestrator-watch RUN=<run-id>
```

Dashboard: `make serve` → run detail → **Orchestrator** panel + feed (control-plane §11).

Automated W0 smoke: `make smoke-orchestrator-w0`.

### Review gate approval flow

1. Engine completes a wave with `review_gate: yes` (e.g. W0 → **W0.8**).
2. Run state → **paused**; `orchestrator-status.md` records a `review_gate` turn with
   **AWAITING REVIEW**; `review-gate-pending.md` is written (same pattern as quota pause).
3. Operator reads the wave summary in terminal, dashboard panel, or
   `orchestrator-status.md`.
4. Resolve any Pre-0 items in `pre0-decisions.md` if the batch is Pre-0.
5. Approve and resume:

   ```bash
   make approve-run RUN=<run-id>
   make resume-run RUN=<run-id> PROVIDER=cursor_local MODEL=auto
   # or: make finish-pre0 RUN=<run-id> when Pre-0 interview is needed
   ```

6. **Optional headless gate agent (W4):** when `TRIPLL_ORCHESTRATOR_AGENT=1`, the
   engine dispatches **`wave-orchestrator`** with a condensed gate brief after the
   review-gate wave. Parse result heuristics (`approve`, `STOP`, `dispatch W1`) inform
   whether to proceed — operator approval via `approve-run` remains authoritative.

After resume, the next serial wave dispatches on the single integration branch recorded
in the orchestrator prompt.

## 10. Agent-Native Plans sidecar (hybrid)

Optional **Docker sidecar** for pre-dispatch plan review and post-change recap via
`/visual-plan` and `/visual-recap` skills. **tripll remains the live-ops control
plane** (SSE, ledger, logs, approve/resume). Plans and the dashboard are complementary —
see [`plan/tripll-agent-native-visual-plans-evaluation.md`](../../../plan/tripll-agent-native-visual-plans-evaluation.md)
for the hybrid rationale and [`plan/tripll-agent-native-docker-local-wave-plan.md`](../../../plan/tripll-agent-native-docker-local-wave-plan.md)
for Docker setup (Phases P0–P3).

**Related runbooks:**

- Phase 0 host spike — [`agent-native-plans-spike.md`](agent-native-plans-spike.md)
- Phase 3 MCP localhost — [`agent-native-plans-localhost-mcp.md`](agent-native-plans-localhost-mcp.md)

### Start order

Run from **`wave-orchestrator/`**:

1. **Optional — Plans sidecar** (when using local Docker MCP instead of hosted SaaS):

   ```bash
   cp .env.agent-native.example .env.agent-native   # once — fill REPLACE_* secrets (D7)
   make plans-up                                    # :3000, volume-backed SQLite (D2)
   ```

   One-time MCP repoint: follow [`agent-native-plans-localhost-mcp.md`](agent-native-plans-localhost-mcp.md) §2
   (`connect http://localhost:3000 --client all` or manual bearer entry at
   `http://localhost:3000/_agent-native/mcp`).

2. **tripll dashboard** (required for live runs):

   ```bash
   make serve    # http://127.0.0.1:8765
   ```

3. **Dispatch / resume** (in another terminal):

   ```bash
   make run-set SET=<set> PROVIDER=cursor_local MODEL=auto
   # or after Pre-0 / review gate:
   make resume-run RUN=<run-id> PROVIDER=cursor_local MODEL=auto
   ```

**Before step 3:** when reviewing a wave-plan visually, run `/visual-plan` in your
coding agent (operator session, not wave subprocess) while the sidecar is up. Record
plan id or URL in `pre0-decisions.md` or run notes for later lookup.

Stop the sidecar when done: `make plans-down`. tripll does not depend on Plans
running during implementation waves.

### `PLANS_BASE_URL` convention

Set in the operator shell (or `.env` loaded before `make serve`) when using the local
Docker sidecar:

```bash
export PLANS_BASE_URL=http://localhost:3000
```

Use this base when opening or storing visual plan links:

```text
{PLANS_BASE_URL}/plans/{plan-id}
```

Example after `/visual-plan` returns a plan id `plan-51d3511d0d954ab2`:

```text
http://localhost:3000/plans/plan-51d3511d0d954ab2
```

**Dashboard link (deferred):** an **Open visual plan** header link
(`{PLANS_BASE_URL}/plans/{id}`) is planned as a follow-up in
[`plan/tripll-dashboard-ui-wave-plan.md`](../../../plan/tripll-dashboard-ui-wave-plan.md)
**W1.2** extension — not shipped in Phase 4. Until then, open Plans URLs manually or
from `pre0-decisions.md`.

### Plans vs dashboard — when to use which

| Situation | Use | Do not use |
|-----------|-----|------------|
| Review `*-wave-plan.md` before `make run-set` | **`/visual-plan`** (hosted, Docker sidecar, or local-files) | Dashboard (no run yet) |
| Pre-0 decision table + architecture choices | **`/visual-plan`** + `make pre0-interview` | Dashboard alone |
| W0.7 dashboard IA / wireframe sign-off | **Dashboard W0.7** + control-plane-design §10 | visual-plan (wrong artefact) |
| Live waves, tokens, cost during a run | **Dashboard** (`make serve`) | Agent-Native Plans |
| Stalled wave, rejected shell, attempt 2+ | **Dashboard** logs + worktree + `status --watch` | visual-recap (wrong phase) |
| Approve Pre-0 or review gate to resume | **`make approve-run`** / **`make resume-run`** | visual-plan (does not approve ledger) |
| Batch progress mid-run | **Dashboard** timeline + `report.md` | visual-plan |
| After batch / Final — semantic code review | **`/visual-recap`** on branch/worktree | `report.md` alone |
| Sensitive plan (must not leave laptop) | **local-files** or **Docker sidecar** | Hosted default |
| Plan review with comments, no SaaS | **`make plans-up`** + localhost MCP | local-files (no comments until publish) |

**Typical hybrid loop:**

1. **Before run:** `/visual-plan` on wave-plan → decisions in `pre0-decisions.md` →
   `make run-set` → Pre-0 gate → `make approve-run` / `make resume-run`.
2. **During run:** dashboard only.
3. **After batch:** `/visual-recap` on integration branch; dashboard `report.md` for run state.

### Local-files mode (no Docker)

`AGENT_NATIVE_PLANS_MODE=local-files` writes MDX under a repo path (e.g.
`runs/input/<set>/plans/<slug>/`) with **no DB writes**. Use when strictest privacy is
required and comments/sharing are not needed. Docker sidecar replaces **hosted** SaaS;
local-files replaces **both** hosted and sidecar when you want zero plan DB at all.

---

## Control plane auth (`TRIPLL_API_TOKEN`)

When `TRIPLL_API_TOKEN` is set, **HTML pages and JSON API routes share one boundary**
(R4). Every dashboard page shell and mutating form POST requires a valid Bearer token
(or matching `?token=` query param for browser loads). Form POSTs also require the
double-submit CSRF field paired with the `tripll_csrf` cookie (R5).

When the token is **unset**, the control plane stays in open dev mode (localhost-only
by default) — behaviour unchanged from pre-W3.

**Bind-address risk:** `make serve` defaults to localhost. If you bind to a non-local
interface (`tripll serve --host 0.0.0.0`) **without** setting `TRIPLL_API_TOKEN`, anyone
on the network can launch runs and change settings through the HTML UI. That combination
is the one genuinely dangerous operator mistake — always set a token before exposing the
dashboard beyond localhost.

---

## Git safety (git clean guard)

tripll ships a repo-local `bin/git` wrapper that blocks `git clean -x` and `git clean -X`.
Those flags delete gitignored operator trees (`.ignorelocal/`, wave plans, design docs).

**Before any git operations in this checkout**, prepend the repo `bin/` directory to PATH:

```bash
export PATH="$PWD/bin:$PATH"
```

Then use plain `git` — the wrapper delegates to your real git binary and intercepts
`git clean` to reject `-x`/`-X`. Safe cleanup remains available:

```bash
git clean -fd              # tracked + untracked dirs, no gitignored files
git clean -fd -- path/to/  # scoped cleanup
```

Do **not** call `/opt/homebrew/bin/git clean -fdx` or similar — that bypasses the guard.

---

## Deferred / manual items

- **Cloud live dispatch + poll loop** — `cursor_cloud` dispatch and the
  background poll scheduler are deferred; the dispatch-only default needs no poll
  loop.
