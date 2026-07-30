# wave-orchestrator / tripll — design note (code factory L1)

**Status:** Code factory L1 — post-remediation (2026-07-27)
**Date:** 2026-06-15 (W0) · updated 2026-07-25 (L1 task graph)
**Author:** wave-runner W0 pass · L1 executor W12
**Design:** `.ignorelocal/design/plan/tripll-code-factory-design.md` (§7–§13) ·
[`docs/design/quality-gauntlet.md`](design/quality-gauntlet.md) (D26–D28, quality inner loop)

---

## 0. Code factory L1 — task graph, harness, exits

L1 turns tripll from a wave **dispatcher** into a **level-1 code factory**. The execution
graph (`RunGraph`) is mirrored into a **task layer** in `.tripll/graph.db` alongside the
authoritative **SQLite ledger** (D6). LangGraph checkpoints (`graph` extra) are optional and
derived — recovery replays from the ledger.

### 0.1 Three graph layers

| Layer | Contents | Store |
|-------|----------|-------|
| `code` | Modules, symbols, tests, specs, requirements, CI checks | `.tripll/graph.db` |
| `task` | Plans, waves, attempts, gates, PRs, env fingerprints | same DB + ledger |
| `finding` | CI failures, review comments, verifier outcomes, **Rules** (repo-scoped) | same DB |

Ontology: `src/tripll/ontology/ontology.yaml`. Docs: [`docs/ontology.md`](ontology.md),
[`docs/graph-serving.md`](graph-serving.md), [`docs/harness-checks.md`](harness-checks.md).

### 0.2 Ledger vs checkpoint

| Artifact | Role |
|----------|------|
| `ledger.db` | **System of record** — wave states, attempts, events, costs |
| `.tripll/graph.db` task layer | Derived task graph; brief packer + findings attach here |
| LangGraph `AsyncSqliteSaver` | Optional loop seam; `thread_id == run_id`; not authoritative |
| `graph.json` | Legacy derived snapshot for dashboard/tests (one release overlap) |

### 0.3 Exit table (§7.10)

| # | Name | Fires when | Engine |
|---|------|------------|--------|
| 1 | goal_met | Outcome contract + CI green + `mergecraft-approval` success | **Engine-live** |
| 2 | turn_cap | `max_attempts=5` exhausted (impl waves) | **Engine-live** |
| 3 | budget_cap | `TRIPLL_COST_BUDGET_USD` exceeded | **Engine-live** |
| 4 | wall_clock | Per-wave limit or run deadline | **Engine-live** |
| 5 | no_progress | Three identical graph-delta hashes | **Engine-live** |
| 6 | human_interrupt | Operator pause / kill switch | **Engine-live** |
| 7 | error_threshold | Circuit breaker per `(agent, problem_type)` | **Engine-live** |
| 8 | external_event | PR merged/closed or source issue closed | **Engine-live** |

Implementation: `src/tripll/loops/exits.py` (`evaluate_exit`); routing lives in
`src/tripll/engine_exits.py` and is reached through the `Engine` façade, which records
``exit_fired`` events on the ledger.
Dashboard shows caps near firing and marks fired exits (§12).

### 0.4 Telemetry seams (§12 — L2 inputs, recorded in v1)

Per attempt: agent/prompt hashes, model, `EnvFingerprint`, tokens, cost, wall clock, outcome,
scope breaches, grader results, findings raised/fixed.

Per run: attempts-to-green, first-attempt pass rate, escalations, **exit fired** (via
``exit_fired`` ledger events), findings by kind,
stale-finding rate, human gate wait, total cost, graph-brief vs grep-brief (D23).

**Calibration loop (W5, R28 advisory).** At compile time, ``compile_plan`` emits a
``first_pass_probability`` Metric per wave under an ``Experiment`` node
(``Hypothesis`` → ``Experiment`` → ``PREDICTED`` / ``REALIZED`` in the finding layer).
After the run, ``tripll calibrate --run <id>`` reads ``ledger.attempts``, writes REALIZED
``attempts_to_green`` and ``first_attempt_pass_rate`` Metrics, and reports a Brier score per
predictor version — or **uncalibrated** when fewer than three prior runs exist. Predictions are
scored and surfaced in ``report.md``; they never change routing, model selection, attempt budget,
or gate behaviour.

### 0.5 Migration (§13)

1. Ledger unchanged — task layer written **alongside**, not instead.
2. `graph.json` retained one release as derived artifact.
3. Plan v1/v2 readers warn once; v3 is canonical.
4. `CW_HOTSPOTS` retired after corpus replay proves equivalence.
5. `build_plan_from_errors` kept as sevn turn-bundle entry point.
6. `skw run --wave` preserved as thin alias.
7. Extras: `graph`, `kg`; stale `ai` extra dropped.

### 0.6 Post-L1 capability boundaries

L1 remediation (W9, W10, D15, ADR 009) closed **one** honest PR investigate→fix path and
shipped graph-packed briefs as the default dispatch context. These boundaries remain after
`wave/l1-remediation`:

| Topic | Shipped in L1 | Still not automatic / out of scope |
|-------|---------------|-------------------------------------|
| **PR → CI fix → review fix loop** | `loops/l1_pr.py` + `dispatch_bridge.py` (W9): LangGraph investigate/fix nodes call real adapters (`ci-investigator` → `check-fixer`, review triager/fixer). Idempotent push/open via `github/pr.py`. Operator CLI: `tripll pr shepherd`, `findings sync`, `pr approve-merge`. | **Not wired into `Engine._drive` or `tripll run`.** One closed loop only (R10); no auto-merge (D15) — loop parks at the human merge gate. |
| **L1 outer wave dispatch** | With `[graph]` installed, `Engine._drive` routes batch dispatch through `l1_outer` → `waves` → `dispatch_bridge.invoke_engine_wave_dispatch` → `Engine.drive_wave_batches` (L2-W4). Post-wave nodes **verify → commit → review → generate** run Final-batch gates, write completion manifests, audit ledger wave rows, and optionally dispatch `post-review-wave-generator` when `orchestrator.review_generate_cycle` is set. Ledger remains authoritative; checkpoints derived. | **Orchestrator serial mode bypasses the outer graph.** Generate cycle does not auto-merge (D15). |
| **`--integrate`** | Per-batch local merge → Docs&Menu → `make ci-resume` → one Conventional Commit on `tripll/integrate/<run-id>` (`integrate.py`). Resume-safe branch creation (no blind `checkout -B`). | **Default OFF.** Does not open GitHub PRs; delivery to remote CI/review is the separate PR phase above. |
| **Dispatch briefs** | Graph-packed brief is the **default** when the code graph is available (`engine._resolve_grep_brief`, `brief.enrich_brief_with_graph_pack`, W10/D23). Packed subgraph replaces the legacy no-exploration line. | Agents still must not run repo-wide grep, graphify, or architecture tours unless the packed context is insufficient (`brief.GRAPH_PACKED_DIRECTIVE`). Legacy grep brief: `--grep-brief` for A/B replay. |
| **LangGraph vs ledger** | Optional `graph` extra: L1 PR loop + durable `AsyncSqliteSaver` checkpoints (`thread_id == run_id`). | **`ledger.db` remains the system of record** (§0.2, D6). Checkpoints are derived; recovery replays from the ledger. Linear DAG runs work without LangGraph. |

---

## 1. Graph data model

### 1.1 WaveNode

The atomic unit of work — a single wave from a single plan.

```python
@dataclass
class WaveNode:
    node_id: str            # "<plan_id>:<wave_id>"  e.g. "plan-1:W0"
    plan_id: str            # short slug  e.g. "provider-runtime-telemetry"
    plan_file: Path         # abs path to the wave-plan .md file
    wave_id: str            # exact heading label  e.g. "W0", "W1", "TI-0"
    lane: str               # logical lane name  e.g. "Telemetry"
    owned_paths: list[str]  # from lane table in parallel-wave.md
    forbidden_paths: list[str]  # derived (other lanes' owned + CW hotspots)
    effort: str             # "S" | "M" | "L" | "XL"
    wall_clock_limit_s: int # 2700 (45 min) or 5400 (90 min for XL)
    depends_on: list[str]   # list of node_ids this must follow
    is_review_gate: bool    # True for W0/CA0/ND0/PP0/SS0/F0/M0 review nodes
    verify_targets: list[str]  # make targets to run after dispatch
    docs_menu_sync: list[str]  # make targets for Docs&Menu sync (may be [])
```

### 1.2 Lane

A named group of disjoint plans that share owned paths and run on one worktree branch.

```python
@dataclass
class Lane:
    lane_id: str            # e.g. "telemetry", "self-improve"
    plans: list[str]        # plan_ids in this lane
    owned_paths: list[str]  # disjoint from all other lanes
    waves: list[WaveNode]   # ordered list of waves in this lane
    branch: str             # "wave/<run-id>/<lane-id>"
    worktree_path: Path | None  # allocated under runs/<run-id>/worktrees/
```

### 1.3 Batch

A group of lanes that can run in parallel (paths disjoint, no CW-4/CW-5 conflict).

```python
@dataclass
class Batch:
    batch_id: str           # "Pre-0" | "A" | "B" | ... | "Final"
    label: str              # human label
    lanes: list[str]        # lane_ids in this batch
    is_human_gate: bool     # True for Pre-0 and W0 review-gate batches
    gate_commands: list[str]  # make targets to run at Batch Final
    cw_seams: list[str]     # coordination wave IDs that serialize within batch
    merge_order: list[str]  # lane merge order at Batch Final
```

### 1.4 RunGraph

The top-level execution graph for one run.

```python
@dataclass
class RunGraph:
    run_id: str             # "<slug>-<YYYYMMDD-HHMMSS>"
    source_mode: Literal["A", "B"]  # A = parallel-wave set; B = plain wave folder
    batches: list[Batch]    # ordered Pre-0 → A → … → Final
    lanes: dict[str, Lane]  # lane_id → Lane
    nodes: dict[str, WaveNode]  # node_id → WaveNode
    pre0_gates: list[str]   # gate items collected at Pre-0
    cw_seams: dict[str, list[str]]  # CW-id → [node_ids that serialize on it]

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = OK).

        Checks: cycle detection, owned-path overlap between lanes,
        CW-seam consistency, gate-before-implementation ordering.
        """
        ...
```

---

## 2. JSON dispatch-brief schema

One brief is emitted per WaveNode dispatch. Fields match the `wave-runner` "Quick start template".

```json
{
  "$schema": "https://tripll/schemas/dispatch-brief.v1.json",
  "brief_version": "1.0",
  "run_id": "<run-id>",
  "node_id": "<plan-id>:<wave-id>",
  "plan_file": "plan/dev_eval_14062026/provider-runtime-telemetry-wave-plan.md",
  "wave_id": "W1",
  "branch": "wave/<run-id>/telemetry-w1",
  "worktree_path": "runs/<run-id>/worktrees/telemetry-w1",
  "prerequisite_waves": ["plan-1:W0"],
  "bullets_in_scope": 4,
  "specs_with_10x_row": "none",
  "locked_decisions": ["D1", "D3", "D6"],
  "owned_paths": [
    "src/sevn/agent/adapters/",
    "src/sevn/agent/tracing/",
    "src/sevn/gateway/mission_state*",
    "tests/ui/dashboard/",
    "tests/e2e/mission-control/observability/"
  ],
  "forbidden_paths": [
    "src/sevn/gateway/agent_turn.py",
    "src/sevn/gateway/http_server.py",
    "Makefile",
    "src/sevn/ui/dashboard/api/tab_registry.py",
    "src/sevn/ui/dashboard/app.js",
    "infra/sevn.schema.json",
    "src/sevn/self_improve/",
    "src/sevn/gateway/replay_worker.py"
  ],
  "verify_targets": ["make ci-affected"],
  "docs_menu_sync_targets": [],
  "manual_smoke_deferred": [],
  "wall_clock_limit_s": 2700,
  "retry_policy": {
    "max_attempts": 5,
    "on_5th_failure": "escalate"
  },
  "agent_directives": [
    "Leave changes staged; do not commit.",
    "Do not run make ci-resume mid-wave — use make ci-affected.",
    "Do not edit the ci: Makefile target.",
    "Do not edit forbidden_paths listed above.",
    "No src/sevn/ edits outside owned_paths."
  ]
}
```

### 2.1 CW hotspot paths (always in forbidden_paths for non-owner lanes)

```
src/sevn/gateway/agent_turn.py   — CW-1 (turn-hook finally)
src/sevn/gateway/http_server.py  — CW-2 (lifespan boot)
Makefile (ci: line)              — CW-3
src/sevn/ui/dashboard/app.js     — CW-4
src/sevn/ui/dashboard/api/tab_registry.py  — CW-4
infra/sevn.schema.json           — CW-5
```

---

## 3. Wave state machine

```
                 ┌─────────┐
                 │  queued │  ← initial state after RunGraph is built
                 └────┬────┘
                      │  deps satisfied + concurrency slot available
                      ▼
              ┌─────────────┐
              │ dispatched  │  ← brief sent to agent adapter
              └──────┬──────┘
                     │  adapter confirms receipt
                     ▼
              ┌─────────────┐
              │  verifying  │  ← outcome contracts + make targets (+ wave-verifier)
              └──────┬──────┘
                     ▲
              ┌──────┴──────┐
              │ quality_loop│  ← optional reference gauntlet (D26–D28)
              └──────┬──────┘
                     │  agent reports done / adapter stream closes
                     ▼
              ┌─────────────┐
              │   running   │  ← agent is executing (wall-clock timer starts)
                     │
           ┌─────────┼──────────┐
           │         │          │
           ▼         ▼          ▼
       ┌──────┐ ┌───────────┐ ┌──────────┐
       │ done │ │ unverified│ │  failed  │  ← attempt N < 5 → retry (queued again)
       └──────┘ └───────────┘ └────┬─────┘   attempt 5 → escalate
                                   │
                                   ▼
                            ┌─────────┐
                            │ blocked │  ← 5th failure; human review required
                            └────┬────┘
                                 │  tripll approve <run-id> --node <node-id>
                                 ▼
                          ┌──────────┐
                          │ queued   │  ← re-entered with corrected brief
                          └──────────┘

       ┌──────────┐
       │ deferred │  ← explicit deferral annotation in wave plan;
       └──────────┘    does not block downstream non-dependent waves

       ┌──────────────┐
       │ gate_pending │  ← is_review_gate=True; engine pauses until
       └──────────────┘    `tripll approve <run-id>` is called
```

**Terminal states:** `done`, `blocked`, `deferred`
**Honest non-terminal:** `unverified` — required grader could not run (never promoted to `done`)
**Resumable states:** All non-terminal states persist in SQLite ledger (D6).

---

## 4. Folder / run-id layout

```
wave-orchestrator/
├── runs/
│   ├── input/                      ← drop a parallel-wave dir or plain wave folder here
│   ├── processing/
│   │   └── <run-id>/               ← active run
│   │       ├── graph.json          ← serialized RunGraph
│   │       ├── ledger.db           ← SQLite state ledger (runs/waves/attempts)
│   │       ├── briefs/
│   │       │   └── <node-id>.json  ← emitted dispatch brief per wave
│   │       ├── worktrees/
│   │       │   └── <lane>-<wave>/  ← git worktree checkouts (D5)
│   │       └── logs/
│   │           └── <node-id>-attempt<N>.log
│   ├── processed/                  ← completed runs (moved from processing/)
│   │   └── <run-id>/
│   │       ├── graph.json
│   │       ├── ledger.db
│   │       └── report.md           ← per-run summary
│   └── failed/                     ← runs with any blocked/escalated wave
│       └── <run-id>/
│           ├── ledger.db
│           └── escalation.md       ← evidence for operator review
│
├── docs/                           ← design notes (this file + backend-inventory.md)
├── spike/                          ← W0 read-only spike scripts
│   ├── parse_dev_eval.py           ← W0.2: Mode A parser spike
│   └── mode_b_spike.py             ← W0.3: Mode B generate + round-trip
│
└── README.md                       ← (W1+ Final)
```

### 4.1 Run-id format

```
<slug>-<YYYYMMDD>-<HHMMSS>
```

Examples:
- `dev-eval-20260615-160012`
- `my-waves-20260615-163045`

The slug is derived from the input directory name (sanitized to `[a-z0-9-]`, max 32 chars).

### 4.2 Mode A input layout

Drop a directory containing:
- `parallel-wave.md` (required)
- `parallel-wave-review.md` (optional; adds CW seams + batch-sequencing corrections)
- `parallel-wave-orchestrator-prompt.md` (optional; adds Pre-0 gate list)
- Individual plan `*-wave-plan.md` files (for per-lane brief rendering)

### 4.3 Mode B input layout

Drop a directory containing N plain `*-wave-plan.md` files. No pre-existing `parallel-wave.md` required. The parser reads each file's `## Files in scope` table and `depends on` headers, clusters plans into lanes by path-disjointness, infers batch order from deps, and **writes a generated `parallel-wave.md`** before handing off to the Mode A engine.

---

## 5. SQLite ledger schema (preview — W1 will define migrations)

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    source_mode TEXT NOT NULL CHECK (source_mode IN ('A', 'B')),
    input_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',  -- active | done | failed | paused
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    graph_json TEXT                         -- serialized RunGraph
);

CREATE TABLE waves (
    node_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    plan_id TEXT NOT NULL,
    wave_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',   -- state machine above
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, node_id)
);

CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    node_id TEXT NOT NULL,
    attempt_n INTEGER NOT NULL,
    backend TEXT NOT NULL,                  -- claude_code | cursor_local | cursor_cloud
    brief_path TEXT,
    log_path TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT,                           -- done | failed | timed_out | scope_breach
    evidence TEXT                           -- failure message or scope-breach file list
);
```

---

## 6. Batch sequencing (dev_eval as canonical example)

```
Pre-0  (HUMAN GATE)  → research + operator decisions
Batch A → CW-1 + CW-2 (shared hotspot code), then parallel: #10.0, #11.E0/E5, #12.H0, #16.W0, #17.CA0
Batch B → Telemetry: #1 W0→W4, #10.1, #11.E1
Batch C → Self-improve: #3 TI-0→TI-3, #10.2, #11.E2, #2 (parallel), #11.E6
Batch D → Gateway UX + P1: #5 W1→W2, #6 W0, #16 W1→W3, #17 CA1→CA2, #11 E3/E4
Batch E → Independent: #4, #7, #8, #9, #18 ND0→ND5, #19 PP0→PP4, #20 SS0→SS4
Batch F → Upstream intel: #12 H1→H2, #12 H3∥H4
Batch G → Remote deploy: #13 RD0→RD3
Batch H → Hermes messaging: #14 M0→M1, #14 M2∥M3∥M4
Batch I → Hermes features: #15 F0, #15 F1∥F2∥F3∥F4, #17 CA3→CA6
Batch Final → make ci-resume, make mc-e2e, parity checks, per-plan Docs&Menu sync
```

---

## 7. Locked decisions (post-W0 sign-off)

### 7.1 Pre-0 gate derivation — LOCKED

**Decision:** Auto-derive Pre-0 gates from `is_review_gate=True` nodes in the generated `RunGraph`. No explicit `pre0-gates.md` required in Mode B.

`WaveNode.is_review_gate = True` whenever the wave-id matches the review-gate pattern (W0, TI-0, CA0, ND0, PP0, SS0, F0, M0, etc.). The engine collects all such nodes as the Pre-0 gate list automatically.

### 7.2 Effort → wall-clock mapping — LOCKED

| Effort | Wall-clock limit |
|--------|-----------------|
| S      | 45 min (2700 s) |
| M      | 45 min (2700 s) |
| L      | 45 min (2700 s) |
| XL     | 90 min (5400 s) |

No change from the W0 proposal.

### 7.3 Cloud adapter test scope — LOCKED

Cloud adapter (`cursor_cloud.py`) implementation and testing **deferred to W4**. The `[cloud]` extra is declared in `pyproject.toml` but no cloud-adapter code ships before W4.

### 7.4 Mode B CW seams — LOCKED

**Decision: Option B with Option A as fallback** (2026-06-15 ✅: operator locked)

When Mode B parses plain wave files (no `parallel-wave-review.md`), the parser uses an optional `review-hints.yaml` sidecar for CW owner assignment; falls back to the default forbidden-path set (§2.1) when the file is absent.

**Behaviour:**

- If `review-hints.yaml` is present in the input folder, the Mode B parser reads it and assigns CW ownership to the named lanes — those lanes may edit their respective CW hotspot files; all other lanes treat those files as forbidden.
- If `review-hints.yaml` is absent, the parser falls back to Option A: the full CW hotspot list (§2.1) is added to `forbidden_paths` for **all** lanes (no lane owns any hotspot).

**`review-hints.yaml` schema (optional; Mode B only):**

```yaml
# review-hints.yaml  (optional; Mode B only)
cw_owners:
  CW-1: telemetry       # lane that may edit agent_turn.py
  CW-2: gateway-ux      # lane that may edit http_server.py
  CW-3: ci-owner        # lane that may edit Makefile ci: line
  CW-4: dashboard       # lane that may edit app.js / tab_registry.py
  CW-5: config          # lane that may edit sevn.schema.json
```

- **Pros:** zero friction for common cases (most spec-impl work has no CW owner lane — just drop the folder); explicit, auditable CW ownership when needed; Mode B can generate the same quality brief as Mode A.
- **Implementation gate:** W2 `parse/plan_files.py` reads `review-hints.yaml` if present (D10). W1 is unblocked — no parser work in W1.

---

## 8. Orchestrator mode

**Status:** W0 design lock (2026-06-16 — orchestrator-mode plan W0)
**Source plan:** `plan/tripll-orchestrator-mode-wave-plan.md`
**Locked decisions:** D1–D14 in that plan

Orchestrator mode adds **Cursor Multitask parity** to headless tripll runs: status tables, turn log, wave-complete summaries, and review-gate messaging in **terminal**, **`orchestrator-status.md`**, **`report.md`**, and the **dashboard** — without requiring a Cursor chat session.

### 8.1 Architecture — two layers

```text
┌─────────────────────────────────────────────────────────────────┐
│  Input dir                                                       │
│  • *-orchestrator-prompt.md  (wave order, verify, REPORTING)    │
│  • *-wave-plan.md            (execution graph, locked D1–D14)   │
└────────────────────────────┬────────────────────────────────────┘
                             │ parse (W1)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  RunGraph + OrchestratorConfig (optional)                        │
│  serial_waves, single_branch, commit_per_wave, review_gates      │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┴───────────────────┐
         │                                       │
         ▼                                       ▼
┌─────────────────────┐              ┌─────────────────────────────┐
│  Engine formatter   │              │  LLM gate agent (optional)  │
│  (deterministic)    │              │  wave-orchestrator          │
│                     │              │                             │
│  • status table     │              │  • review gates only        │
│  • turn log append  │              │  • recoverable STOP         │
│  • ledger events    │              │  • TRIPLL_ORCHESTRATOR_   │
│  • brief overrides  │              │    AGENT=1 (W4)             │
│  • wave dispatch    │              │  • does NOT own every turn  │
└─────────┬───────────┘              └─────────────────────────────┘
          │
          │ dispatches
          ▼
┌─────────────────────┐
│  wave-runner        │  one subagent per wave (serial when
│  (implementer)      │  single_branch / orchestrator_mode: serial)
└─────────────────────┘
```

**Engine formatter (D2):** owns status table rendering, turn log append, terminal/dashboard feed, and wave-runner dispatch. It does **not** replace wave dispatch with an LLM loop every turn.

**LLM gate agent (D2, D9):** optional `wave-orchestrator` invocation at **review gates** and **recoverable STOP** (quota, 3× verify fail). Cursor Multitask sessions use the same agent definition for full serial coordination.

### 8.2 Opt-in rules (D1)

Orchestrator mode activates when **both** are true:

1. Input dir contains `*-orchestrator-prompt.md` — glob prefers `{slug}-orchestrator-prompt.md`, else any `*orchestrator-prompt.md`.
2. Wave plan or prompt declares `orchestrator_mode: serial` (default **serial** when prompt present).

When the prompt is **absent**, parallel lane runs behave exactly as today (D14). Mode A `parallel-wave-orchestrator-prompt.md` remains Pre-0 gate list only; the new parser is a superset (W1).

### 8.3 Single-branch mode (D8)

When `OrchestratorConfig.single_branch: true`:

- All waves use **one worktree** on `feature_branch` (no per-wave lane worktrees).
- Engine sets `max_parallel=1` and iterates `serial_waves` in prompt order (topological fallback from graph).
- Conflicts with parallel batch A — orchestrator mode **forces serial graph execution**.

### 8.4 Artefact layout

Per-run artefacts under `runs/<folder>/<run-id>/`:

| Artefact | Role |
|----------|------|
| `orchestrator-status.md` | Append-only turn log + latest status table at top (D3) |
| `report.md` | Ops/batch view; gains `## Orchestrator` section linking status (W3) |
| `review-gate-pending.md` | Pause marker when review gate triggered (W2) |
| `graph.json` | Optional `orchestrator: OrchestratorConfig` block (W1) |

**`orchestrator-status.md`** is distinct from `report.md`: status file is the Multitask-style live feed; report is the batch summary. Both cross-link.

Atomic rewrite: engine writes via temp file then rename (same pattern as other run artefacts).

### 8.5 Turn types (D5)

Each append to the turn log records one of:

| Type | When emitted |
|------|----------------|
| `bootstrap` | Run start; feature branch + baseline SHA recorded |
| `wave_dispatched` | Before wave-runner dispatch; status row → in progress |
| `wave_complete` | After verify pass; includes `wave_summary` (D6) |
| `wave_failed` | Verify fail or scope breach |
| `review_gate` | Wave has `review_gate`; run paused for operator |
| `stop` | Unrecoverable halt (push fail, 3× verify, operator STOP) |
| `resume` | Operator approved gate or resumed from pause |
| `orchestrator_agent` | Optional LLM gate dispatch completed |

### 8.6 OrchestratorConfig (locked W0.3)

Serialized on `RunGraph.orchestrator` when orchestrator mode is active (W1.2):

```python
@dataclass
class OrchestratorConfig:
    enabled: bool
    prompt_path: str
    feature_branch: str | None
    single_branch: bool
    commit_per_wave: bool
    verify_target: str  # default "partial-ci"
    ci_base: str        # default "origin/test-pre"
    serial_waves: list[str]  # ordered wave_ids from prompt or graph
    review_gates: dict[str, str]  # wave_id -> gate label (e.g. W0.8)
    model_policy: str   # "inherit" | "auto"
    agent_wave: str     # default "wave-runner"
    agent_orchestrator: str  # default "wave-orchestrator"
```

**Field notes:**

- `verify_target` — Makefile target name run from **repo root** after each wave (typically `partial-ci` with `SEVN_CI_BASE=ci_base`).
- `serial_waves` — explicit order from orchestrator prompt table; engine falls back to topological sort of graph when empty.
- `review_gates` — maps wave_id (e.g. `W0`) to gate label (e.g. `W0.8`) for pause + `AWAITING REVIEW` status.
- `model_policy` — when `inherit` or orchestrator MODEL POLICY says omit, adapters strip execution-graph `composer-*` defaults (D11).

### 8.7 orchestrator-status.md schema (locked W0.4)

Top-level Markdown structure (rendered by `orchestrator_status.py` in W1):

```markdown
# Orchestrator status — {run_id}

**Updated:** {iso_ts}
**Feature branch:** `{feature_branch}` | **Mode:** serial

## Status table

| Wave | Status | Branch | Commit | Evidence / blockers |
|------|--------|--------|--------|---------------------|
| W0 | done | `feature/…` | `abc1234` | design-note §8, agent defs |
| W1 | pending | … | — | … |

## Turn log

### Turn 1 — bootstrap

{iso_ts} — Created `feature/…` from `test-pre` @ `{baseline_sha}`.

### Turn 2 — wave_dispatched

{iso_ts} — Dispatched wave-runner for **Wave W0**.

### Turn 3 — wave_complete

{iso_ts} — W0 complete. Commit `def5678`.

**Summary:** {wave_summary — first H2 block or first 2000 chars of agent result}

### Turn 4 — review_gate

{iso_ts} — **AWAITING REVIEW** (W0.8). Operator sign-off on D1–D14 before W1.
```

**Rules:**

- `## Status table` is **rewritten** on each transition (latest snapshot at top of file).
- `## Turn log` is **append-only** — new `### Turn N — {type}` sections only; never edit prior turns.
- Status table columns match Cursor Multitask export (D4): **Wave | Status | Branch | Commit | Evidence / blockers**.
- Parser in W1 extracts REPORTING FORMAT template from orchestrator prompt when present.

### 8.8 Brief overrides (D7, preview)

When `commit_per_wave: true`, engine replaces default `AGENT_DIRECTIVES` with orchestrator prompt policy:

- Commit + push on green verify
- `make partial-ci` from repo root (`SEVN_CI_BASE=ci_base`)
- Never `--no-verify`
- Single integration `feature_branch` when `single_branch: true`
- Required completion markdown block (`## Wave {id} complete`, files touched, verification)

Full implementation: W2 `brief.orchestrator_directives()`.

### 8.9 Agent split (D9)

| Dispatch | Agent | When |
|----------|-------|------|
| Wave implementation | `wave-runner` | Every wave in orchestrator mode |
| Review gate / STOP recovery | `wave-orchestrator` | Optional headless; always in Cursor Multitask |

Wave dispatches use `agent_wave` (default `wave-runner`), not `wave-plan-executor`, when orchestrator profile sets `agent=wave-runner` (W4).

## 9. Tests-first model + test-creator agent (locked W0)

Locked decisions for the `test-creator` / tests-first wave model. Wave order becomes:

```text
W0 (design/contract gate) → W1 (test-creator: full suite, RED) → impl waves (green) → Final
```

### 9.1 `role` column (D5)

The execution graph gains an optional 8th column **`role`** with values `impl` | `test-author`
(default `impl`; absent column or blank cell → `impl`). `WaveSpec.role` and `WaveNode.role` carry it;
`validate_wave_plan_v1` rejects any other value. **W1 is always `role: test-author`.**

### 9.2 `TEST_PATHS` forbidden overlay (D7)

`graph.TEST_PATHS = ["tests/", "wave-orchestrator/tests/"]`. `derive_forbidden_paths(..., node=...)`
applies a **node-level overlay**: every node whose `role != "test-author"` forbids `TEST_PATHS`
(even when its lane owns them); the `test-author` node does not. The existing lane-level derivation
(other lanes' owned paths + CW hotspots) is unchanged. Setting `TEST_PATHS = []` disables the overlay.

### 9.3 `agent_test` (D3)

`OrchestratorConfig.agent_test` and `ParsedOrchestratorPrompt.agent_test` default to `test-creator`,
mirroring `agent_wave` / `agent_orchestrator`; parsed from an `agent_test:` key in the prompt. The
brief routes `role: test-author` nodes to `agent_test`, all others to `agent_wave`.

### 9.4 5-attempt cap (D1)

`Engine.max_attempts` default is **5** (was 3): impl waves get 5 tries to pass the suite, then
escalate (`blocked`). The escalation banner is parameterised on `self.max_attempts` (no hardcoded
"3"); brief `retry_policy` is `{"max_attempts": 5, "on_5th_failure": "escalate"}`.

### 9.5 Escalation ownership (D3)

On a `blocked` impl wave, the orchestrator re-dispatches a **fresh coding agent** (clean context).
**Only `test-creator` ever edits a test** — re-dispatched solely when the test itself is judged
wrong. Coding agents never touch `tests/`.

### 9.6 xfail discipline

Cross-wave not-yet-green tests use **non-strict** `xfail(reason="green after WN", strict=False)`.
`strict=True` is forbidden for cross-wave reds: when the impl wave lands, a strict xfail that now
passes becomes `XPASS(strict)` = a hard failure the impl wave (forbidden from tests) cannot fix.
After each impl wave the orchestrator re-dispatches `test-creator` to remove satisfied markers.

### 9.7 cookiecutter integration (D4)

`audreyfeldroy/cookiecutter-pypackage` is integrated two ways: (a) its pytest layout / fixtures /
parametrize / cross-version conventions are adopted in the `test-creator` instructions; (b) an
optional `scaffold-package` step (`src/tripll/scaffold.py` + Makefile target, `scaffold` extra)
shells out to `uvx cookiecutter` and **normalizes** the output to sevn standards — `justfile` →
Makefile, `ty` → mypy, drop `tox.ini` + `.github/workflows/`, keep `tests/` + `pyproject.toml`.
cookiecutter is an optional dependency, not a runtime dep.

## 10. Pipeline pathfix — plan paths, validate gate, role dispatch (locked W0)

Locked contracts from `plan/tripll-pipeline-pathfix-wave-plan.md` Wave W0 (2026-06-19).
Implementation waves: W2–W7; tests authored in W1 (RED).

### 10.1 `plan_paths.py` API (locked W0.1)

New module `tripll/plan_paths.py` (W3):

```python
def normalize_plan_refs(text: str, repo_root: Path) -> tuple[str, list[str]]:
    """Rewrite in-repo refs to repo-root-relative; return (new_text, external_parent_dirs)."""

def find_unresolved_refs(text: str, repo_root: Path) -> list[str]:
    """Return in-repo refs that do not resolve under repo_root."""

def validate_plan(plan_path: Path, repo_root: Path) -> list[str]:
    """Read plan; return dead in-repo ref strings (empty = valid)."""
```

`normalize_plan_refs` is pure (no FS writes). Call sites: `stage_dispatch_context` (W3),
`validate-plan` CLI + pipeline promotion gate (W4).

### 10.2 Normalization rules (locked W0.2)

- **Scan:** markdown `](path)` targets and inline backtick refs pointing inside `repo_root`.
- **Rewrite:** `../`, `./`, and in-repo leading `/` → repo-root-relative (`specs/…`, `src/…`, …).
- **Idempotent:** bare `specs/foo.md` unchanged.
- **Ignore:** anchor tokens without path separator (`telegram_format.py:to_telegram`, `foo.py:bar`).
- **External (D3):** absolute paths outside `repo_root` preserved; parent dirs collected for
  `--add-dir` / `workspace_scope` (W3 engine wiring).

### 10.3 Validate gate UX (locked W0.3)

CLI `tripll validate-plan <plan.md> [--repo-root]`:

- Success → exit 0.
- Failure → exit non-zero; one line per bad ref:
  `<plan> → <bad_ref> (try: <suggested_fix>)`.

Pipeline promotion (W4): validate every `*-wave-plan.md` before graph build; abort run on dead
in-repo ref with the same message format.

### 10.4 Role-dispatch toggle (locked W0.4)

| Surface | Name |
|---------|------|
| Config | `OrchestratorConfig.role_dispatch` (`bool`, default `False`) |
| Env | `TRIPLL_ROLE_DISPATCH=1` |
| CLI | `--role-dispatch` / `--no-role-dispatch` on `run` and `resume` |

**Precedence:** CLI > env > plan config > orchestrator-implied (`orchestrator.enabled` implies on).

When effective: `role:test-author` → brief `agent` = `agent_test` (default `test-creator`);
`role:impl` → `agent_wave` (default `wave-runner`). `TEST_PATHS` overlay unchanged (mode-independent).

### 10.5 Claude adapter + backend honor (locked W0.5)

- **D4:** `ClaudeCodeAdapter.build_argv` always passes `--verbose` with `-p --output-format stream-json`.
- **D5:** `DEFAULT_MODEL = "claude-sonnet-4-6"`; per-wave overrides unchanged.
- **D6:** `run`/`resume` honor CLI `--backend/--provider` + `--model`; no persisted-backend override.
  Canonical: `make resume-run RUN=<id> PROVIDER=cursor_local MODEL=auto`.
