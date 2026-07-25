# Control-plane design (W0 lock)

Design decisions for the FastAPI control plane + live dashboard layered over the
existing `tripll` engine. Locked with the operator. Companion to the execution
plan at `plan/wave-orchestrator-cp-integration-and-fixes-plan.md`.

## Principles

- **Engine is the single execution authority.** The FastAPI service only
  observes and controls; it never becomes the thing that runs agents. A run must
  make progress whether or not the server is up.
- **No new runtime dependencies beyond Python.** No Rust, Postgres, Docker, or
  external control plane. Everything ships in-tree, installed via `uv`.
- **One event pipeline.** The ledger `events` table (W3) is the single source of
  truth for live status; the terminal heartbeat, `status --watch`, the HTTP SSE
  feed, and the web dashboard all read from it.

## 1. Process model — decoupled (locked)

The FastAPI app launches/controls runs as **detached subprocesses**, not
in-process asyncio tasks:

- **Launch:** `POST /api/runs` spawns `tripll run <input> [--backend ...]` via
  `subprocess.Popen(..., start_new_session=True)` so the engine process is in its
  own session and **survives FastAPI restart/stop**. The child PID is written to
  `runs/processing/<run-id>/engine.pid`.
- **Approve / resume / pause:** map to `tripll approve|resume <run-id>` (also
  detached) and a pause marker file the engine checks at safe points (reuse the
  existing pause/marker pattern — `cost-budget-paused.md`, quota pause). Pause
  does not kill in-flight waves; it stops dispatch of new ones.
- **Read state:** all GET endpoints open the ledger read-only (`open_ledger`) and
  read the runs dir / `report.md`. No engine coupling.
- **Liveness:** a run is "live" if `engine.pid` exists and the process is alive;
  otherwise the API reports the last persisted ledger state. The server can be
  restarted at any time with zero effect on running engines.

Rationale: ties run lifetime to the OS, not to the web server; keeps the engine
unchanged in spirit; trivially satisfies "engine keeps working if FastAPI is
stopped."

## 2. UI stack — Jinja + htmx + SSE (locked)

- Server-rendered Jinja templates under `src/tripll/api/ui/`, progressively
  enhanced with htmx; live regions subscribe to the SSE event feed.
- **Zero Node/JS build toolchain.** Static assets (htmx, minimal CSS) vendored or
  CDN-pinned. Keeps parity with sevn's Python-only / `uv` posture.

## 3. Executor contract — fresh sonnet sub-agent per wave (locked)

- Each wave dispatch spawns a **new** `claude -p --agent wave-plan-executor`
  process (the existing model) on **`claude-3-5-sonnet`** by default; opus only
  when the wave's execution-graph row declares a model override.
- The **persistent thing is the profile/definition** (backend + model + local
  agent name `wave-plan-executor` + skills/tools + default scope), not the
  process. Profiles are created once and referenced by many runs/waves.

## 4. Agent-profile schema

Stored in a new `profiles` ledger table (or `runs/profiles.json` — pick the table
for queryability). Fields:

| field        | type     | notes                                                        |
|--------------|----------|--------------------------------------------------------------|
| `profile_id` | TEXT PK  | stable slug, e.g. `claude-wave-executor`                     |
| `name`       | TEXT     | display name                                                 |
| `backend`    | TEXT     | `claude_code` \| `cursor_local` \| `cursor_cloud`            |
| `model`      | TEXT     | default `claude-3-5-sonnet`                                  |
| `agent`      | TEXT     | local agent definition, default `wave-plan-executor`         |
| `skills`     | JSON     | optional skill/tool allowlist                                |
| `scope`      | JSON     | default workspace-scope hints (toolchain paths, etc.)        |
| `created_at` / `updated_at` | TEXT |                                                   |

A run records which `profile_id` it used; waves inherit it. Seed one default
profile per available backend on first `serve`/`cp-setup` so nothing is created
per run.

## 5. Events table (defined here, implemented in W3)

```
CREATE TABLE IF NOT EXISTS events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    ts           TEXT NOT NULL,
    phase        TEXT NOT NULL,   -- dispatched|running|verifying|done|failed|paused
    last_action  TEXT,            -- one-line summary (summarize_stream_line)
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd     REAL
);
CREATE INDEX IF NOT EXISTS idx_events_run_ts ON events (run_id, ts);
```

The engine appends an event whenever a node changes phase or the stream yields a
new operator-relevant action / usage delta. SSE replays from a client-supplied
`Last-Event-ID` (= `event_id`) then tails new rows.

## 6. HTTP API surface (parity with the CP interface)

- **Agents/profiles:** `GET/POST /api/agents`, `GET/PATCH/DELETE /api/agents/{id}`.
- **Runs:** `POST /api/runs` (input set + profile), `GET /api/runs`,
  `GET /api/runs/{id}`, `POST /api/runs/{id}/approve|resume|pause`.
- **Waves:** `GET /api/runs/{id}/waves`, `GET /api/waves/{run_id}/{node_id}`.
- **Events:** `GET /api/runs/{id}/events` (poll, `?after=<event_id>`) +
  `GET /api/runs/{id}/events/stream` (SSE).
- **Config/backends:** `GET/PUT /api/config` (model defaults, budgets,
  `TRIPLL_MAX_PARALLEL`), `GET /api/backends` (claude/cursor availability + auth).
- **Health:** `GET /health`.

Auth: a single bearer token from env (`TRIPLL_API_TOKEN`); localhost-only bind
by default.

## 7. Ledger concurrency (for W1 parallelism)

- The ledger already opens with `PRAGMA journal_mode = WAL`.
- The engine runs in **one asyncio event loop**; sqlite calls are synchronous, so
  individual statements are already serialized by the single thread.
- The only hazard is multi-statement logical transactions interleaving across
  `await` points under `asyncio.gather`. **Lock with a single `asyncio.Lock`**
  held around each ledger-mutating sequence in the engine (`insert_attempt`,
  `transition_wave` chains, `end_attempt`, event appends). Reads need no lock
  under WAL.
- Worktrees are already per-lane-wave, so concurrent nodes never share a working
  tree.

## 8. Review gate

W4 (API) and W5 (UI) must not start until this document is reviewed. W1–W3
(engine parallelism, cost/retry, events) may proceed now — they only depend on
§5 (events schema) and §7 (ledger concurrency), both locked above.

---

## 9. Operating the control plane

This section is the operator runbook for the FastAPI control plane and the
LAP-style browser dashboard (W1–W4). For the full engine lifecycle (Pre-0
gate, wave retry, integration) see
[`docs/runbooks/operator-runbook.md`](runbooks/operator-runbook.md).

### Install the API extra

```bash
cd wave-orchestrator
uv sync --extra dev --extra api   # or: make sync-api
```

### Start the server

```bash
make serve                        # binds localhost:8765 (default)
# or
tripll serve --host 0.0.0.0 --port 9000   # custom host/port
```

Open `http://localhost:8765/` in a browser for the live dashboard.
API documentation (Swagger UI) is at `http://localhost:8765/docs`.

**Auth:** set `TRIPLL_API_TOKEN=<secret>` to require a Bearer token on all
API requests. When the variable is unset, the server is open to localhost
access (dev mode — do not expose on a network interface without setting a
token). The dashboard injects the token into htmx `Authorization` headers and
appends `?token=<secret>` to SSE and fragment URLs because browsers cannot set
custom headers on `EventSource` (see §10, D12).

---

### Browser workflows (dashboard v1)

The top nav (**Agents | Runs | Settings | API docs**) is available on every
page. Use **Runs** (`/`) as home; click a run id to open run detail.

#### Create or edit agent profiles

1. Open **Agents** (`/agents`) — lists every persisted profile.
2. Click **New profile** (`/agents/new`) or **Edit** on an existing row.
3. Fill in name, backend (`claude_code`, `cursor_local`, `cursor_cloud`),
   model, local agent name (default `wave-plan-executor`), and optional skills
   JSON.
4. Submit — the form POSTs to `POST /api/agents` or `PATCH /api/agents/{id}`.
   One default profile per available backend is seeded on first `serve`.

Profiles are persistent — create once, reuse across many runs.

#### Launch a run from the home page

1. Drop an input set under `runs/input/<set>/` (`make init` creates the layout).
2. On **Runs** (`/`), use the **Launch run** form:
   - **Input set** — pick from the dropdown (folders under `runs/input/`) or
     paste an absolute path in the custom field.
   - **Agent profile** — select the profile that defines backend + model.
3. Click **Launch** — the server POSTs to `/api/runs`, spawns a detached
   engine subprocess, and redirects to `/runs/<run-id>`.

The engine survives FastAPI restarts; the run id appears in the runs table
immediately.

#### Watch a run (run detail page)

Open `/runs/<run-id>`. The page is **hydrated on first paint** — wave rows show
phase, last action, token counts, and cost from `latest_events_by_node` before
SSE connects.

**Run header** — state badge, cumulative run cost, live/offline indicator,
log-file count, link to `report.md`. When pause or escalation marker files exist
(`quota-paused.md`, `cost-budget-paused.md`, `pause-requested.md`,
`escalation.md`), coloured banners show the first-line reason with an expander
for the full file.

**Batch timeline** — horizontal swimlanes from `graph.json` batch layers (or
`report.md` phase headings when batch metadata is absent). Wave nodes are
coloured by ledger phase.

**Wave table** — one row per wave node. SSE (`GET /api/runs/{id}/events/stream`)
updates phase, action, tokens, cost, and optional `attempt_n` / `task_id` fields
without a full page reload. Status line reads "Live — receiving events…" while
connected.

**Event timeline sidebar** — scrollable append-only feed; initial HTML replays
the last 500 ledger events; SSE appends new rows (timestamp, node, phase,
action, cost).

**Run report** — when `report.md` exists, expand the collapsible panel to lazy-
load a rendered markdown fragment.

#### Approve, resume, or pause from the browser

On run detail, use the action buttons above the wave table:

| Button | Effect |
|--------|--------|
| **Approve** | Writes Pre-0 approval (`POST /api/runs/{id}/approve`) after you resolve `pre0-decisions.md` |
| **Approve gate** | When HITL is pending, opens the modal or requires complete `hitl-responses.json` before approve |
| **Resume** | Continues a paused run (`POST /api/runs/{id}/resume`) |
| **Pause** | Requests graceful pause — in-flight waves finish; no new waves dispatched (`POST /api/runs/{id}/pause`) |

A short flash message confirms the request. CLI equivalents:
`tripll approve|resume|pause <run-id>`.

#### Human-in-the-loop (HITL) forms

When a run pauses at Pre-0 or a review gate, the engine writes `hitl-form.json`.
The dashboard shows a **Human input required** banner and an **Open HITL** button.

**Modal wizard** — one question per step; footer actions:

| Button | API |
|--------|-----|
| Save draft | `PUT /api/runs/{id}/hitl/responses` |
| Submit & approve | `POST …/hitl/submit` then `POST …/hitl/approve` then `POST …/resume` |
| Exit | Closes modal; draft preserved |

**JSON API**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/runs/{id}/hitl` | Form, responses, `complete`, `pending` |
| `PUT` | `/api/runs/{id}/hitl/responses` | Save draft or submitted answers |
| `POST` | `/api/runs/{id}/hitl/submit` | Validate all answers; rewrite `pre0-decisions.md` |
| `POST` | `/api/runs/{id}/hitl/approve` | Validate + write gate marker |

`POST /api/runs/{id}/approve` returns **409** when `hitl-form.json` exists but
responses are incomplete. Schema details: [`hitl-form-template.md`](hitl-form-template.md).

**CLI wait mode:** `tripll run … --wait-for-hitl` or `WAIT_FOR_HITL=1 make run-set`
polls until responses are complete, then auto-approves and resumes.

#### Read wave logs

1. Expand a wave row (click the node id `<details>` summary).
2. Scroll to the **Log** panel — htmx loads the tail on expand.
3. The viewer serves read-only log tails from
   `runs/<folder>/<run-id>/logs/<node>-attempt<N>.log` (200 KiB max, path
   containment enforced — see §10, D4).
4. Default attempt = latest from the `attempts` table; prior attempts are linked
   from the **Attempts** panel above the log.
5. **Gate-only waves** (Pre-0 W0, review-gate rows with zero attempts) show
   *No agent log yet — wave not dispatched.* — not a missing-file error with a
   full filesystem path.

#### Track git worktree changes

Inside the expanded wave row, the **Worktree** panel shows:

- branch name, changed-file count, porcelain paths
- `git diff --stat` lines vs branch HEAD

While phase is `running` or `verifying`, htmx polls every **5 s** and stops
when the wave reaches a terminal phase. No git writes originate from the API.

#### Interpret wave task progress

The **Wave tasks** panel parses checklist bullets (`- [ ] **Wn.m** …`) from
the staged wave-plan slice on the wave worktree. The **active** bullet is
highlighted:

- **Primary rule:** longest case-insensitive substring match between
  `last_action` (from SSE) and bullet text.
- **Fallback:** when phase is `running` and no match, the first unchecked
  bullet is marked active.

When SSE delivers a new `last_action` during `running`/`verifying`, the task
checklist reloads automatically. Use this to see which plan bullet the agent
is working on without opening the worktree file.

#### Attempt history

The **Attempts** panel lists every attempt for the wave (outcome, evidence,
cost, log link). When phase transitions from `failed`/`blocked` to
`dispatched`, a **starting attempt N** badge appears on the row summary.

#### Settings

Open **Settings** (`/settings`) to view and update runtime config bound to
`GET/PUT /api/config`: `max_parallel`, cost budget, and related knobs. Changes
affect newly spawned subprocesses only.

---

### API equivalents (curl)

Use these when scripting or when the dashboard is unavailable.

#### List / create profiles

```bash
curl http://localhost:8765/api/agents
curl -X POST http://localhost:8765/api/agents \
  -H "Content-Type: application/json" \
  -d '{"name": "My Claude executor", "backend": "claude_code", "model": "claude-3-5-sonnet", "agent": "wave-plan-executor"}'
```

#### Launch a run

```bash
curl -X POST http://localhost:8765/api/runs \
  -H "Content-Type: application/json" \
  -d '{"input_path": "/abs/path/to/runs/input/my-set", "profile_id": "claude-wave-executor"}'
```

#### Watch a run live (terminal)

```bash
make status-watch RUN=<run-id>   # Ctrl-C to exit
tripll status --watch <run-id>
```

Browser: `/runs/<run-id>` (hydrated table + SSE — see above).

#### Approve / resume / pause

```bash
curl -X POST http://localhost:8765/api/runs/<run-id>/approve
curl -X POST http://localhost:8765/api/runs/<run-id>/resume
curl -X POST http://localhost:8765/api/runs/<run-id>/pause
```

#### Runtime configuration

```bash
curl http://localhost:8765/api/config
curl -X PUT http://localhost:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"max_parallel": 5, "cost_budget_usd": 50.0}'
```

See [`.env.example`](../.env.example) for the full list of `TRIPLL_*`
environment variables and their defaults.

---

## 10. Dashboard UI information architecture (W0 lock)

Locked for the LAP-style observability dashboard (decisions D1–D12 in
`plan/tripll-dashboard-ui-wave-plan.md`). Implementation waves W1–W4 build
on this contract; W0 stops at route stubs and helper schemas.

### Page map

| Route | Purpose |
|-------|---------|
| `GET /` | **Runs home** — list runs, launch-run form (W2), profile/backend summary |
| `GET /runs/{id}` | **Run detail** — hydrated wave table, live SSE, fragment hosts |
| `GET /agents` | **Agent profiles** list (W2) |
| `GET /agents/new` | Create profile form (W2) |
| `GET /agents/{id}/edit` | Edit profile form (W2) |
| `GET /settings` | Runtime config form bound to `GET/PUT /api/config` (W2) |
| `GET /docs` | Swagger UI (external tab from nav) |

**Top nav (D8):** Agents \| Runs \| Settings \| API docs — rendered via `_nav.html`
(W2).

### Run detail panel layout (top → bottom)

1. **Run header** (`_run_header.html`, W1.2 / W4.2) — state badge, cumulative
   cost, live/offline indicator, pause/escalation banners (D10), links to
   `logs/` and `report.md`.
2. **Batch timeline** (`_batch_timeline.html`, W4.1) — horizontal swimlanes from
   `graph.json` batch layers (fallback: `report.md` phase headings, D9).
3. **Wave table** — one row per wave node; hydrated on first paint via
   `latest_events_by_node` (D2, W1.1); SSE row updates unchanged from W5.
4. **Event timeline sidebar** (`#event-timeline`, W1.3) — scrollable append-only
   feed; initial HTML from `list_events` (last N=500); SSE appends new rows
   (D3).
5. **Per-wave expanders** (W1.4 / W3) — log viewer (`_log_viewer.html`),
   attempt history (`_attempts.html`), wave-task checklist (`wave_task.py`, D6),
   worktree panel (`_worktree_panel.html`, D5).

### HTML fragment routes (stubs in W0, bodies in W1–W4)

| Route | Delivers |
|-------|----------|
| `GET /runs/{id}/timeline` | Event timeline partial |
| `GET /runs/{id}/waves/{node_id}/log` | Log tail viewer (`?attempt=N`, D4) |
| `GET /runs/{id}/waves/{node_id}/worktree` | Git status + diff stat (poll 5 s, D5) |
| `GET /runs/{id}/batch-timeline` | Batch swimlane chart |
| `GET /runs/{id}/report` | `report.md` render or `<pre>` fallback |

Fragment GETs accept the same `?token=` query param as SSE when
`TRIPLL_API_TOKEN` is set (D12).

### Data helper contracts

#### `latest_events_by_node(run_id)` (D2)

Implemented in `tripll.ledger.latest_events_by_node`. Returns
`dict[node_id, EventRow]` collapsing the append-only `events` table to one row
per node using the same algorithm as `cli._status_watch`:

- **phase**, **last_action**, **ts**, **event_id** — from the latest event row.
- **input_tokens**, **output_tokens**, **cost_usd** — cumulative; carry forward
  the last non-`None` value per field across events for that node.

Used to hydrate the wave table on `GET /runs/{id}` (W1.1) without a second
pipeline.

#### Safe log path resolver (D4)

Module: `tripll.api._artefacts`.

- **Pattern:** `runs/<folder>/<run_id>/logs/<sanitized-node-id>-attempt<N>.log`
- **Allowed folders:** `processing`, `processed`, `failed`
- **Sanitization:** `node_id` → replace `:` and `/` with `_`, strip `>` (matches
  `engine._safe`).
- **Filename regex:** `^.+-attempt\d+\.log$`
- **Containment:** resolved path must stay under `logs/` and the run directory;
  reject `..`, symlinks, and missing files.
- **Tail default:** `MAX_LOG_TAIL_BYTES = 200 * 1024` (200 KiB); read-only.

#### Worktree status response (D5)

Module: `tripll.api._worktree_status`.

```json
{
  "branch": "wave/<run-id>/<lane>-<wave>",
  "changed_count": 3,
  "changed_paths": ["src/foo.py", "tests/test_foo.py"],
  "diff_stat_lines": [" src/foo.py | 10 +++++-----", " 1 file changed, ..."],
  "head_sha": "<full-sha>"
}
```

- **Poll interval:** 5 s (`WORKTREE_POLL_INTERVAL_S`) via htmx while phase ∈
  `{running, verifying}`.
- **Stop polling:** when phase is terminal (`done`, `failed`, `blocked`,
  `deferred`, etc.) or pre-active (`queued`, `dispatched`, `gate_pending`).
- **No git writes** from the API; reuses `worktrees.changed_paths` +
  `git diff --stat HEAD`.

#### Wave task parser (D6)

Module: `tripll.wave_task`.

- **Input:** staged plan markdown slice (`worktrees.staged_wave_plan_path`) +
  optional `last_action` and `phase`.
- **Bullet pattern:** `- [ ] **Wn.m** …` or `- [x] **Wn** …`
- **Output:**

```json
{
  "bullets": [
    {"id": "W0.1", "text": "…", "checked": false, "active": false},
    {"id": "W0.2", "text": "…", "checked": false, "active": true}
  ],
  "inferred_task_id": "W0.2"
}
```

- **Inference:** longest case-insensitive substring match between `last_action`
  and bullet text wins; fallback when `phase=running`: first unchecked bullet.

#### SSE event JSON (optional W3 fields)

Poll (`GET /api/runs/{id}/events`) and SSE (`GET /api/runs/{id}/events/stream`)
return the same JSON object per event. W5 clients ignore unknown keys.

Required keys (unchanged): `event_id`, `run_id`, `node_id`, `ts`, `phase`,
`last_action`, `input_tokens`, `output_tokens`, `cost_usd`.

Optional keys (W3, omitted when unknown):

| Field | When present |
|-------|----------------|
| `attempt_n` | `phase=dispatched` — 1-based attempt from engine dispatch |
| `task_id` | `phase` ∈ `{running, verifying}` with `last_action` — inferred from staged plan (D6) |

### LAP observability parity checklist (D11)

| Capability | Wave | Status at W0 |
|------------|------|--------------|
| Hydrated run detail on load | W1.1 | Contract locked (D2) |
| Live event timeline (replay + SSE) | W1.3 | Contract locked (D3) |
| Run header (state, cost, live, pause) | W1.2, W4.2 | IA documented |
| Launch run + agent CRUD forms | W2.3–W2.4 | Routes in page map |
| Batch timeline from graph/report | W4.1 | Fragment route stub |
| Nav chrome + favicon | W2.1–W2.2 | Nav targets documented |
| Safe log viewer | W1.4 | Resolver locked (D4) |
| Attempt visibility | W3.1 | Schema references `attempts` table |
| Wave task progress | W3.3 | Parser contract locked (D6) |
| Git worktree live diff | W3.4 | Schema locked (D5) |

**Out of scope (D11):** LiteLLM Rust CP, Postgres, remote executor management.

### W0 review gate (W0.7)

Operator sign-off required on this §10 layout, D1–D12, and fragment route list
before W1/W2 implementation begins.

---

## 11. Orchestrator mode (dashboard + live feed)

**Status:** W0 design lock (2026-06-16 — `plan/tripll-orchestrator-mode-wave-plan.md` W0)
**Depends on:** §10 dashboard IA (run detail layout, SSE event pipeline)
**Locked decisions:** D1, D3, D12, D13, D14 in orchestrator-mode plan

Orchestrator mode surfaces **Multitask-style operator updates** on the run detail page and in the terminal without changing §1–§2 process model: the engine remains the execution authority; the dashboard **observes** `orchestrator-status.md` and ledger `events` with `phase=orchestrator`.

### Relationship to §10 dashboard

| §10 (dashboard v1) | §11 (orchestrator mode) |
|---------------------|-------------------------|
| Run header, batch timeline, wave table | **Orchestrator panel** below header (W5) |
| Per-node SSE (`phase` = wave lifecycle) | Additional `phase=orchestrator` events (W3) |
| Event timeline sidebar | Orchestrator feed (turn log excerpt) |
| Worktree / log / task panels | Unchanged — still per wave node |

Orchestrator mode is **opt-in** (D1, D14): runs without `*-orchestrator-prompt.md` render run detail exactly as §10.

### Run detail panel layout (orchestrator mode)

Insert between items 1 and 2 of §10 run detail layout:

```text
1. Run header (_run_header.html)
1b. Orchestrator panel (_orchestrator_panel.html)     ← NEW (W5.1)
1c. Orchestrator feed (_orchestrator_feed.html)       ← NEW (W5.2)
2. Batch timeline
3. Wave table
…
```

#### Orchestrator panel (`_orchestrator_panel.html`, D13)

Hydrated from `orchestrator-status.md` snapshot or server-side parse (W5.1):

| UI element | Source |
|------------|--------|
| **Status table** | `## Status table` in `orchestrator-status.md` |
| **Current wave** | Latest `wave_dispatched` or in-progress row |
| **STOP / REVIEW gates** | Latest turn type `review_gate` or `stop` |
| **Next action** | Parsed from latest turn body or engine `last_action` |
| **Wave summary one-liner** | Run header extension when current wave terminal (W5.5, D6) |

Tone: short paragraphs and table rows — match Cursor Multitask, not raw `engine.log` dump.

#### Orchestrator feed (`_orchestrator_feed.html`)

Scrollable turn log — last **20** turns (W5.2):

- Timestamp, type badge (`bootstrap`, `wave_complete`, `review_gate`, …)
- One-line summary
- Link to full wave log when `node_id` present

Initial HTML from file parse; live updates via SSE or poll (below).

### SSE vs poll (D13)

**Preferred (DRY):** reuse existing `GET /api/runs/{id}/events/stream` SSE; client filters `phase === "orchestrator"` (W5.3). Engine appends orchestrator events in W3 with `last_action` = one-line summary and optional JSON `metadata` (turn type, markdown excerpt ≤500 chars).

**Fallback / supplement:** htmx fragment poll every **2 s** on `GET /runs/{id}/orchestrator` while run is live — same stop conditions as worktree panel (§10, D5: stop when run terminal or paused at gate).

| Mechanism | Delivers | When |
|-----------|----------|------|
| SSE `phase=orchestrator` | New turn summaries, status row updates | W3+W5; preferred |
| htmx poll 2 s | Full panel + feed fragment refresh | SSE gap or initial hydrate |
| `orchestrator-status.md` read | First paint before SSE connects | W5.1 |

Dedicated `GET /api/runs/{id}/orchestrator/stream` is optional if client-side filter proves insufficient; default is filtered events SSE.

### Fragment routes (W5 stubs)

| Route | Delivers |
|-------|----------|
| `GET /runs/{id}/orchestrator` | Panel + feed partial (status table + turn log excerpt) |
| `GET /api/runs/{id}/orchestrator` | JSON snapshot for scripting |

### Terminal parity (D12)

`make status-watch RUN=…` prints **Orchestrator** block (status table + last 3 turns) above the per-node table (W3.3). Optional `make orchestrator-watch RUN=…` tails `orchestrator-status.md` only.

Terminal and dashboard read the **same** `orchestrator-status.md` content — no second formatting pipeline.

### W0 review gate (W0.8)

Operator sign-off required on §11 layout, `OrchestratorConfig` (design-note §8.6), `orchestrator-status.md` schema (§8.7), and agent split (`wave-orchestrator` vs `wave-runner`) before W1 implementation.

---

## 12. LangGraph execution seam (code factory L1)

**Status:** W6/W12 — optional `graph` extra
**Depends on:** §1 process model (engine remains authority), §5 events table

When the `graph` extra is installed (`uv sync --extra graph`), wave and PR loops may run
through LangGraph compiled graphs in `src/tripll/loops/`:

| Loop | Module | Role |
|------|--------|------|
| L1 outer | `l1_outer.py` | Wave dispatch + verify + retry |
| L1 PR | `l1_pr.py` | Push, open PR, fix CI/review, merge gate |

**Checkpointing:** `AsyncSqliteSaver` with `thread_id == run_id`, `durability="sync"`.
Checkpoints are **derived** — the ledger (`ledger.db`) stays the system of record (D6).
If a checkpoint is lost, replay state from the ledger and task graph.

**Degradation without `graph` extra:** Linear batch execution via `Engine` continues to work.
Cyclic plans and the PR fix loop require LangGraph — install `graph` or use `tripll[all]`.

**Dashboard (§12 telemetry):** Run detail includes L1 panels — graph subgraph for the
focus wave, findings grouped by state, exit caps near firing — see `_l1_panels.html`.

**CLI parity:**

```bash
tripll run …                           # engine path (default)
tripll pr shepherd <run-id>            # PR loop (requires graph extra for full loop)
```

See [`docs/design-note.md`](design-note.md) §0 and [`docs/harness-checks.md`](harness-checks.md).
