# tripll

Headless parallel wave-plan execution pipeline. Drop a folder of plan files into
`runs/input/`, and `tripll` will:

1. Parse the set into a **RunGraph** (lanes, batches, Pre-0 gates, CW seams).
2. Dispatch each wave to an agent backend in dependency order.
3. Stop at the **Pre-0 human gate** until you approve.
4. Retry failed waves (2 retries, then escalate).
5. Optionally **integrate** each batch on one branch (`--integrate`).

Deep dives: [`docs/design-note.md`](docs/design-note.md) (graph model),
[`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md) (operations).

---

## Prerequisites

Run all commands from this directory (the `tripll` checkout).

| Requirement | Notes |
|-------------|--------|
| **uv** | `uv sync` installs the `tripll` CLI into this project's env — it is **not** on global PATH. Use **`make`** targets below. |
| **Backend** | Default `claude_code` needs `claude` on PATH. See [`.env.example`](.env.example) — tripll has **no API keys**; auth lives in the backend toolchain. |
| **Target repo** | Dispatch runs against a target git checkout (worktrees, verify commands). Point at it with `TRIPLL_REPO_ROOT`, or run from inside it. |

```bash
cp .env.example .env    # optional: TRIPLL_RUNS, TRIPLL_DEBUG
make setup              # uv sync (dev/api/obs) + git hooks
make init               # once: creates runs/{input,processing,processed,failed}/
```

---

## Quick run

Minimal path from zero to a started run:

```bash
make init

# Drop ONE input set (see “Input shapes” below), then:
make plan-set SET=my-set          # parse + validate graph (no dispatch)
make run-set SET=my-set           # start run → stops at Pre-0 gate

# Block until HITL is done (polls dashboard / hitl-responses.json, then auto-resume):
WAIT_FOR_HITL=1 make run-set SET=my-set

# Dashboard (terminal 1): make serve  →  http://localhost:8765
# Open run detail → Open HITL → complete wizard → Submit & approve

# After resolving Pre-0 (dashboard modal, API, or CLI interview):
make pre0-interview RUN=<run-id>   # multiple choice + notes → hitl-responses.json + pre0-decisions.md
make continue-run RUN=<run-id>     # approve + resume (after interview)
# Or all three in one step:
make finish-pre0 RUN=<run-id>
# Abandon run and restore input set for a clean restart:
make reset-run RUN=<run-id>
make tripll ARGS='resume <run-id>'
make status RUN=<run-id>
```

To **preview** dispatch argv without executing: `make dry-run-set SET=my-set`.

To **plan or run every folder** under `runs/input/` one after another:

```bash
make plan-input      # graph only, all sets
make run-input       # sequential runs (each may stop at Pre-0)
```

---

## Input shapes

`tripll` always takes a **directory** under `runs/input/<name>/`. The parser
auto-detects Mode A vs Mode B from the files inside.

Mode B Pre-0 gates are **auto-derived from your wave-plan files** — `## Wave W0`
sections and decision-table rows marked “confirm at W0”. They are **not** copied
from the dev_eval set. If your plan has no W0 review items, Pre-0 is empty and
the run proceeds without a human stop.

**Mode A** — parallel-wave set

Use when you already have a coordinated multi-plan manifest (e.g. dev_eval).

**Expected files** (minimum):

```
runs/input/dev-eval/
  parallel-wave.md              # required — lane/batch manifest
  parallel-wave-review.md         # optional — CW ownership + forbidden paths
  *-wave-plan.md                  # one per plan row in the manifest
  parallel-wave-orchestrator-prompt.md   # optional — Pre-0 gate list (Mode A)
```

**Example** (copy the real dev_eval set from the repo):

```bash
make init
cp -r ../plan/dev_eval_14062026 runs/input/dev-eval
make plan-set SET=dev-eval
make run-set SET=dev-eval
```

Mode A batch order comes from `parallel-wave.md` (Pre-0 → coordination batches →
lane batches → Final).

### Mode B-v1 — wave-plan with execution graph (recommended)

For **execution-order awareness** (W0 → R1 → … → Final inside one plan file),
use **tripll format v1**:

1. Copy [`docs/wave-plan-template.md`](docs/wave-plan-template.md) or the
   [telegram example graph](docs/examples/telegram-rich-inline-miniapps-wave-plan.v1.md).
2. Add **`## tripll execution graph`** (and optional **`## tripll batches`**) to
   your `*-wave-plan.md`.
3. Validate and generate a deterministic manifest:

```bash
make validate-set SET=my-set          # must pass before plan
make plan-set SET=my-set              # validates + writes parallel-wave.md + prints graph
make run-set SET=my-set
```

Use agent [`docs/agents/wave-plan-author.md`](docs/agents/wave-plan-author.md) to
convert legacy plans (narrative “Execution order & parallelism” only) into v1.

**Machine-readable tables:**

| Section | Purpose |
|---------|---------|
| `## tripll execution graph` | `wave_id`, `depends_on`, `review_gate`, `verify_targets`, `role` |
| `## tripll batches` (optional) | Explicit batch membership; overrides auto layers |

**Tests-first model (design-note §9):** the optional `role` column (`impl` \| `test-author`, default
`impl`) drives a tests-first flow — `W0 (gate) → W1 test-creator (full RED suite) → impl waves
(green) → Final`. **W1 is always `test-creator`**, the single owner of `tests/`; implementation waves
are forbidden from editing tests (engine `TEST_PATHS` overlay) and get **5 attempts** before
escalation. See [`docs/agents/test-creator.md`](docs/agents/test-creator.md).

`make plan-set` always runs **`validate` first**, then **`plan --write-manifest`**
(same bytes for the same graph — no timestamps).

### Mode B-legacy — plain wave files without execution graph

Legacy Mode B (no v1 section) clusters files into lanes by path overlap only —
**one node per plan file**, not per `## Wave R*` section. Prefer v1 for
single-plan serial/parallel schedules.

**Expected files**:

```
runs/input/telemetry-only/
  provider-runtime-telemetry-wave-plan.md
  review-hints.yaml                          # optional
```

**Single wave file** — put the one file in its own folder:

```bash
mkdir -p runs/input/telemetry-only
cp ../plan/dev_eval_14062026/provider-runtime-telemetry-wave-plan.md \
   runs/input/telemetry-only/
make plan-set SET=telemetry-only   # fails validate until v1 graph added
```

**Multiple wave files** — lane clustering by path overlap (legacy):

```bash
mkdir -p runs/input/self-improve-mini
cp ../plan/dev_eval_14062026/self-improve-proposer-wave-plan.md \
   ../plan/dev_eval_14062026/trajectory-ingest-wave-plan.md \
   runs/input/self-improve-mini/
make plan-set SET=self-improve-mini
```

Mode B Pre-0 gates (legacy): auto-derived from `## Wave W0` sections. CW seams:
optional `review-hints.yaml`; otherwise all CW hotspot paths are forbidden to
every lane (default fallback).

---

## Orchestrator mode (Cursor Multitask parity)

**Opt-in** orchestrator mode adds Multitask-style status tables and turn logs to
headless runs — terminal, `orchestrator-status.md`, `report.md`, and the dashboard
— without a Cursor chat session. Architecture: design-note
[`§8`](docs/design-note.md#8-orchestrator-mode); dashboard IA:
[`control-plane-design.md §11`](docs/control-plane-design.md#11-orchestrator-mode-dashboard--live-feed).

### When to use

| Situation | Use |
|-----------|-----|
| Interactive Cursor Multitask with live subagents | Cursor orchestrator chat + [`wave-orchestrator` agent](docs/agents/wave-orchestrator.md) |
| Detached / overnight runs with same operator UX | **tripll orchestrator mode** (`make run-set`, dashboard, `status-watch`) |
| Parallel lane batches (dev_eval Mode A, no orchestrator prompt) | Default tripll — unchanged (D14) |

### Input set layout

Place **both** files under `runs/input/<set>/`:

```
runs/input/orchestrator-mode-smoke/
  tripll-orchestrator-mode-wave-plan.md          # v1 execution graph (+ optional orchestrator_mode: serial)
  tripll-orchestrator-mode-orchestrator-prompt.md   # serial order, verify, REPORTING FORMAT
```

**Prompt file naming (D1):** prefer `{plan-slug}-orchestrator-prompt.md` (slug from
`*-wave-plan.md` basename). Any `*orchestrator-prompt.md` is accepted when slug match
is missing.

Orchestrator mode activates when the prompt is present and the plan declares
`orchestrator_mode: serial` (default **serial** when prompt present). See locked
decisions D1–D14 in
[`plan/tripll-orchestrator-mode-wave-plan.md`](../plan/tripll-orchestrator-mode-wave-plan.md).

**Implementing teams:** follow
[`plan/tripll-orchestrator-mode-orchestrator-prompt.md`](../plan/tripll-orchestrator-mode-orchestrator-prompt.md)
(serial wave order, commit+push per wave, `make partial-ci`, single integration branch).

### Quick start (single-branch serial)

Example W0 smoke set (copy or seed):

```bash
make seed-orchestrator-smoke-set
make validate-set SET=orchestrator-mode-smoke
make plan-set SET=orchestrator-mode-smoke

make run-set SET=orchestrator-mode-smoke PROVIDER=cursor_local MODEL=auto
# Pre-0 / W0.8 review gate — then:
make finish-pre0 RUN=<run-id> PROVIDER=cursor_local MODEL=auto
```

**Single-branch mode (D8):** one worktree on `feature_branch` from the orchestrator
prompt; engine runs waves **serially** (`max_parallel=1`) in prompt order. Wave
dispatches use **`wave-runner`** for impl waves and **`test-creator`** for the W1
`role: test-author` wave (`agent_test`); optional **`wave-orchestrator`** at review gates when
`TRIPLL_ORCHESTRATOR_AGENT=1`.

Monitor:

```bash
make status-watch RUN=<run-id>        # Orchestrator table + last 3 turns, then per-node table
make orchestrator-watch RUN=<run-id>  # tail orchestrator-status.md only
make serve                            # dashboard Orchestrator panel on run detail
make smoke-orchestrator-w0            # automated W0 validate + parity pytest
```

Full operator flow (review gates, Multitask vs headless decision): [`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md) §8.

Example input set source: [`docs/examples/orchestrator-mode-input-set/`](docs/examples/orchestrator-mode-input-set/).

---

## Makefile reference

All targets run from **`wave-orchestrator/`**. Variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SET` | — | Subfolder name under `runs/input/` (required for `*-set` targets) |
| `BACKEND` | `claude_code` | `claude_code`, `cursor_local`, or `cursor_cloud` |
| `FOLDER` | `.sevn/turns` | Turn bundles directory for `make build-plan-from-errors` / `dry-run-build-plan-from-errors` |
| `RUN` | — | Run-id for `make status RUN=…` |
| `ARGS` | — | Full passthrough for `make tripll ARGS='…'` |
| `TRIPLL_RUNS` | `./runs` (absolute) | Override runs root |

| Target | Purpose |
|--------|---------|
| `make help` | List targets |
| `make sync` | `uv sync --extra dev` — install CLI |
| `make init` | Create `runs/` layout |
| `make list-input` | Show pending sets in `runs/input/` |
| `make build-plan-from-errors FOLDER=<dir>` | Walk unprocessed turn-bundles → one wave plan (W5) |
| `make dry-run-build-plan-from-errors FOLDER=<dir>` | Preview dispatch argv without executing (same `PROVIDER`/`MODEL`/`AGENT`) |
| `make validate-set SET=<name>` | Validate v1 execution graph in `runs/input/<name>/` |
| `make validate-input` | Validate every input subdirectory |
| `make plan-set SET=<name>` | validate + graph + **write** `parallel-wave.md` |
| `make dry-run-set SET=<name>` | Engine dry-run: sample argv / integrate preview |
| `make run-set SET=<name>` | Start one run (`BACKEND=` optional) |
| `make plan-input` | `plan-set` for **every** subdir of `runs/input/` |
| `make run-input` | `run-set` for **every** subdir, sequentially |
| `make status` | List all runs |
| `make status RUN=<id>` | Wave states + escalation evidence for one run |
| `make pre0-interview RUN=<id>` | Interactive Pre-0 decisions (multiple choice + notes) |
| `make approve-run RUN=<id>` | Mark Pre-0 approved after decisions |
| `make resume-run RUN=<id>` | Resume a paused run (`BACKEND=` optional) |
| `make tripll ARGS='…'` | Any subcommand (`approve`, `resume`, `plan`, …) |
| `make check` | Lint + typecheck + test |
| `make seed-orchestrator-smoke-set` | Copy W0 orchestrator example → `runs/input/orchestrator-mode-smoke/` |
| `make smoke-orchestrator-w0` | Orchestrator W0 smoke — validate + plan + pytest |
| `make orchestrator-watch RUN=<id>` | Tail `orchestrator-status.md` only (orchestrator mode, D12) |

From **repo root**, CI only: `make wave-orchestrator-check` → delegates here.

---

## Turn-bundle error plans (`build-plan-from-errors`)

When the gateway collects **turn bundles** under `<content_root>/.sevn/turns/<DDMMYY>/` (see sevn
`WORKSPACE.md` and `diagnostics.turn_bundles.enabled` in `sevn.json`), this target walks
**every unprocessed** index entry across all day partitions (and legacy flat `turns/index.json`
when present), evaluates `has_error`, marks each turn `processed`, and
— when the run finds ≥1 error turn — dispatches **one** agent invocation to emit **one**
tripll v1 `*-wave-plan.md` for the batch.

| Artefact | Path |
|----------|------|
| Agent def | [`docs/agents/build-plan-from-errors.md`](docs/agents/build-plan-from-errors.md) |
| Prompt template | [`docs/prompts/build-plan-from-errors.md`](docs/prompts/build-plan-from-errors.md) |
| Problem taxonomy | [`docs/prompts/build-plan-from-errors-problem-types.md`](docs/prompts/build-plan-from-errors-problem-types.md) — injected into every dispatch; agent classifies each turn against all kinds before writing waves |
| Driver | `src/tripll/build_plan_from_errors.py` |
| Bundle explorer (sevn CLI) | `sevn turn-bundle view <turn_id>` from the workspace that owns `sevn.json` |
| Plan output | `runs/input/from-errors-<run_id>/` (ready for `validate-set` / `run-set`) |

**Typical flow**

```bash
# 1. Enable bundles in sevn.json (or backfill with sevn turn-bundle export)
# 2. From wave-orchestrator/ — default FOLDER is .sevn/turns beside sevn.json
make dry-run-build-plan-from-errors FOLDER=/path/to/workspace/.sevn/turns/160626
make build-plan-from-errors FOLDER=/path/to/workspace/.sevn/turns

# 3. When a plan was written:
make validate-set SET=from-errors-<run_id>
make plan-set SET=from-errors-<run_id>
make run-set SET=from-errors-<run_id>
```

Portable `FOLDER=` and GNU `--folder=` (after the target) both work. Override backend with
`PROVIDER` / `MODEL` / `AGENT` like other dispatch targets. Runs with zero new error turns
emit no plan file; clean turns still flip `processed` in each day's `index.json`.

---

## Run lifecycle

```
runs/input/<set>/  ──run──►  runs/processing/<run-id>/
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Pre-0 STOP      waves dispatch    ledger.db
              (approve)       (backend CLI)     briefs/ logs/
                    │
         approve + resume
                    │
                    ▼
         runs/processed/<run-id>/   or   runs/failed/<run-id>/
```

1. **`run-set`** claims the input folder into `processing/<run-id>/`.
2. Engine stops at **Pre-0** — run `make pre0-interview RUN=<run-id>` (or edit `pre0-decisions.md`), then `approve-run` + `resume-run`.
3. Each wave: dispatch → verify → `done` or retry (max 3 attempts → `blocked`).
4. **`status RUN=<id>`** shows wave states; failures write `escalation.md` + `report.md`.

---

## Control plane (FastAPI + dashboard)

The FastAPI control plane gives you a **LAP-style operator dashboard** (Jinja +
htmx + SSE — no Node build) and an HTTP API for creating profiles, launching
runs, and watching live agent activity. Full browser runbook:
[`docs/control-plane-design.md`](docs/control-plane-design.md) §9.

### Install

```bash
uv sync --extra dev --extra api   # or: make sync-api
```

### Start

```bash
make serve                        # http://localhost:8765/
# or bind a custom address:
tripll serve --host 0.0.0.0 --port 9000
```

Open `http://localhost:8765/` for the live dashboard.
Swagger API docs at `http://localhost:8765/docs`.

### Dashboard features (v1)

| Page | What you see |
|------|----------------|
| **Runs** (`/`) | Runs table (state, cost, live badge); **Launch run** form (input set + profile); backend availability summary |
| **Run detail** (`/runs/{id}`) | Hydrated wave table on first paint; SSE live updates; run header (state, cost, live/offline, pause/escalation banners); batch timeline swimlanes; event timeline sidebar (500-event replay + SSE tail); Approve / Resume / Pause buttons; collapsible `report.md` embed |
| **Wave expander** (per row) | Attempt history + "starting attempt N" badge; wave-task checklist with active bullet; git worktree status + diff stat (5 s poll while running); read-only log tail viewer |
| **Agents** (`/agents`) | Profile list; create/edit forms (backend, model, agent, skills) — no curl required |
| **Settings** (`/settings`) | Runtime config form (`max_parallel`, cost budget, etc.) |
| **Nav** | Agents \| Runs \| Settings \| API docs (Swagger in new tab) |

Information architecture and data contracts: §10 in
[`docs/control-plane-design.md`](docs/control-plane-design.md).

Example v1 execution graph for this dashboard program:
[`docs/examples/tripll-dashboard-ui-wave-plan.v1.md`](docs/examples/tripll-dashboard-ui-wave-plan.v1.md).

### Live terminal tail

```bash
make status-watch RUN=<run-id>   # Ctrl-C to exit
tripll status --watch <run-id> --interval 2
make orchestrator-watch RUN=<run-id>   # orchestrator mode: orchestrator-status.md only
```

Orchestrator mode runs also write `orchestrator-status.md` (Multitask-style status
table + turn log). See README **Orchestrator mode** and operator runbook §8.

### Auth and environment variables

| Variable | Purpose |
|----------|---------|
| `TRIPLL_API_TOKEN` | When set, requires Bearer token on all API/UI fragment requests. Dashboard injects token into htmx headers and `?token=` on SSE/fragment URLs. **Required** when binding beyond localhost. |
| `TRIPLL_RUNS` | Runs root directory (default `./runs`). |
| `TRIPLL_MAX_PARALLEL` | Max concurrent wave dispatches (also editable on Settings page). |
| `TRIPLL_COST_BUDGET_USD` | Run cost budget; pause marker when exceeded. |
| `TRIPLL_SSE_POLL` | SSE tail poll interval in seconds (default `1.0`). |
| `TRIPLL_DEBUG` | Verbose engine logging. |

When `TRIPLL_API_TOKEN` is unset the server allows all localhost connections
(dev mode). Browser `EventSource` clients pass the token as `?token=<tok>` on
the SSE endpoint because browsers cannot set custom `Authorization` headers on
`EventSource`.

See [`.env.example`](.env.example) for the full list of `TRIPLL_*` variables.

### HTTP API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (`{"status":"ok"}`) |
| `GET` | `/api/agents` | List all agent profiles |
| `POST` | `/api/agents` | Create a profile |
| `GET` | `/api/agents/{id}` | Get one profile |
| `PATCH` | `/api/agents/{id}` | Partial-update a profile |
| `DELETE` | `/api/agents/{id}` | Delete a profile |
| `GET` | `/api/runs` | List all runs |
| `POST` | `/api/runs` | Launch a new run |
| `GET` | `/api/runs/{id}` | Run detail + liveness |
| `POST` | `/api/runs/{id}/approve` | Approve Pre-0 gate |
| `POST` | `/api/runs/{id}/resume` | Resume paused run |
| `POST` | `/api/runs/{id}/pause` | Request graceful pause |
| `GET` | `/api/runs/{id}/waves` | List waves |
| `GET` | `/api/waves/{run_id}/{node_id}` | Wave detail |
| `GET` | `/api/runs/{id}/events` | Poll events (`?after=<event_id>`) |
| `GET` | `/api/runs/{id}/events/stream` | SSE live event stream |
| `GET` | `/api/config` | Read runtime config |
| `PUT` | `/api/config` | Update runtime config |
| `GET` | `/api/backends` | Backend availability |

Full operator guide: [`docs/control-plane-design.md`](docs/control-plane-design.md) §9.

---

## Backends

| Backend | CLI / deps | Notes |
|---------|------------|--------|
| `claude_code` | `claude` on PATH | Default. Sub-agent `wave-plan-executor`. |
| `cursor_local` | `cursor-agent` on PATH | Capability-gated; clear error if missing. |
| `cursor_cloud` | `uv sync --extra cloud` + sevn workspace | Live dispatch deferred; manual smoke. |

Dispatch-only default: changes stay staged on worktree branches + `report.md`.
Add `--integrate` via passthrough:

```bash
make tripll ARGS='run runs/input/dev-eval --integrate --dry-run'
```

---

## Folder layout

```
runs/
  input/<set>/               # you drop wave sets here (Mode A or B)
  processing/<run-id>/       # active run
    ledger.db
    graph.json
    pre0-decisions.md
    pre0-approved            # written by approve
    briefs/  logs/  worktrees/
    report.md  escalation.md
  processed/<run-id>/
  failed/<run-id>/
```

Override root: `TRIPLL_RUNS=/path/to/runs` or `tripll --runs-root …`.

---

## Configuration

| What | Where |
|------|--------|
| Runs folder | `$TRIPLL_RUNS` (Makefile sets `./runs`) |
| Debug logging | `$TRIPLL_DEBUG=1` |
| API keys / models | **Not in tripll** — see [`.env.example`](.env.example) per backend |

---

## Development

```bash
make sync
make check        # lint + mypy + pytest
make test
```
