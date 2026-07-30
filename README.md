# tripll

<p align="center">
  <img src="about-tripll/assets/logo.svg" alt="tripll" width="128" height="128" />
</p>

**Why tripll?** Most wave-plan automation teaches you *how* to dispatch before it explains
*why* — and every failed run evaporates when the archive closes. The problem is not missing
agents or plans; it is that **nothing durable survives a run**. A wave fails five times, a
human fixes it, and the next dispatch starts from the same priors instead of the lesson.

tripll is a headless, parallel **wave-plan execution pipeline** that compounds what each run
learns: findings become **rules**, rules pack into the next brief, executable patterns fail
`make rules-check`, and calibration scores predicted difficulty against the ledger.

```bash
uv tool install tripll && tripll setup && tripll doctor
```

From a target checkout, onboard and validate before your first dispatch:

```bash
cd ~/code/my-project && tripll init && tripll validate-plan docs/plans/*-wave-plan.md
```

See the [product pipeline diagram](about-tripll/assets/pipeline.html) and the
[rules runbook](docs/runbooks/rules-runbook.md) for the compounding loop end to end.

---

## New here? Start here

If you only have `pip install tripll` (or `uv tool install tripll`) and a git checkout you
want to automate, follow this path **before** the operator sections below:

```bash
uv tool install tripll        # or: pip install tripll
tripll setup                  # once per machine — providers, models, tracing
tripll doctor                 # confirm backends and repo layout will run
cd ~/code/my-project && tripll init     # brownfield: specs + evaluation + tripll.toml
# — or —
tripll new my-project                   # greenfield: scaffold + starter docs
cd my-project && tripll doctor
tripll validate-plan docs/plans/*-wave-plan.md
make run-set SET=my-set                 # or tripll run runs/input/my-set
```

| Step | What you get |
|------|----------------|
| **`tripll setup`** | Machine config at `~/.config/tripll/config.toml` (providers, default models). |
| **`tripll doctor`** | Readiness report — missing logins surfaced as actions, never stored secrets (**R24**). |
| **`tripll init`** | Brownfield: `tripll.toml`, starter specs/PRDs/plans, `docs/evaluation-<date>.md` with file:line evidence, `runs/` dirs. Idempotent — operator edits preserved. |
| **`tripll new`** | Greenfield: Python skeleton + the same emitters as `init`. |

**Config precedence (four layers):** CLI flags → environment (`TRIPLL_*`) → repo
`tripll.toml` → machine `~/.config/tripll/config.toml`. See
[`docs/runbooks/onboarding-runbook.md`](docs/runbooks/onboarding-runbook.md).

**Human gates:** v3 plans may set `[pipeline] human_gates` to `prompt` (default),
`auto_accept`, or `fail`. Override with `TRIPLL_HUMAN_GATES=auto_accept` for unattended
Pre-0 when tier-4 canaries pass — documented in
[`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md#human-gate-modes-human_gates).

Deep dives: [`docs/design-note.md`](docs/design-note.md) ·
[`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md) ·
[`docs/runbooks/onboarding-runbook.md`](docs/runbooks/onboarding-runbook.md) ·
[`docs/runbooks/rules-runbook.md`](docs/runbooks/rules-runbook.md).

---

## Pipeline overview

Drop a folder of plan files into `runs/input/`, and `tripll` will:

1. Parse the set into a **RunGraph** (lanes, batches, Pre-0 gates, CW seams).
2. Dispatch each wave to an agent backend in dependency order.
3. Stop at the **Pre-0 human gate** until you approve.
4. Retry failed waves (**5 attempts** for impl waves, then escalate).
5. Optionally **integrate** each batch on one branch (`--integrate`).
6. **Compound** — resolved findings propose rules; operators promote; active rules pack into
   the next brief and may fail `make rules-check` when executable.

Interactive diagram: [`about-tripll/assets/pipeline.html`](about-tripll/assets/pipeline.html).

---

## Prerequisites

Run all commands from this directory (the `tripll` checkout).

| Requirement | Notes |
|-------------|--------|
| **uv** | `uv sync` installs the `tripll` CLI into this project's env — it is **not** on global PATH. Use **`make`** targets below. |
| **Backend** | Default `claude_code` needs `claude` on PATH. See [`.env.example`](.env.example) — tripll has **no API keys**; auth lives in the backend toolchain. |
| **Target repo** | Dispatch runs against a target git checkout (worktrees, verify commands). Point at it with `TRIPLL_REPO_ROOT`, or run from inside it. |
| **Extras** | `graph` (LangGraph loops), `kg` (NetworkX replica), `api` (dashboard), `obs` (Logfire). See [Optional extras](#optional-extras) below. |

```bash
cp .env.example .env    # optional: TRIPLL_RUNS, TRIPLL_DEBUG
make setup              # uv sync (dev/api/obs/graph) + git hooks
make init               # once: creates runs/{input,processing,processed,failed}/
```

### Optional extras

Install with `uv sync --extra <name>` or `make setup` (includes dev + api + obs + graph):

| Extra | Purpose |
|-------|---------|
| `graph` | LangGraph L1 outer + PR loops, durable checkpoints |
| `kg` | NetworkX graph replica for analytics |
| `api` | FastAPI control plane + live dashboard |
| `obs` | Logfire/OpenTelemetry tracing (no-op without `LOGFIRE_TOKEN`) |
| `all` | `graph` + `kg` + `api` + `obs` |

**Code KG** (no extra beyond core CLI):

```bash
tripll graph extract --repo .     # build .tripll/graph.db
tripll graph query <node_id>      # 2-hop neighbourhood
tripll findings sync --pr <n>     # CI + review → Finding nodes
```

Graph-packed briefs are the default dispatch path; use `--grep-brief` for legacy A/B.
See [`docs/graph-serving.md`](docs/graph-serving.md) and [`docs/ontology.md`](docs/ontology.md).

**No API keys in tripll** — auth lives in backend toolchains (`claude`, `cursor-agent`).
PR review CI uses optional `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`
(`.github/workflows/mergecraft.yml` — [mergeCraft](https://github.com/alexhawat/mergeCraft)).
Local advisory review: `make review` or `tripll review diff`.

---

## CLI readiness

The `tripll` console script ships with this repo. After `make setup`:

```bash
uv run tripll --help          # top-level command groups
uv run tripll --version       # tripll 0.0.1
make help                     # operator Make targets (preferred day-to-day)
```

**Status:** production-ready for operator workflows — init, validate, plan, run, pause/resume,
Pre-0 HITL, hotfix inject, graph reconcile, dashboard (`serve`), code KG (`graph`), findings
sync, integrate/deliver, PR shepherd, doc gates (`spec` / `prd` / `changelog`), and bench
replay. Backend auth lives in your toolchain (`claude`, `cursor-agent`), not in tripll.

### Command groups (`tripll --help`)

| Group | Subcommands | Purpose |
|-------|-------------|---------|
| **Run lifecycle** | `init`, `run`, `plan`, `validate`, `validate-plan`, `status`, `list-runs`, `pause`, `resume`, `approve`, `pre0-interview`, `reset-run`, `delete-run`, `run inject`, `run reconcile-graph` | Parse input sets, start/pause/resume runs, Pre-0 gates, hotfix inject, plan reconcile |
| **Control plane** | `serve` | FastAPI dashboard + HTTP API (`--extra api`) |
| **Code KG** | `graph extract`, `graph fuse`, `graph gate`, `graph query` | Build `.tripll/graph.db`, pack wave briefs |
| **Findings** | `findings sync`, `findings list`, `findings triage` | CI + review → Finding graph |
| **PR phase** | `pr shepherd`, `pr status`, `pr approve-merge` | Push/open/fix loop + human merge gate |
| **Doc gates** | `spec validate\|score`, `prd …`, `changelog check\|eval`, `doc-score` | Absorbed skw validators (`src/tripll/skw/`) |
| **Bench** | `bench run` | Frozen L1 task replay + D23 metric deltas |
| **Legacy alias** | `skw` | Deprecated entry; use `tripll spec` / `tripll run` instead |

Copy-paste introspection:

```bash
uv run tripll run --help
uv run tripll graph --help
uv run tripll pr --help
uv run tripll spec --help
uv run tripll findings --help
```

---

## Entry points

| Entry point | When to use | Example |
|-------------|-------------|---------|
| **`make` targets** | Day-to-day operator flow; sets `TRIPLL_RUNS`, backend flags | `make run-set SET=my-set` |
| **`tripll` CLI** | Scripting, CI, passthrough | `uv run tripll run runs/input/my-set` |
| **Dashboard** | HITL wizards, live wave table, L1 panels | `make serve` → `http://localhost:8765` |
| **HTTP API** | Automation against the control plane | `POST /api/runs`, SSE `/api/runs/{id}/events/stream` |
| **Python modules** | Turn-bundle plan builder, tests | `python -m tripll.build_plan_from_errors` |
| **Doc gates** | Spec/PRD/CHANGELOG CI parity | `make spec-check`, `make changelog-check` |

**Runs root:** defaults to `./runs` in the tripll checkout (absolute path via Makefile).
Onboarded **target repos** default to `.tripll/runs/`; legacy top-level `runs/` is kept when
it already exists. Override with `TRIPLL_RUNS=/path/to/runs` or `tripll --runs-root /path/to/runs`.

**Target repo:** wave dispatches run against the git checkout tripll orchestrates. Set
`TRIPLL_REPO_ROOT=/path/to/checkout` or run from inside the target repo; tripll walks up to
find `.git`.

**Backend passthrough:** `PROVIDER=cursor_local MODEL=auto make run-set SET=…` is equivalent to
`tripll run … --backend cursor_local --model auto`.

---

## Build and run a pipeline

End-to-end flow from a blank plan to a merged PR:

```
Author plan (v3) → validate → plan (dry-run) → run → Pre-0 approve → waves dispatch
    → integrate (optional) → deliver (push/open PR) → PR shepherd (fix loop) → approve-merge (human)
```

### 1. Author a wave plan (format v3)

Copy [`docs/wave-plan-template.md`](docs/wave-plan-template.md). Required: TOML front matter with
`waveorch_format = 3`, typed `[[waves.depends_on]]`, per-wave `targets`, and optional
`[waves.outcome]` contracts. Use agent [`docs/agents/plan-author.md`](docs/agents/plan-author.md)
(or legacy [`wave-plan-author.md`](docs/agents/wave-plan-author.md) for v1→v3 conversion).

Place the file under `runs/input/<set>/`:

```
runs/input/my-feature/
  my-feature-wave-plan.md
  review-hints.yaml          # optional CW seams
```

Legacy v1 (`## tripll execution graph`) and v2 (`waveorch_format = 2`) still compile; prefer v3
for new work. See [Mode B-v3](#mode-b-v3--wave-plan-with-execution-graph-recommended) below.

### 2. Validate

Two complementary gates:

```bash
# Execution graph + shape checks (compiler)
make validate-set SET=my-feature
# or: uv run tripll validate runs/input/my-feature/

# In-repo path refs (hard-fail before dispatch)
uv run tripll validate-plan runs/input/my-feature/my-feature-wave-plan.md
```

`make plan-set` always runs `validate` first.

### 3. Plan (dry-run)

Print batch order, lanes, and Pre-0 gates without dispatching:

```bash
make plan-set SET=my-feature              # validate + write parallel-wave.md
make dry-run-set SET=my-feature           # sample dispatch argv + brief preview

# CLI equivalents:
uv run tripll plan runs/input/my-feature --dry-run
uv run tripll plan runs/input/my-feature --dry-run --write-manifest
uv run tripll run runs/input/my-feature --dry-run
```

### 4. Run

```bash
make run-set SET=my-feature
# Block until Pre-0 HITL completes (dashboard or CLI interview):
WAIT_FOR_HITL=1 make run-set SET=my-feature

# CLI:
uv run tripll run runs/input/my-feature --wait-for-hitl
uv run tripll run runs/input/my-feature --backend cursor_local --model auto
```

Run claims `runs/input/<set>/` into `runs/processing/<run-id>/` and stops at Pre-0 unless the
plan has no W0 review items.

### 5. Pre-0 approve and resume

```bash
make pre0-interview RUN=<run-id>    # terminal questionnaire
make finish-pre0 RUN=<run-id>       # interview + approve + resume
# or dashboard: Open HITL → Submit & approve → Resume
```

### 6. Monitor, pause, and resume

```bash
make status RUN=<run-id>
make status-watch RUN=<run-id>
uv run tripll pause <run-id>                    # request graceful pause
uv run tripll resume <run-id>
make resume-run RUN=<run-id> PROVIDER=cursor_local MODEL=auto
```

### 7. Hotfix inject and graph reconcile (paused runs)

While a run is paused, apply mid-run course corrections:

**Mode A — one-line hotfix** (narrow path scope; no plan edit):

```bash
uv run tripll pause <run-id>
uv run tripll run inject <run-id> --after <wave-id> --brief "…" --paths src/foo.py
uv run tripll resume <run-id>
```

**Mode B — plan edit + reconcile** (full wave section with verify targets):

```bash
uv run tripll pause <run-id>
# edit *-wave-plan.md under runs/processing/<run-id>/
uv run tripll run reconcile-graph <run-id>
uv run tripll resume <run-id>
```

See [`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md) §6.

### 8. Integrate and deliver (optional)

Dispatch-only is the default (worktree branches + `report.md`, no merges). To merge batches
locally and open a PR:

```bash
make tripll ARGS='run runs/input/my-feature --integrate --dry-run'
make tripll ARGS='run runs/input/my-feature --integrate --deliver --dry-run'
make tripll ARGS='run runs/input/my-feature --integrate --deliver'
```

Integration branch: `tripll/integrate/<run-id>` (push target for `--deliver`).

### 9. PR phase (after impl waves)

tripll never auto-merges. After waves complete, the PR loop pushes the branch, opens a PR,
syncs findings, and dispatches fix agents until required checks pass:

```bash
uv run tripll pr shepherd --run <run-id> --phase deliver
uv run tripll pr shepherd --run <run-id> --phase investigate_and_fix
uv run tripll findings sync --pr <n> --run-id <run-id>
uv run tripll pr status <run-id>
uv run tripll pr approve-merge <run-id>    # human merge gate only
```

Dashboard run detail shows **Code factory L1** panels (subgraph, findings, exit caps). Full
operator guide: [`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md) §8.

### Graph-packed briefs (default dispatch context)

Before or during a run, build the code KG so wave briefs include a 2-hop subgraph:

```bash
uv run tripll graph extract --repo . --repo-root /path/to/target
uv run tripll graph query src/tripll/engine.py --hops 2
```

Use `--grep-brief` on `run`/`resume` for legacy A/B comparison. See [`docs/graph-serving.md`](docs/graph-serving.md).

---

## Examples cookbook

Thirteen copy-paste workflows covering the main entry points:

**1. Validate an input set before planning**

```bash
make init
make validate-set SET=my-set
uv run tripll validate runs/input/my-set/
```

**2. Plan + inspect graph (no dispatch)**

```bash
make plan-set SET=my-set
uv run tripll plan runs/input/my-set --dry-run --write-manifest
```

**3. Dry-run dispatch argv**

```bash
make dry-run-set SET=my-set PROVIDER=claude_code
uv run tripll run runs/input/my-set --dry-run --backend cursor_local --model auto
```

**4. Start a run with HITL auto-resume**

```bash
make serve                                    # terminal 1
WAIT_FOR_HITL=1 make run-set SET=my-set       # terminal 2
```

**5. Orchestrator-mode serial smoke**

```bash
make seed-orchestrator-smoke-set
make validate-set SET=orchestrator-mode-smoke
make run-set SET=orchestrator-mode-smoke PROVIDER=cursor_local MODEL=auto
make finish-pre0 RUN=<run-id> PROVIDER=cursor_local MODEL=auto
```

**6. Build a plan from gateway turn-bundle errors**

```bash
make dry-run-build-plan-from-errors FOLDER=/path/to/workspace/.sevn/turns
make build-plan-from-errors FOLDER=/path/to/workspace/.sevn/turns
make validate-set SET=from-errors-<run_id>
make run-set SET=from-errors-<run_id>
```

**7. Code KG extract + query (graph-packed briefs)**

```bash
uv run tripll graph extract --repo . --repo-root .
uv run tripll graph fuse
uv run tripll graph query src/tripll/cli.py --hops 2 --db .tripll/graph.db
```

**8. Sync PR findings into the graph**

```bash
uv run tripll findings sync --pr 42 --run-id <run-id>
uv run tripll findings list --state open
uv run tripll findings triage F-abc123 --state rejected --rationale "noise"
```

**9. L1 bench replay (D23 metrics)**

```bash
uv run tripll bench run
uv run tripll bench run --bench-dir bench/ --db .tripll/graph.db
```

**10. Doc gates (absorbed skw)**

```bash
make spec-check                    # tripll spec validate docs/
make prd-check                     # tripll prd validate docs/prd/
make changelog-check               # tripll changelog check
uv run tripll spec score docs/ --repo-root .
uv run tripll changelog eval --repo-root . --base origin/main   # advisory LLM score
```

**11. PR shepherd one-liners**

```bash
uv run tripll pr shepherd --run <run-id> --phase deliver
uv run tripll pr shepherd --run <run-id> --phase investigate_and_fix
uv run tripll pr status <run-id>
uv run tripll pr approve-merge <run-id>
```

**12. Dashboard + API launch**

```bash
make serve
tripll serve --host 0.0.0.0 --port 9000
curl -s http://localhost:8765/health
curl -s http://localhost:8765/api/runs | jq .
```

**13. Passthrough any subcommand via Make**

```bash
make tripll ARGS='status'
make tripll ARGS='run runs/input/dev-eval --integrate --deliver --dry-run'
make tripll ARGS='run inject <run-id> --after W3 --brief "hotfix" --paths src/foo.py'
make tripll ARGS='resume <run-id> --wait-for-hitl'
```

More input-set layouts: [Input shapes](#input-shapes), [Orchestrator mode](#orchestrator-mode-cursor-multitask-parity).

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

### Mode B-v3 — wave plan with execution graph (recommended)

For **execution-order awareness** (W0 → R1 → … → Final inside one plan file),
use **tripll format v3** (`waveorch_format = 3` in TOML front matter):

1. Copy [`docs/wave-plan-template.md`](docs/wave-plan-template.md) or convert a legacy example
   with [`docs/agents/plan-author.md`](docs/agents/plan-author.md).
2. Fill TOML: `[[waves]]` rows with `targets`, typed `[[waves.depends_on]]`, optional
   `[waves.outcome]` contracts, run-level `[pipeline]` deadline/budget.
3. Validate and generate a deterministic manifest:

```bash
make validate-set SET=my-set          # must pass before plan
uv run tripll validate-plan runs/input/my-set/*-wave-plan.md
make plan-set SET=my-set              # validates + writes parallel-wave.md + prints graph
make run-set SET=my-set
```

Use agent [`docs/agents/plan-author.md`](docs/agents/plan-author.md) for new v3 plans, or
[`docs/agents/wave-plan-author.md`](docs/agents/wave-plan-author.md) to convert legacy v1 narrative
plans.

**Machine-readable schema (v3):**

| Field | Purpose |
|-------|---------|
| `waveorch_format = 3` | Canonical plan version |
| `[[waves]]` + `id`, `role`, `targets`, `verify` | Wave nodes and one-writer paths |
| `[[waves.depends_on]]` + `reason` | Typed edges (`artifact`, `contract`, `gate`) |
| `[waves.outcome]` | Required/forbidden/evidence contracts (graders decide done) |
| `[pipeline]` | Run deadline, budget, turn caps |

Legacy v1 (`## tripll execution graph` table) and v2 (`waveorch_format = 2`) compile via
`tripll.plan.compat_v1_v2` with a one-time warning — prefer v3 for new plans.

**Tests-first model (design-note §9):** the optional `role` column (`impl` \| `test-author`, default
`impl`) drives a tests-first flow — `W0 (gate) → W1 test-creator (full RED suite) → impl waves
(green) → Final`. **W1 is always `test-creator`**, the single owner of `tests/`; implementation waves
are forbidden from editing tests (engine `TEST_PATHS` overlay) and get **5 attempts** before
escalation. See [`docs/agents/test-creator.md`](docs/agents/test-creator.md).

`make plan-set` always runs **`validate` first**, then **`plan --write-manifest`**
(same bytes for the same graph — no timestamps).

### Mode B-legacy — plain wave files without execution graph

Legacy Mode B (no v3/v1 section) clusters files into lanes by path overlap only —
**one node per plan file**, not per `## Wave R*` section. Prefer v3 for
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
make plan-set SET=telemetry-only   # fails validate until v3 (or v1) graph added
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
  tripll-orchestrator-mode-wave-plan.md          # v3 execution graph (+ optional orchestrator_mode: serial)
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

All targets run from **this directory** (the `tripll` checkout). Variables:

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
| `make validate-set SET=<name>` | Validate wave-plan(s) in `runs/input/<name>/` |
| `make validate-input` | Validate every input subdirectory |
| `make spec-check` | Validate specs in `docs/` (doc gate) |
| `make changelog-check` | Deterministic CHANGELOG gate vs `origin/main` |
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
| `make check` | Lint + typecheck + mergeCraft pin + about-site + test |
| `make bench` | Replay sealed brief-packing benchmark (tier 2; see `bench/`) |
| `make review` | Advisory mergeCraft diff review vs `origin/main` |
| `make about-site` | Regenerate `about-tripll/` HTML from `_sources/` |
| `make seed-orchestrator-smoke-set` | Copy W0 orchestrator example → `runs/input/orchestrator-mode-smoke/` |
| `make smoke-orchestrator-w0` | Orchestrator W0 smoke — validate + plan + pytest |
| `make orchestrator-watch RUN=<id>` | Tail `orchestrator-status.md` only (orchestrator mode, D12) |

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
3. Each wave: dispatch → verify → `done`, `unverified`, or retry (max **5** attempts → `blocked`).
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
| **Run detail** (`/runs/{id}`) | Hydrated wave table (provider, model, effort, cost) on first paint; SSE live updates; run header (state, cost, per-provider rollup, live/offline, pause/escalation banners); batch timeline swimlanes; **L1 panels** (graph subgraph, findings, exit caps); event timeline sidebar (500-event replay + SSE tail); Approve / Resume / Pause buttons; collapsible `report.md` embed |
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
| `TRIPLL_API_TOKEN` | When set, requires Bearer token on **all HTML pages and JSON API routes** (R4). Dashboard injects token into htmx headers and `?token=` on SSE/fragment URLs. **Required** when binding beyond localhost. |
| `TRIPLL_HUMAN_GATES` | Override plan `[pipeline] human_gates`: `prompt`, `auto_accept`, or `fail`. |
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
Add `--integrate` and `--deliver` via passthrough:

```bash
make tripll ARGS='run runs/input/dev-eval --integrate --dry-run'
make tripll ARGS='run runs/input/dev-eval --integrate --deliver --dry-run'
make tripll ARGS='run runs/input/dev-eval --integrate --deliver'
```

---

## Folder layout

```
runs/                        # tripll checkout default (also .tripll/runs/ on target repos)
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

Onboarded target repos default to `.tripll/runs/`; legacy top-level `runs/` is kept when it
already exists. Override root: `TRIPLL_RUNS=/path/to/runs` or `tripll --runs-root …`.

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
