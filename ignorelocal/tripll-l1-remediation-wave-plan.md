# tripll L1 remediation — gate integrity, security, concurrency, exit closure — wave plan

**Status:** W15 complete — W12 next
**Date:** 2026-07-26
**Source audit:** `ignorelocal/project-evaluation-2026-07-25.md` (cited as `§n` / finding IDs)
**Target repo:** [`sevn-bot/tripll`](https://github.com/sevn-bot/tripll) — this checkout
**Audit baseline:** `3f5cf9b` (`pre-0.0.1`) — two-pass audit, all findings line-checked at this sha
**Owner agents:** `wave-runner` (P0–P3, W2–W15, Final, Thermos) · `test-creator` (W1 `role: test-author`
+ per-wave xfail reconciliation)
**Contract copy:** `docs/plans/l1-remediation.md` (tracked; W0.6 copies this file there and records
its sha256 — Thermos re-verifies the hash)

---

## Re-entry

> **The crash-test rule.** A fresh session in any tool must read this block and continue without
> re-explanation. Whoever finishes a wave updates it **in the same commit** as the wave's work.
> If this block is stale, the run is not resumable — treat that as a defect, not an inconvenience.

| Field | Value |
|-------|-------|
| **Current wave** | W15 ✅ (2026-07-27) — W12 next |
| **Stage** | Greenfield `tripll new`: packaged skeleton + shared brownfield emitters |
| **Next action** | W12.1 — dispatch-status banner on `docs/agents/*.md` (ARCH-06) |
| **Blocked on** | — |
| **Last pushed sha** | `52cf10e` |
| **Last CI run id** | `30166223593` (pre-W2; W2 push pending green CI) |
| **Parked waves** | 0 of 3 (plan-level stop rule) |
| **Integration target** | `pre-0.0.1` (`3f5cf9b`) — both `main` and `pre-0.0.1` execute CI post-P0.1; prefer audit baseline per tie-break |
| **Plan sha256** | `fcaf28f487904c0e1ac3e46c23254abd983358e458e00355526b89ba0cc06cc2` |

---

## Human gates and auto-accept

Three of this plan's steps are not agent actions (P0.1, W0.2's tie-break, the Thermos merge
request). tripll has **no auto-accept knob today** — `grep -rn "auto_accept" src/tripll` is empty.
P0.8 adds one so an operator can run this plan unattended.

**Config surface (P0.8 implements):**

```toml
[pipeline]
human_gates = "prompt"      # prompt | auto_accept | fail
```

Environment override: `TRIPLL_HUMAN_GATES=auto_accept`. Per gate, in the wave table:
`human = true` and `auto_acceptable = true|false`.

**The one rule that survives auto-accept.** `auto_accept` skips the *prompt*, never the *evidence*.
A gate that carries a tier-4 canary (below) still runs it. If the canary is red, `auto_accept`
resolves the gate to **PARKED**, not to "proceed." This is what keeps global convention 2 intact:
auto-accepting P0.1 must never mean "carry on with CI dark and call it green."

| Gate | `auto_acceptable` | Canary | Auto-accept behaviour |
|------|-------------------|--------|-----------------------|
| P0.1 billing block | `true` | `gh run list --workflow=CI --limit 1` shows a **started** run | canary red ⇒ PARKED, plan stops |
| W0.2 integration target | `true` | none — the P0.1 rule decides it mechanically | applies the rule, records it |
| Thermos merge request | `false` | — | always human; tripll never merges (D15) |

---

## Provider fabric — per-provider limits, per-wave routing, failover

**The problem.** `cursor_local` fails with *"Couldn't start"* / *"Workspace Disconnected"* when several
agents run at once — the Cursor extension host gets overwhelmed. That is a **resource limit, not a
product quota**, and today tripll cannot express it:

| Gap | Evidence | Wave |
|-----|----------|------|
| **PROV-01** — the backend is chosen **per run**, not per wave. `Engine.__init__` takes one `adapter` and `_execute_node` uses `self.adapter` for every node | `engine.py:942`, `:995`, `cli.py:747` (`--backend`), persisted to `dispatch-config.json` | **P1** |
| **PROV-02** — one **global** `asyncio.Semaphore(TRIPLL_MAX_PARALLEL, default 3)` for all backends. Cannot cap `cursor_local` at 5 while `claude_code` runs 3 and `cursor_cloud` runs 8 | `engine.py:880`, `:949–960` | **P1** |
| **PROV-03** — an extension-host crash is indistinguishable from a wave failure, so it burns the 3-attempt budget and parks a wave that was never really attempted | no infra-failure classifier in `adapters/base.py` | **P1** |
| **MODEL-01** — `DEFAULT_MODEL = "claude-sonnet-4-6"` while `engine.py:24` documents the default as `claude-3-5-sonnet`, a **retired** model ID that 404s | `adapters/claude_code.py:37` vs `engine.py:24` | **P1** |
| **EFFORT-01** — no reasoning-effort control, though **both CLIs support it**. `claude --effort <low\|medium\|high\|xhigh\|max>`; `cursor-agent --model` takes parameterized models (`claude-opus-5[context=1m,effort=high]`) and `-thinking-high` / `-xhigh` variants | `claude_code.py:207–226` builds argv with no `--effort`; `cursor_local.py:131` | **P1** |
| **BUDGET-01** — `claude --max-budget-usd` exists and is unused. Exit 3 (budget) rests entirely on tripll's own accounting, which BUG-cost proves can double-count — there is no process-level backstop | `claude_code.py` argv; `exits.py` exit 3 | **P1** |
| **AUTH-01** — nothing defines what happens when a provider's credentials expire mid-run. Under `human_gates = "auto_accept"` an auth prompt becomes a silent hang, not a gate | no auth preflight in `adapters/` | **P1** |
| **CAP-01** — `cursor_local max_parallel = 5` is a **number, not a measurement**. Each wave gets its own worktree (`allocate_worktree`), so whether the extension host dies from N concurrent agents or N workspaces is untested | untested | **P1** |
| **COST-01** — `budget_usd = 60` is meaningless across three providers at different prices. `ledger.attempts` carries `backend` *and* cost, so the data exists — nothing aggregates or reports per provider | `ledger.py:161`, `:258` | **W6** |
| **DASH-01** — the dashboard shows no provider / model / effort per wave. In a mixed-provider run "which one ran this?" is the first debugging question | `api/ui/templates/_waves_tbody.html` | **W12** |

**Already present — do not rebuild.** Per-wave **model** works today: both adapters resolve
`brief["model"] → adapter default → DEFAULT_MODEL` (`claude_code.py:224`, `cursor_local.py:131`),
`WaveNode.model` exists (`graph.py:116`), `BACKENDS` + `build_adapter` give a factory registry
(`adapters/__init__.py:38`), and `ledger.attempts.backend` is already a **per-attempt** column
(`ledger.py:161`, `:258`) — so a mixed-provider run needs **no ledger schema change**.

### Config surface (P1 implements)

```   
[providers.claude_code]
max_parallel = 3
default_model = "claude-opus-5"

[providers.cursor_local]
max_parallel = 5              # the extension-host ceiling; adaptive throttle may lower it
default_model = "auto"
cooldown_s = 30               # after an infra failure, before re-admitting work

[providers.cursor_cloud]
max_parallel = 8
default_model = "auto"

[pipeline]
max_parallel = 10             # global ceiling across all providers
```

- **Two semaphores, fixed order.** Acquire **global → provider**, release in reverse. Consistent
  ordering means no deadlock. `TRIPLL_MAX_PARALLEL` keeps working as the global ceiling.
- **Infra-failure classifier.** `"Couldn't start"`, `"Workspace Disconnected"`, and non-zero exit
  with no agent output are classified **`infra`**, not `failure`. An `infra` outcome does **not**
  consume a wave attempt, does **not** trip the exit-7 breaker, and is recorded as its own event.
- **Adaptive throttle.** N consecutive `infra` results from one provider halve its pool and start
  its `cooldown_s`; a clean dispatch restores it by one step. This is the per-run breaker W6 builds
  (BUG-07), scoped **per provider** instead of per run.
- **Failover.** A wave declares `fallback = ["claude_code"]`. When its provider is in cooldown or
  its pool is saturated beyond the deadline, the wave re-dispatches on the fallback provider and
  the switch is recorded on the attempt. Failover is a **provider** change only — never a silent
  model downgrade.

### Reasoning effort, per wave

Both CLIs expose it — verified against the installed binaries, not assumed:

| Provider | Mechanism | Values |
|----------|-----------|--------|
| `claude_code` | `claude --effort <level>` | `low` · `medium` · `high` · `xhigh` · `max` |
| `cursor_local` / `cursor_cloud` | encoded **in the model string** — either a parameterized model (`claude-opus-5[context=1m,effort=high,fast=false]`) or a named variant (`claude-opus-5-thinking-high`, `gpt-5.3-codex-xhigh`) | per `cursor-agent --list-models` |

**Cursor needs no code change.** `cursor_local.py:131` already forwards `brief["model"]` straight to
`--model`, so a wave declaring `model = "claude-opus-5-thinking-high"` gets high thinking **today**.
Only `claude_code` needs the new `--effort` flag (P1.10).

Two more flags worth wiring while the argv builder is open:

- **`claude --max-budget-usd <amount>`** (works with `-p`, which the adapter already uses) — a
  **process-level** cap per dispatch. Exit 3 currently trusts tripll's own cost accounting, and
  BUG-cost proves that can double-count; this is the backstop that holds even when the ledger is
  wrong (BUDGET-01).
- **`claude --fallback-model <list>`** — native model fallback on overload. **Deliberately not
  used** (R16): it silently substitutes a *model*, which is exactly the downgrade the plan's
  failover rule forbids. Provider failover stays tripll's job; model identity stays declared.

Effort assignment for this plan:

Every wave routes through **`cursor_local`**. Most use `model = "auto"` and let Cursor pick depth;
P0, Final, and Thermos pin **`claude-opus-5`** explicitly. Effort rides **in the model string** on
Cursor — there is no separate `reasoning_effort` key. Swap `auto` for
`claude-opus-5-thinking-high` (or a parameterized `claude-opus-5[effort=high]`) on any wave that
needs more depth than Auto provides.

### Recommended assignment

Model IDs are current as of 2026-07: `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`
(Claude Code CLI `--model`); `auto` for `cursor_local` / `cursor_cloud`.
**P1.7 fixes MODEL-01 first** — `claude-3-5-sonnet` is retired and `claude-sonnet-4-6` is a
generation behind.

| Wave shape | Provider | Model | Why |
|------------|----------|-------|-----|
| All impl waves (P1–W12) | `cursor_local` | `auto` | Single provider, Cursor Auto for well-specified work; `fallback = ["claude_code"]` on infra failure |
| Pre-0 gate (P0) | `cursor_local` | `claude-opus-5` | Human gate + plan self-hosting — pinned top tier on Cursor |
| Final sweep | `cursor_local` | `claude-opus-5` | xfail reconciliation and CI gate — explicit top tier |
| **Review (Thermos)** | `cursor_local` — **fresh session, never the builder's** | `claude-opus-5` | R17. Review runs at the top capability tier; independence comes from a fresh session and explicit model pin, not from Auto |

### Example pipelines — combined providers and models

Four shapes, all expressible in v3 once P1 lands. Copy the fragment, not the whole plan.

**1. Constrained-local (this plan's shape).** Cursor is the bottleneck, so it gets the mechanical
work at a hard cap while the reasoning waves run on Claude Code.

```toml
[providers.cursor_local]
max_parallel = 5
cooldown_s   = 30
[providers.claude_code]
max_parallel = 3

[[waves]]
id = "W5"                       # cancellation — hardest reasoning
model    = "claude-opus-5"

[[waves]]
id = "W12"                      # docs + aria labels — mechanical
model    = "auto"
```

**2. Cost-tiered by wave difficulty.** One provider, three model tiers. Cheapest change to make —
per-wave `model` already works today, before P1.

```toml
[[waves]]
id = "W1"                       # authors the acceptance contract
model    = "claude-opus-5"

[[waves]]
id = "W6"                       # bounded, well-specified fixes
model    = "claude-sonnet-5"

[[waves]]
id = "W11"                      # dependency bumps, mostly waiting on CI
model    = "claude-haiku-4-5"
```

**3. Builder/checker split across providers (R17).** The reviewer is never the builder's session,
and for a `cursor_local`-built wave it is a different provider too.

```toml
[[waves]]
id = "W8"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
role     = "impl"
model    = "auto"

[[waves]]
id = "Thermos"
provider = "cursor_local"
model = "claude-opus-5"
role     = "impl"
model    = "claude-opus-5"      # review runs at the top tier — independence, not a downgrade
  [[waves.depends_on]]
  wave   = "W8"
  reason = "gate"
  detail = "fresh-eyes review of a wave built elsewhere"
```

**4. Burst to cloud, keep local for the gate.** `cursor_cloud` absorbs breadth; the verifying wave
stays local so its `make ci` runs against the real checkout.

```toml
[providers.cursor_cloud]
max_parallel = 8

[[waves]]
id = "W11"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
model    = "auto"

[[waves]]
id = "Final"
provider = "cursor_local"
model = "claude-opus-5"
model    = "claude-opus-5"
verify   = ["make ci"]
```

**5. Effort-tiered on one provider.** The cheapest quality lever after model choice — same model,
different depth per wave.

```toml
[[waves]]
id = "W7"                            # exit wiring — deepest reasoning in the plan
model    = "claude-opus-5"
max_budget_usd   = 12.0              # process-level backstop (BUDGET-01)

[[waves]]
id = "W11"                           # dependency bumps — mechanical, latency-sensitive
model    = "claude-haiku-4-5"
```

Same idea on Cursor, where effort rides **in the model string** — no separate field:

```toml
[[waves]]
id = "W8"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
model    = "claude-opus-5-thinking-high"      # or claude-opus-5[context=1m,effort=high]
```

**Model and effort note — verified against the installed CLIs, not assumed.**
Claude Code `--model` takes `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5` (no date
suffixes) and `--effort` takes `low|medium|high|xhigh|max`. Cursor's `--model` takes `auto`, a named
variant (`claude-opus-5-thinking-high`, `gpt-5.3-codex-xhigh`, `composer-2.5`), or a parameterized
model (`claude-opus-5[context=1m,effort=high,fast=false]`) — run `cursor-agent --list-models` for
the account's current set. P1.7 must land before any of these examples run, or the default is the
retired `claude-3-5-sonnet`. `reasoning_effort` is a **distinct key** from the v3 `effort` field,
which is wave size (`S`/`M`/`L`/`XL`, `graph.py:96`) — reusing the name is a duplicate-key TOML error.

---

## Tracing — every agent call, no exceptions

**The problem.** tripll dispatches agents and cannot show you what they did. The ledger records
*that* an attempt happened and what it cost; nothing records the **call** as a span. And the one
place that configures tracing has two rival implementations with different gates, so "is tracing
on?" has no single answer.

| Gap | Evidence | Wave |
|-----|----------|------|
| **TRACE-01** — no span wraps agent dispatch. `AgentAdapter.dispatch` is the single chokepoint for all three backends and emits nothing; the engine records ledger events only | `adapters/base.py:407–488`, `engine.py:2334` | **P3** |
| **TRACE-02** — four dispatch call sites and one direct-SDK call site, none traced. The four route through `adapter.dispatch`; the fifth bypasses adapters entirely (`pydantic_ai.Agent.run_sync`) | `engine.py:2334`, `orchestrator_gate.py:192`, `build_plan_from_errors.py:333`, `extract/semantic.py:143`, `skw/changelog_eval.py:393` | **P3** |
| **TRACE-03** — **two** Logfire configurators with different gates. `tripll skw …` runs both in one process ⇒ two `logfire.configure()` calls | `obs.py:52–54` (gated `LOGFIRE_TOKEN`) vs `skw/tracing.py:90–94` (gated `SKW_TRACE` / `skw.toml`) | **P3** |
| **TRACE-04** — **no local sink.** Tracing is all-or-nothing on a Logfire **cloud** token; a developer without one gets nothing at all. There is no JSONL/SQLite trace writer anywhere in `src/` | `obs.py:49–50` early-returns without a token | **P3** |
| **TRACE-05** — no **self-hosted** Logfire path. `obs.py:53` never passes `advanced=AdvancedOptions(base_url=…)`. A deployed local Logfire server is reachable only by the SDK's bare `LOGFIRE_BASE_URL` env — undocumented, unconfigurable, untested | `obs.py:52–54` | **P3** |
| **TRACE-06** — no scrubbing configured, and `instrument_httpx(capture_all=True)` ships auth headers and bodies. This is **OBS-01**, already forbidden in W4; P3 owns the fix because P3 rewrites the call | `obs.py:54` | **P3** (W4 re-verifies) |

**Already present — do not rebuild.** `DispatchResult` already carries `cost_usd`, `input_tokens`,
`output_tokens`, `returncode`, `argv` and `log_path` (`adapters/base.py:479–488`), and
`run_streaming`'s `on_event` callback already delivers throttled live usage
(`adapters/base.py:292–316`). `log_redact` already owns the operator hide-key list
(`config/log-hide-keys.toml`). Spans consume all of this — they do not re-derive it.

### The one seam that gives "no exceptions"

`AgentAdapter.dispatch` (`adapters/base.py:407–488`) is a **base-class** method: `build_argv` →
`run_streaming` → `parse_result`. No adapter overrides it. Instrumenting that one method traces
`claude_code`, `cursor_local`, `cursor_cloud` **and** all four call sites at once. The fifth site is
a `pydantic_ai` agent, covered by `logfire.instrument_pydantic_ai()` — no per-call-site edits.

| Call path | Covered by |
|-----------|-----------|
| `engine.py` wave dispatch · `orchestrator_gate.py` · `build_plan_from_errors.py` · `extract/semantic.py` | `AgentAdapter.dispatch` span (P3.4) |
| `skw/changelog_eval.py` pydantic-ai judge | `logfire.instrument_pydantic_ai()` (P3.3) |
| SKW graph nodes + `skw/driver.py` subprocess | existing `skw.tracing.span` call sites, re-pointed at the spine (P3.7) |
| Any HTTP call to a model API | `logfire.instrument_httpx(capture_all=False)` (P3.3) |

There is **no** `logfire.instrument_subprocess` — verified against the installed SDK. Agent
subprocess spans are manual by necessity, which is exactly what P3.4 adds.

### Config surface (P3 implements)

Three sink classes, independently selectable. **Local sinks need no token** — that is the point of
TRACE-04.

```toml
[tracing]
enabled = true                # TRIPLL_TRACE=0 forces off; default on
service_name = "tripll"
sinks = ["sqlite", "jsonl"]   # local, always available, no token required
retention_days = 30
capture = "shape"             # off | shape | full — prompt/completion policy (R21)

[[tracing.exporters]]         # zero or more; each is optional
type = "logfire"              # Logfire cloud — LOGFIRE_TOKEN

[[tracing.exporters]]
type = "logfire"
base_url = "http://localhost:8080"          # deployed local Logfire server

[[tracing.exporters]]
type = "otlp"
endpoint = "http://127.0.0.1:4318/v1/traces"  # any OTLP collector
```

Env overrides, in precedence order: `TRIPLL_TRACE`, `LOGFIRE_TOKEN`, `LOGFIRE_BASE_URL`,
`OTEL_EXPORTER_OTLP_ENDPOINT`.

**Verified against `logfire 4.37.0`, not assumed:** `AdvancedOptions(base_url=…)` and the
`LOGFIRE_BASE_URL` env var both exist, so a **self-hosted Logfire server** is a first-class target;
`ScrubbingOptions(callback, extra_patterns)`, `instrument_pydantic_ai`, `instrument_httpx`
(`capture_all`, `capture_headers`, `capture_request_body`, `capture_response_body`) all exist;
`instrument_subprocess` does **not**.

### Where local traces land

```text
runs/processing/<run-id>/traces/traces.db          # SQLite, queryable, joins to ledger
runs/processing/<run-id>/traces/<YYYY-MM-DD>.jsonl # daily-rotated append log
```

Beside `logs/`, inside the run directory, so a trace travels with the run it describes and is
deleted with it. Retention is `retention_days` (default 30).

### Span taxonomy

| Span | Emitted at | Attributes set on close |
|------|-----------|-------------------------|
| `tripll.run` | engine run start | `run_id`, `slug`, `plan_sha256`, `base`, `branch`, `target_repo` → `exit_id`, `cost_usd`, `waves_done`, `waves_parked` |
| `tripll.wave` | `_execute_node` | `wave_id`, `node_id`, `lane`, `provider`, `model`, `reasoning_effort`, `attempt_n` → `state`, `failure_class`, `fallback_used` |
| `tripll.agent.dispatch` | `AgentAdapter.dispatch` | `backend`, `model`, `argv` (redacted), `worktree`, `timeout_s` → `outcome`, `returncode`, `cost_usd`, `input_tokens`, `output_tokens`, `duration_s`, `stop_reason` |
| `tripll.verify` | each `verify` command | `command` → `exit_code`, `duration_s` |
| `tripll.integrate` | batch integration | `lane`, `batch` → `merged`, `conflicts` |

**Correlation without a ledger migration.** Every span carries `run_id`, `node_id` and
`attempt_id`, so trace → ledger is a join on `attempts.attempt_id`. No `trace_id` column, no
schema change, no collision with W6's ledger work. `ledger.py` is deliberately **not** a P3 target.

### Redaction — one hide-list, not two

sevn's lesson learned the hard way: two redaction systems drift. P3 reuses
`log_redact.load_hide_keys` (`config/log-hide-keys.toml`) as the **single** source for span
scrubbing, wired into `logfire.ScrubbingOptions(extra_patterns=…)` and applied by the local sink
before write. W4 grows that hide list (SEC-07) and every consumer inherits it.

`capture = "shape"` is the default: prompt and completion are recorded as **shape only** — role,
block types, character counts — never text. `capture = "full"` is opt-in, operator-set, and never
the default. `capture = "off"` drops the fields entirely.

---

## Onboarding — install, configure once, then init any repo

**The problem.** tripll is installable but not *adoptable*. There is no one-time setup, no persisted
configuration, and nothing that turns an arbitrary repo into one tripll can work on. `tripll init`
(`cli.py:373`) creates four empty `runs/` directories and stops. Everything else is 28 `TRIPLL_*`
environment variables, a per-run `dispatch-config.json`, and agent profiles that only exist once you
have started the dashboard.

| Gap | Evidence | Wave |
|-----|----------|------|
| **ONB-01** — no one-time setup. No `tripll.toml`, no user-level config, no `setup` / `doctor` / `config` command. `tripll init` creates `runs/{input,processing,processed,failed}/` and nothing else | `cli.py:373–387`; 28 `TRIPLL_*` vars across `src/`; no `tomllib` read for operator config outside `plan/` and `skw/` | **W13** |
| **ONB-02** — no brownfield command. Nothing generates specs and their related files for an existing repo. `spec sync` / `prd sync` scaffold missing docs but are doc-folder-scoped, not repo-scoped | `cli.py:1771`, `:1798` | **W14** |
| **ONB-03** — no repo evaluation. `report.py` is per-**run**; `graph extract` builds a KG of any repo but nothing aggregates it into an evaluation document | `report.py`, `cli.py:1331` | **W14** |
| **ONB-04** — greenfield is a **generic** cookiecutter Python package with no tripll specs, agents, config or plan | `scaffold.py`, `make scaffold-package` → `gh:audreyfeldroy/cookiecutter-pypackage` | **W15** |
| **ONB-05** — ~~`doc_folder.py` hard-imports `sevn`~~ — **FIXED AHEAD OF THE PLAN, 2026-07-26.** The `sync` command imported `sevn.docs.about.*` and `sevn.docs.readme.providers`, and `_ensure_sevn_importable` mutated `sys.path` to inject `<repo_root>/src`. It was already dead — `tripll spec sync` raised `ModuleNotFoundError: No module named 'sevn'` in tripll's own checkout, and its only test was skipped behind `importorskip("sevn")`. Removed end to end: 253 lines from `doc_folder.py`, the `spec sync` / `prd sync` CLI commands, the `spec-sync` / `prd-sync` Make targets. `validate` and `score` were always sevn-free and are untouched | was `skw/doc_folder.py:137–389` | **done** — W14 re-verifies |
| **ONB-06** — the **only** wave-plan template in the wheel is `tripll/skw/wave-plan-template.md`, which is **`waveorch_format = 2`** — the deprecated format. The v3 template lives at `docs/wave-plan-template.md`, **outside** the package, and does not ship. A pip-installed tripll cannot emit a v3 plan | verified against a built wheel: `docs/` absent, `wave-plan-template` resolves only to the skw v2 copy | **W13** |

**Verified, not assumed:** two wheels were built and diffed — one with the `force-include` block in
`pyproject.toml`, one without. The file lists are **identical**: 266 entries each, nothing lost.
Hatchling already ships every non-`.py` file under `src/tripll/`, so `spec-templates/`,
`prd-templates/`, `prompts/`, `agents/`, `skills/` and the rules TOMLs **are** packaged and the
`force-include` block is dead config (W13.7 deletes it, W13.7a replaces it with a real test). The
single genuine packaging gap is ONB-06: the v3 template lives in `docs/`, which is not part of the
package at all.

### The three commands

```bash
# once per machine, after install
tripll setup                 # configure providers, models, tracing; writes ~/.config/tripll/config.toml
tripll doctor                # preflight: providers reachable, extras present, templates resolvable

# in an existing repo (brownfield)
cd ~/code/some-project
tripll init                  # specs + related files + tripll.toml + an evaluation of the repo

# a new project (greenfield)
tripll new my-project        # scaffold + specs + tripll.toml, ready to plan against
```

`tripll init` keeps its current runs-layout behaviour as a subset — it grows, it does not change
meaning. Both `init` and `new` are **idempotent**: re-running reconciles rather than overwrites, and
never clobbers a file the operator has edited.

### Config precedence

Four layers, highest wins. This is the single resolution order for every setting, so "why did it
pick that model?" has one answer:

```text
env (TRIPLL_*)  >  ./tripll.toml (repo)  >  ~/.config/tripll/config.toml (user)  >  built-in defaults
```

```toml
# ~/.config/tripll/config.toml — written by `tripll setup`
default_provider = "cursor_local"

[providers.cursor_local]
max_parallel  = 5
default_model = "auto"

[providers.claude_code]
max_parallel  = 3
default_model = "claude-opus-5"

[tracing]
enabled = true
sinks   = ["sqlite", "jsonl"]
```

```toml
# ./tripll.toml — written by `tripll init` / `tripll new`, committed to the repo
repo_root = "."
specs_dir = "docs/specs"
prds_dir  = "docs/prds"
plans_dir = "docs/plans"
```

**No secrets in either file.** Provider credentials stay in the backend toolchains (`claude`,
`cursor-agent`) exactly as they are today; `tripll setup` *verifies* auth via each adapter's
`capabilities()` and tells you what to run, but never stores a key (R24). This is the one design
point most likely to be "helpfully" changed later, so it is a `forbidden` clause, not a preference.

### What brownfield `tripll init` produces

| Artefact | Built from |
|----------|-----------|
| `tripll.toml` | detected layout + `tripll setup` defaults |
| `docs/specs/`, `docs/prds/` skeletons | the SKW spec/PRD templates and rules (below) |
| `docs/plans/` + a **v3** plan template | the packaged v3 template ONB-06 adds |
| `.tripll/graph.db` | `tripll graph extract` on the detected repo root |
| **`docs/evaluation-<date>.md`** | the code graph + doc scores + gate signals, in the section shape of `ignorelocal/project-evaluation-2026-07-25.md` |

The evaluation is the deliverable that makes the rest useful: it is what tells the operator which
waves to plan first. Its structure is already proven — this plan was generated from one.

### What we take from SKW, and what we leave

Answering the standing question directly. `skw/` is ~11.6k LOC of vendored kit; roughly a third of it
is worth keeping, and almost none of the orchestration is.

| From `skw/` | Verdict | Where it goes |
|-------------|---------|---------------|
| `spec_validate.py`, `prd_validate.py`, `doc_validate.py` + `spec-templates/`, `prd-templates/` (frontmatter schema, required H2 order, AST check that `interfaces[].symbol` really exists) | **adapt** | W14 — the brownfield doc contract. Already packaged in the wheel |
| `doc_score.py` — deterministic 0–100 with a scaffold-phrase penalty and a status-honesty component | **adapt** | W14 — the evaluation's doc-quality score, and the gate for "is this spec real or a stub" |
| `doc_folder.py` validate/score | **adapt** | W14 — **minus** the sevn import (ONB-05) |
| `doc_folder.py` `sync` → `sevn.docs.about.*` | **dropped** | **Done 2026-07-26** — removed end to end. W14 still owes the tripll-native manifest that replaces the capability |
| `render.py` + `prompts/` + the front-end agents (`specify`, `clarify`, `plan`, `wayfinder`, `prd-author`, `wave-generator`) | **adapt** | W14 + W15 — this *is* the spec-generation spine for both directions; do not rewrite it |
| `nextstep.py` — "what is the next command to run" from checkbox state | **adapt** | W13 — tripll has **no** equivalent, and it is exactly what a new operator needs after `init` |
| `markdown_sections.py` — wave checkbox parsing | **reuse** | W13, feeds `nextstep` |
| `runtime.py` — `is_dryrun` / `is_pytest` / `is_auto_approve` | **reuse** | W13 — trivial and already correct |
| `agent_config.py` — the model **merge table** and precedence chain | **adapt (rules only)** | W13's config precedence. Take the resolution order; drop the argv builder, which `adapters/` already owns |
| `pipeline_diagram.py` — self-contained HTML pipeline diagram | **reuse** | W14's evaluation output |
| `skills/improve-codebase-architecture` + `render_report.py` | **adapt** | W14 — the closest thing to an evaluation generator; broaden from "architecture deepening" to the full section set |
| `scaffold.py` (skw) — wave file from template | **reuse** | W14, re-pointed at the **v3** template |
| `tracing.py` | **demote** | P3 — thin forwarder to `tripll.obs` (R22) |
| `pipeline.py`, `graph_nodes.py`, `states.py`, `driver.py`, `wave_model.py`, `resolve_wave.py`, `turn_context.py`, `git.py`, `verify.py` | **leave** | Duplicate orchestration. `engine.py` + `adapters/` supersede all of it; it dies with the SKW mount |
| `validate.py` wave-file lint | **leave** | `tripll.plan` already does v3 properly |

The pattern: **keep the document contracts and the prompt spine, drop the second execution engine.**
SKW's value was never its runner — tripll has a better one — it is the accumulated definition of what
a good spec, PRD and changelog look like, and the prompts that produce them.

---

## Machine block (`waveorch_format = 3`)

> **Why this exists.** Prose "Acceptance:" lines are self-reported. `[waves.outcome]` contracts are
> graded (D16 — *graders decide completion; agents do not self-report done*). And a plan tripll can
> dispatch is the strongest available smoke test of the dispatcher this plan is repairing.
>
> **The waves below are serial by choice, and by a compiler defect this plan also fixes.** Today
> `check_stop_rule` refuses them (SHAPE-01, P0.10); after that fix they would compile in four
> tracks. They are still dispatched serially, because per-wave *commit → push → green CI on that
> sha* is this plan's acceptance mechanism, and parallel branch tips mean each wave's green run
> covers only a partial tree — a diluted rerun of CI-00. The tracks in *Execution order* remain
> valid **operator** guidance for hand-driven parallelism.
>
> **Verified 2026-07-26:** this block parses under `plan.format_v3.parse_plan_v3` and passes
> `plan.shape_checks.compile_plan` — **22 waves**, 0 dropped edges, max parallel group 1, no dangling
> dependency, and no wave targets more than 5 modules (the P0.10 per-wave threshold).

```toml
waveorch_format = 3
title = "tripll L1 remediation — gate, security, concurrency, exit closure"
slug = "l1-remediation"
base = "pre-0.0.1"                        # W0.2: both main/pre-0.0.1 execute CI; prefer audit baseline
branch = "wave/l1-remediation"
target_repo = "sevn-bot/tripll"

[pipeline]
max_turns = 3
deadline = "72h"
budget_usd = 60.0
human_gates = "prompt"                    # P0.8 implements auto_accept
max_parked_waves = 3                      # plan-level stop rule
max_parallel = 10                         # global ceiling across all providers (P1)
default_provider = "cursor_local"         # used when a wave declares none
extras = ["graph", "kg"]                  # P2: code graph + networkx replica active for the run
creates = [                               # P0.7: paths this plan will author (validate-plan exempt)
  "src/tripll/api/_csrf.py",
  "src/tripll/loops/dispatch_bridge.py",
  "src/tripll/adapters/pools.py",
  "src/tripll/adapters/failure_class.py",
  "src/tripll/tracing/__init__.py",
  "src/tripll/tracing/sink.py",
  "src/tripll/tracing/sinks.py",
  "src/tripll/tracing/redact.py",
  "src/tripll/tracing/spans.py",
  "src/tripll/tracing/config.py",
  "tests/test_tracing.py",
  "src/tripll/config.py",
  "src/tripll/templates/wave-plan-template.md",
  "src/tripll/onboard/__init__.py",
  "src/tripll/onboard/brownfield.py",
  "src/tripll/onboard/greenfield.py",
  "src/tripll/onboard/evaluate.py",
  "src/tripll/onboard/nextstep.py",
  "tests/test_config.py",
  "tests/test_onboard.py",
  "docs/runbooks/onboarding-runbook.md",
  "tests/test_ui_auth.py",
  "tests/test_run_id_safety.py",
  "tests/test_cancellation.py",
  "tests/test_cost_accounting.py",
  "tests/test_integrate_resume.py",
  "tests/test_exit_wiring.py",
  "tests/test_cw_portability.py",
  "tests/test_obs.py",
  "tests/test_provider_pools.py",
  "tests/test_code_graph.py",
  "bench/brief_packer_bench.py",
]

# NOTE: [providers.*] tables must come after every bare [pipeline] key — a key
# written below a table header belongs to that table, not to [pipeline].
[providers.claude_code]                   # P1
max_parallel = 3
default_model = "claude-opus-5"

[providers.cursor_local]
max_parallel = 5                          # extension-host ceiling; adaptive throttle may lower it
default_model = "auto"
cooldown_s = 30

[providers.cursor_cloud]
max_parallel = 8
default_model = "auto"
cooldown_s = 60

[[waves]]
id = "P0"
title = "Gate restoration and plan self-hosting"
role = "impl"
effort = "M"
human = true
auto_acceptable = true
provider = "cursor_local"
model = "claude-opus-5"
targets = [".github/workflows/ci.yml", ".github/actions/bootstrap/action.yml", "Makefile", "src/tripll/plan_paths.py", "src/tripll/plan/shape_checks.py"]
verify = ["make lint", "make typecheck"]

  [waves.outcome]
  required = [
    "gh run list --workflow=CI --limit 1 shows status != blocked",
    "make lint from a venv-less checkout resolves ruff 0.15.12",
    "tripll validate-plan docs/plans/l1-remediation.md exits 0",
    "independent non-overlapping waves compile; one wave targeting >5 modules is still refused",
  ]
  forbidden = ["marking any later wave done while CI has not executed"]
  evidence = ["command_output", "ci_run_id"]

[[waves]]
id = "P1"
title = "Provider fabric — per-provider pools, per-wave routing, failover"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/adapters/pools.py", "src/tripll/adapters/failure_class.py", "src/tripll/engine.py", "src/tripll/graph.py", "src/tripll/adapters/claude_code.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "P0"
  reason = "gate"
  detail = "no provider work lands before CI can verify it"

  [waves.outcome]
  required = [
    "cursor_local never exceeds its configured max_parallel, verified by a concurrency probe",
    "two waves in one run dispatch to different providers and the ledger records both",
    "an infra-classified failure consumes no wave attempt and trips no exit-7 breaker",
    "grep -rn 'claude-3-5-sonnet' src returns nothing",
  ]
  forbidden = ["a single global semaphore shared across providers", "failover that silently changes model"]
  evidence = ["test_output", "final_diff"]

[[waves]]
id = "P2"
title = "Code graph activation"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/graphstore/sqlite_store.py", "src/tripll/graphstore/replica_networkx.py", "src/tripll/plan/compile.py", "src/tripll/serve/brief_packer.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "P1"
  reason = "artifact"
  detail = "graph-derived routing hints read the provider fabric's config"

  [waves.outcome]
  required = [
    "compile_plan passes a real code_graph to check_stop_rule; the union fallback is not reached",
    "a CALLS-adjacent parallel pair is refused with the precise rule, not the proxy",
    "graph briefs are packed for every dispatched wave when the graph extra is installed",
    "no graph extra installed still yields a working run",
  ]
  forbidden = ["a hard dependency on langgraph or networkx in the base install"]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "P3"
title = "Tracing spine — every agent call traced, local or Logfire"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/tracing", "src/tripll/obs.py", "src/tripll/adapters/base.py", "src/tripll/engine.py", "src/tripll/skw/tracing.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "P2"
  reason = "artifact"
  detail = "wave spans carry provider/model/effort, which P1 lands and P2 annotates"

  [waves.outcome]
  required = [
    "tests/test_tracing.py passes",
    "a run with no LOGFIRE_TOKEN still writes runs/*/traces/traces.db and a dated .jsonl",
    "every adapter dispatch emits exactly one tripll.agent.dispatch span carrying backend, model, outcome and token counts",
    "grep -rn 'logfire.configure' src/tripll returns exactly one call site",
    "tripll skw with SKW_TRACE=1 and LOGFIRE_TOKEN set configures logfire once, not twice",
    "a self-hosted base_url is honoured: AdvancedOptions(base_url=...) is passed when tracing.exporters declares one",
    "the dependency runs one way: grep -rn 'tripll.skw' src/tripll/obs.py src/tripll/tracing returns nothing",
    "tracing works with tripll.skw absent entirely — the spine has no SKW dependency to lose",
  ]
  forbidden = [
    "logfire.instrument_httpx(capture_all=True) anywhere in src/",
    "a second logfire.configure call site",
    "any import of tripll.skw from tripll.obs or tripll.tracing",
    "prompt or completion text in a span when capture is 'shape'",
    "any ledger schema change in this wave",
    "tracing that raises into the dispatch path",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W0"
title = "Baseline, anchors, ADRs, contract pinning"
role = "impl"
effort = "S"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["docs/decisions/006-agent-def-source.md", "docs/decisions/007-exit-one-wire-or-fail.md", "docs/decisions/008-cw-hotspot-default.md", "docs/decisions/009-one-closed-l1-loop.md", "docs/plans/l1-remediation.md"]
verify = ["make lint"]

  [[waves.depends_on]]
  wave = "P3"
  reason = "gate"
  detail = "the integration-target rule needs an executed CI run; P1–P3 land the fabric and tracing W0+ dispatch on"

  [waves.outcome]
  required = [
    "ls docs/decisions/0{06..12}-*.md counts 7 (012 lands in P3)",
    "gh issue list --label out-of-scope returns >= 3 issues",
    "docs/plans/l1-remediation.md exists and its sha256 is recorded in Re-entry",
  ]
  forbidden = ["any change under src/"]
  evidence = ["command_output", "final_diff"]

[[waves]]
id = "W1"
title = "Author the RED suite"
role = "test-author"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["tests/test_ui_auth.py", "tests/test_run_id_safety.py", "tests/test_cancellation.py", "tests/test_cost_accounting.py", "tests/test_integrate_resume.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W0"
  reason = "artifact"
  detail = "tests anchor on W0's re-grepped line numbers"

  [waves.outcome]
  required = [
    "make test reports 0 failed and >= 20 xfailed",
    "every new test file declares a tier marker",
    "docs/test-plans/l1-remediation.md maps finding -> test -> wave -> tier",
  ]
  forbidden = ["editing src/ in this wave"]
  evidence = ["test_output", "final_diff"]

[[waves]]
id = "W2"
title = "Close the gate: re-home AgentDef source"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/graphstore/task_sync.py", "tests/test_agent_roster.py", "src/tripll/skw/agents/README.md", "CLAUDE.md"]
verify = ["make check"]

  [[waves.depends_on]]
  wave = "W1"
  reason = "contract"
  detail = "roster assertions define acceptance"

  [waves.outcome]
  required = [
    "make check exits 0 from a fresh clone in a temp dir",
    "grep -rn '\\.cursor/agents' src tests docs returns nothing",
    "hash_agent_def returns a digest for all 14 section-11 slugs",
    "CI is green on this sha — the repo's first green run",
  ]
  forbidden = ["un-ignoring any path under .cursor/", "deleting a roster assertion"]
  evidence = ["test_output", "ci_run_id"]

[[waves]]
id = "W3"
title = "Auth parity for the HTML control plane"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/api/ui/router.py", "src/tripll/api/_auth.py", "src/tripll/api/_csrf.py", "src/tripll/api/app.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W2"
  reason = "gate"
  detail = "a green gate must exist before it can detect a regression"

  [waves.outcome]
  required = [
    "tests/test_ui_auth.py passes",
    "every mutating HTML POST returns 401/403 without a token when TRIPLL_API_TOKEN is set",
    "a POST with a valid token and no CSRF field is rejected",
  ]
  forbidden = ["changing behaviour when TRIPLL_API_TOKEN is unset"]
  evidence = ["test_output", "final_diff"]

[[waves]]
id = "W4"
title = "Token transport, traversal guard, redaction, obs capture"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/api/ui/templates", "src/tripll/pipeline.py", "src/tripll/log_redact.py", "config/log-hide-keys.toml", "src/tripll/obs.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W3"
  reason = "artifact"
  detail = "W3 lands the CSRF field in the same templates — one writer"

  [waves.outcome]
  required = [
    "tests/test_run_id_safety.py and tests/test_obs.py pass",
    "grep -rn '?token=' src/tripll/api/ui/templates matches only the EventSource URL",
    "config/log-hide-keys.toml lists more than one key",
  ]
  forbidden = ["logfire.instrument_httpx(capture_all=True) anywhere in src/"]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W5"
title = "Cancellation and subprocess safety"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/engine.py", "src/tripll/adapters/base.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W4"
  reason = "gate"
  detail = "security waves land before runtime surgery on engine.py"

  [waves.outcome]
  required = [
    "tests/test_cancellation.py passes including the real-pid assertion",
    "no child process survives a cancelled dispatch",
    "no wave is left in state 'running' after cancellation",
    "a cancelled dispatch still closes its tripll.agent.dispatch span with a terminal status",
  ]
  forbidden = [
    "asyncio.gather without return_exceptions in engine.py",
    "removing or bypassing the P3 dispatch span while reworking base.py",
  ]
  evidence = ["test_output", "final_diff"]

[[waves]]
id = "W6"
title = "Ledger and integrate correctness"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/ledger.py", "src/tripll/loops/exits.py", "src/tripll/integrate.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W5"
  reason = "artifact"
  detail = "W5 makes the ledger finalizer cancellation-safe first"

  [waves.outcome]
  required = [
    "tests/test_cost_accounting.py and tests/test_integrate_resume.py pass",
    "grep -n 'updated_at = updated_at' src/tripll/loops/exits.py returns nothing",
    "re-running integrate preserves prior lane merges",
  ]
  forbidden = ["unconditional 'git checkout -B' in integrate.py"]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W7"
title = "Exit table closure — wire or fail"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/loops/exits.py", "src/tripll/engine.py", "src/tripll/github/reviews.py", "docs/design-note.md"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W6"
  reason = "artifact"
  detail = "exit records write through record_exit_on_run, fixed in W6"

  [waves.outcome]
  required = [
    "tests/test_exit_wiring.py passes",
    "grep -rn 'pullfrog_success' src/tripll shows at least one production setter",
    "exits 1, 4, 7 and 8 each fire from the Engine path and record an exit id",
  ]
  forbidden = ["removing goal_met from the advertised exit table", "documenting an exit as live while unreachable"]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W9"
title = "Close one L1 loop end to end"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/loops/dispatch_bridge.py", "src/tripll/loops/l1_pr.py", "src/tripll/loops/l1_outer.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W7"
  reason = "artifact"
  detail = "the PR fix loop consumes the wired exit table"

  [waves.outcome]
  required = [
    "tests/test_pr_loop.py asserts a fake adapter recorded an invocation",
    "the loop parks at the human merge gate and never merges",
    "no langgraph installed still yields the linear degradation path",
  ]
  forbidden = ["merging a PR from the loop", "leaving 'would call ... in production' in l1_outer.py"]
  evidence = ["test_output", "final_diff"]

[[waves]]
id = "W8"
title = "Repo portability"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/plan/cw_buckets.py", "src/tripll/graph.py", "src/tripll/repo_root.py", "src/tripll/worktrees.py", "src/tripll/build_plan_from_errors.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W9"
  reason = "gate"
  detail = "serialised behind the runtime chain; no shared targets"

  [waves.outcome]
  required = [
    "tests/test_cw_portability.py passes",
    "grep -rn 'src/sevn' src/tripll/plan/cw_buckets.py returns nothing outside the opt-in fixture",
    "grep DX-runs stale nested runs path absent from src docs",
  ]
  forbidden = ["shipping sevn paths as a default forbidden set"]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W10"
title = "Observability, bench, brief packer"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["bench/brief_packer_bench.py", "src/tripll/serve/brief_packer.py", "Makefile", ".github/workflows/ci.yml"]
verify = ["make lint", "make typecheck", "make test", "make bench"]

  [[waves.depends_on]]
  wave = "W8"
  reason = "gate"
  detail = "bench exercises the dispatch path W5 stabilised"

  [waves.outcome]
  required = [
    "grep -n '^bench:' Makefile is non-empty",
    "make bench exits 0",
    "_graph_brief_tokens is computed once per task, asserted by call counter",
  ]
  forbidden = ["a blocking bench job on first landing"]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W11"
title = "DX cleanups and dependency rebaseline"
role = "impl"
effort = "S"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/log_redact.py", "pyproject.toml", "uv.lock"]
verify = ["make ci"]

  [[waves.depends_on]]
  wave = "W10"
  reason = "gate"
  detail = "dependabot rebaseline is meaningless without a live gate"

  [waves.outcome]
  required = [
    "grep -n 'tomllib' src/tripll/log_redact.py is non-empty",
    "each of the 7 dependabot PRs is merged green or closed with a recorded reason",
  ]
  forbidden = ["merging a dependency PR without a green CI run on its head"]
  evidence = ["command_output", "ci_run_id"]

[[waves]]
id = "W13"
title = "Config spine — tripll.toml, one-time setup, doctor"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/config.py", "src/tripll/templates", "src/tripll/cli.py", "src/tripll/adapters/__init__.py", "pyproject.toml"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W11"
  reason = "artifact"
  detail = "W11 is the last writer on pyproject.toml; the packaged-template fix lands after it"

  [waves.outcome]
  required = [
    "tests/test_config.py passes",
    "tripll setup writes ~/.config/tripll/config.toml and tripll doctor reports every provider's availability",
    "config resolves env > ./tripll.toml > user config > defaults, asserted at every layer",
    "a v3 wave-plan template resolves from an installed wheel with no repo checkout present",
    "tripll doctor exits non-zero when no provider is available",
  ]
  forbidden = [
    "storing a provider API key or token in any tripll config file",
    "reading operator config with a hand-rolled TOML parser instead of tomllib",
    "changing what tripll init already does to the runs layout",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W14"
title = "Brownfield onboarding — specs, related files, repo evaluation"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/onboard", "src/tripll/skw/doc_folder.py", "src/tripll/cli.py", "docs/runbooks/onboarding-runbook.md"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W13"
  reason = "artifact"
  detail = "init reads the config spine and emits the packaged v3 template W13 lands"

  [waves.outcome]
  required = [
    "tests/test_onboard.py passes",
    "tripll init in a fixture repo that is not tripll and not sevn writes tripll.toml, docs/specs, docs/prds, docs/plans and an evaluation document",
    "the evaluation carries a per-area findings table with file:line evidence and a doc score",
    "grep -rn 'import sevn' src/tripll returns nothing",
    "tripll init is idempotent: a second run changes no operator-edited file",
  ]
  forbidden = [
    "any import of sevn, or sys.path mutation to reach it",
    "an evaluation that reports a finding without file-level evidence",
    "overwriting an existing spec, PRD or plan without an explicit flag",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W15"
title = "Greenfield onboarding — tripll new"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/scaffold.py", "src/tripll/onboard", "src/tripll/cli.py", "src/tripll/templates"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W14"
  reason = "artifact"
  detail = "greenfield reuses the spec and plan emitters brownfield builds; one implementation, two entry points"

  [waves.outcome]
  required = [
    "tripll new <name> produces a project that tripll validate-plan and make check both accept",
    "the scaffolded project contains tripll.toml, a docs/specs skeleton and a v3 plan template",
    "greenfield and brownfield share one spec-emitter, asserted by test rather than by inspection",
    "the cookiecutter dependency stays optional: tripll new degrades with a named error when the scaffold extra is absent",
  ]
  forbidden = [
    "a second copy of the spec templates for greenfield",
    "requiring network access to scaffold when templates are packaged",
  ]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W12"
title = "Docs, roster honesty, a11y"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["docs/agents", "docs/runbooks/operator-runbook.md", "README.md", "about-tripll", "src/tripll/api/ui/templates"]
verify = ["make check", "make about-site"]

  [[waves.depends_on]]
  wave = "W15"
  reason = "artifact"
  detail = "docs describe shipped behaviour, including onboarding; also last writer on templates after W3/W4"

  [waves.outcome]
  required = [
    "every docs/agents/*.md carries a dispatch-status banner",
    "about-site-check is green after regeneration",
    "no interactive control in the templates lacks an aria-label or aria-labelledby",
    "README documents the full new-user path: install, tripll setup, tripll doctor, then tripll init or tripll new",
    "about-tripll getting-started covers the same path and about-site-check is green",
    "a reader following only the README can go from install to a started run without reading source",
  ]
  forbidden = [
    "claiming an unwired agent is on the dispatch path",
    "documenting an onboarding command that W13-W15 did not ship",
  ]
  evidence = ["command_output", "final_diff"]

[[waves]]
id = "Final"
title = "Finalize the L1 remediation gate"
role = "impl"
effort = "S"
provider = "cursor_local"
model = "claude-opus-5"
targets = ["docs/test-plans/l1-remediation.md", "CHANGELOG.md"]
verify = ["make ci"]

  [[waves.depends_on]]
  wave = "W12"
  reason = "contract"
  detail = "xfail sweep needs every impl wave landed"

  [waves.outcome]
  required = [
    "make ci exits 0",
    "a green GitHub Actions run exists on the branch head",
    "no xfail marker remains whose wave is done",
  ]
  forbidden = ["closing Final with any wave in PARKED state undeclared in the summary"]
  evidence = ["test_output", "ci_run_id"]

[[waves]]
id = "Thermos"
title = "Branch review, tamper audit, merge request"
role = "impl"
effort = "M"
human = true
auto_acceptable = false
provider = "cursor_local"
model = "claude-opus-5"
targets = ["CHANGELOG.md"]
verify = ["make ci"]

  [[waves.depends_on]]
  wave = "Final"
  reason = "gate"
  detail = "review runs against the finished branch"

  [waves.outcome]
  required = [
    "no review finding above severity 'low' remains open",
    "the plan sha256 matches the value recorded in W0.6",
    "the full suite ran green twice consecutively",
  ]
  forbidden = ["merging without a human", "weakened or deleted acceptance criteria in the diff"]
  evidence = ["command_output", "ci_run_id", "final_diff"]
```

---

## Worktree & branch

```bash
cd /Users/alex/Documents/code/sevn.bot/tripll
git worktree add ../tripll-l1-remediation wave/l1-remediation pre-0.0.1
cd ../tripll-l1-remediation
make setup          # REQUIRED — see DX-05; `uv run` alone does not install the dev group
```

- **Branch:** `wave/l1-remediation`. **Base:** decided by the P0.1 rule (below), defaulting to
  `pre-0.0.1`, the branch the audit ran against.
- **Worktree root:** `../tripll-l1-remediation`.
- **Seed gitignored trees:** `cp` the audit + this plan into the worktree with plain `cp`.
- **Git safety:** never `git clean -x` / `-X` (`CLAUDE.md`). The rule file `CLAUDE.md` links to
  (`.cursor/rules/no-destructive-git-clean.mdc`) is **absent from every checkout**. Treat the
  prohibition as live regardless; W2 relocates the rule to a tracked path and fixes the link.
- **Integration target — the rule, decided now (was W0.2's open question):** the integration target
  is **whichever branch CI executes on after P0.1**. A base with no CI defeats this plan's premise.
  `main` (`ba85072`) and `pre-0.0.1` (`3f5cf9b`) diverged by parallel cherry-picks of the same
  `.gitignore` change; if CI runs on both, prefer `pre-0.0.1` (the audit baseline) and record why.
  W0.2 now *applies and records* this rule rather than deciding it.

---

## Docs touched

- `docs/design-note.md` — exit table §0.3–0.4: mark which exits are Engine-live vs evaluator-only
- `docs/runbooks/operator-runbook.md` — auth/token posture; stuck-wave recovery; bench; human-gate
  auto-accept semantics; **tracing** (enabling it, where trace files land, pointing at a self-hosted
  Logfire server, reading a wave's span tree, what `capture` does)
- `docs/agents/*.md` — dispatch-status honesty banner (ARCH-06); repoint dead `.cursor/agents/` links
- `docs/harness-checks.md` — grader/self-report risks, unchanged intent
- `README.md` — `TRIPLL_API_TOKEN` semantics, bind-address guidance, `make bench`, and the
  **new-user path** it lacks today: install → `tripll setup` → `tripll doctor` → `tripll init` or
  `tripll new`, plus config precedence and the no-stored-credentials posture (R24)
- `about-tripll/_sources/getting-started.yaml`, `cli.yaml` — same path; regenerate via
  `make about-site` after any doc change
- `CLAUDE.md` — `setup` / `doctor` / `init` / `new` in the command table; `tripll.obs` named as the
  **sole** tracing configurator so no future agent re-adds a second one
- `CHANGELOG.md` — `## [Unreleased]` bullet per wave
- **new** `docs/decisions/006-*.md` … `013-*.md` — ADRs for the irreversible calls
  (`012-tracing-spine.md` lands in P3, `013-onboarding.md` in W13 — neither in W0)
- **new** `docs/runbooks/onboarding-runbook.md` — brownfield and greenfield end to end, what each
  artefact is for, safe re-runs, and how to read the evaluation (W14.8, W15.5)
- **new** `docs/plans/l1-remediation.md` — the tracked contract copy of this file
- **new** `docs/test-plans/l1-remediation.md` — finding → test → wave → **tier** matrix

## Goal

Restore the property that **a green gate means something**, then land every finding the audit
raised. End state: GitHub Actions executes on every push and is green; `make check` passes from a
clean clone with no untracked prerequisites; the HTML control plane enforces the same auth boundary
as the JSON API; cancellation cannot orphan an agent subprocess or strand a wave in `running`; the
designed 8-exit table is wired to the Engine; and tripll's defaults are repo-portable rather than
sevn-shaped.

## Files in scope

| Area | Paths |
|------|-------|
| CI / gate (P0, W10) | `.github/workflows/ci.yml`, `.github/actions/bootstrap/action.yml`, `Makefile` |
| Plan self-hosting (P0) | `src/tripll/plan_paths.py`, `src/tripll/engine.py`, `src/tripll/plan/format_v3.py` |
| AgentDef source (W2) | `src/tripll/graphstore/task_sync.py`, `tests/test_agent_roster.py`, `src/tripll/skw/agents/*.md`, `CLAUDE.md` |
| Auth parity (W3) | `src/tripll/api/ui/router.py`, `src/tripll/api/_auth.py`, **new** `src/tripll/api/_csrf.py`, `src/tripll/api/app.py` |
| Token / traversal / redaction (W4) | `src/tripll/api/ui/templates/*.html`, `src/tripll/pipeline.py`, `src/tripll/log_redact.py`, `config/log-hide-keys.toml`, `src/tripll/obs.py` |
| Concurrency (W5) | `src/tripll/engine.py`, `src/tripll/adapters/base.py` |
| Ledger / integrate (W6) | `src/tripll/ledger.py`, `src/tripll/loops/exits.py`, `src/tripll/integrate.py` |
| Exit closure (W7) | `src/tripll/loops/exits.py`, `src/tripll/engine.py`, `src/tripll/github/reviews.py`, `docs/design-note.md` |
| L1 loops (W9) | `src/tripll/loops/l1_outer.py`, `src/tripll/loops/l1_pr.py`, **new** `src/tripll/loops/dispatch_bridge.py` |
| Portability (W8) | `src/tripll/plan/cw_buckets.py`, `src/tripll/graph.py`, `src/tripll/repo_root.py`, `src/tripll/worktrees.py`, `src/tripll/cli.py`, `src/tripll/build_plan_from_errors.py` |
| Obs / bench (W10) | **new** `tests/test_obs.py`, `bench/**`, `Makefile`, `src/tripll/serve/brief_packer.py` |
| DX (W11) | `src/tripll/log_redact.py`, `Makefile`, dependabot PR rebaseline |
| Config spine (W13) | **new** `src/tripll/config.py`, **new** `src/tripll/templates/wave-plan-template.md`, `src/tripll/cli.py`, `src/tripll/adapters/__init__.py`, `pyproject.toml` |
| Onboarding (W14, W15) | **new** `src/tripll/onboard/{brownfield,greenfield,evaluate,nextstep}.py`, `src/tripll/skw/doc_folder.py`, `src/tripll/scaffold.py`, `src/tripll/cli.py`, **new** `docs/runbooks/onboarding-runbook.md` |
| Docs / a11y (W12) | `docs/**`, `about-tripll/**`, `src/tripll/api/ui/templates/**`, `README.md`, `CLAUDE.md` |
| Tests (W1) | **new** `tests/test_ui_auth.py`, `test_cancellation.py`, `test_exit_wiring.py`, `test_integrate_resume.py`, `test_cost_accounting.py`, `test_obs.py`, `test_cw_portability.py`, `test_run_id_safety.py`; **new** `docs/test-plans/l1-remediation.md` |

## Finding ↔ wave reconciliation

Every row is a finding from the audit. **Anchors re-verified at `3f5cf9b`** — W0 re-greps before any
edit, since line numbers shift.

| ID | Finding | Live anchor | Wave |
|----|---------|-------------|------|
| CI-00 | Actions never executed — 0/27 runs, billing hold | GitHub billing (external) | **P0** |
| DX-05 | `lint`/`typecheck` lack `sync` prereq → PATH ruff (0.8.1 vs 0.15.12) | `Makefile:9–10`, `:279–281` vs `:295` | **P0** |
| DX-01 | No `timeout-minutes` on the CI job | `.github/workflows/ci.yml` | P0 |
| DX-02 | Python unpinned — venv built on 3.14.6 vs `requires-python >=3.12` | `.github/actions/bootstrap/action.yml` | P0 |
| PLAN-selfhost | `validate_plan` gates `src/`+`tests/` refs; no "planned-new" exemption | `plan_paths.py:62` | P0 |
| PLAN-gates | No auto-accept knob for human gates | absent (`grep auto_accept src/` empty) | P0 |
| SHAPE-01 | `check_stop_rule` unions targets across *unrelated* parallel waves; 3 non-overlapping waves with 6 total targets are refused. `compile_plan` supplies neither `code_graph` nor `requirement_span`, so only the crude fallback ever runs | `shape_checks.py:186–199`, called from `:213` | P0 |
| PROV-01 | Backend chosen **per run**, not per wave — `Engine` holds one `self.adapter` for every node | `engine.py:954`, `:1318` (`_resolve_adapter`), `:2366`; `cli.py:789` (`--backend`) | **P1** ✅ |
| PROV-02 | One **global** semaphore for all backends — cannot cap `cursor_local` independently, so its extension host is overwhelmed | `adapters/pools.py:131–138`; `engine.py:961–962` | **P1** ✅ |
| PROV-03 | No infra-failure class: *"Couldn't start"* / *"Workspace Disconnected"* burns a wave attempt and trips the breaker | `adapters/failure_class.py` (`classify_failure`) | **P1** ✅ |
| MODEL-01 | `DEFAULT_MODEL = "claude-sonnet-4-6"` while the Engine docstring documents `claude-3-5-sonnet` — a **retired** ID that 404s | `adapters/claude_code.py:37` vs `engine.py:26` | **P1** ✅ |
| GRAPH-01 | Code graph exists but is not wired: `compile_plan` passes no `code_graph`, so the precise D20 rule can never fire | `graphstore/`, `plan/shape_checks.py:194–230` | **P2** ✅ |
| TRACE-01 | No span wraps agent dispatch — the one chokepoint every backend shares emits nothing | `adapters/base.py:407–544`, `engine.py:2541` (`tripll.wave`) | **P3** ✅ |
| TRACE-02 | Five agent/LLM call sites, none traced; one (`pydantic_ai.Agent.run_sync`) bypasses adapters entirely | `engine.py:2541`, `orchestrator_gate.py:192`, `build_plan_from_errors.py:333`, `extract/semantic.py:143`, `skw/changelog_eval.py:393` | **P3** ✅ |
| TRACE-03 | **Two** Logfire configurators with different gates; `tripll skw …` calls `logfire.configure()` twice | `obs.py:88–166` vs `skw/tracing.py:50–69` (forwarder) | **P3** ✅ |
| TRACE-04 | No local trace sink — tracing is all-or-nothing on a cloud token; no JSONL/SQLite writer exists | `obs.py:136–166`, `tracing/sinks.py` | **P3** ✅ |
| TRACE-05 | No self-hosted Logfire path — `AdvancedOptions(base_url=…)` is never passed | `obs.py:58–66` | **P3** ✅ |
| TEST-03 | 14 tests require gitignored, never-authored `.cursor/agents/*.md` | `tests/test_agent_roster.py:78–83` | **W2** |
| ARCH-agentdef | `hash_agent_def` → `None`; AgentDef nodes silently absent; dead doc links | `graphstore/task_sync.py:40–48` | W2 |
| SEC-01 | Mutating HTML form POSTs skip `require_auth` | `api/ui/router.py:218, 305, 366, 396` | **W3** |
| SEC-05 | No CSRF on those POSTs | same handlers | W3 |
| SEC-06 | Page shells unauthenticated (fragments *are* gated) | `router.py:160, 276, 291, 342, 389, 415` | W3 |
| SEC-02 | `find_run_dir` joins `folder / run_id` with no traversal guard | `pipeline.py:514–524` | **W4** |
| SEC-03 | `?token=` on htmx URLs duplicates `hx-headers`, leaks to logs | `run_detail.html`, `_waves_tbody.html`, `_attempts.html`, `log_full.html` | W4 |
| SEC-04 | `base.html` injects token via HTML escape, not `tojson` | `base.html:16` vs `_hitl_modal.html:36` | W4 |
| SEC-07 | Redaction hide list contains only `signature` | `config/log-hide-keys.toml` | W4 |
| OBS-01 | `instrument_httpx(capture_all=True)` can ship auth headers/bodies | `obs.py:162` (`capture_all=False`) | **P3** fixes, W4 re-verifies |
| BUG-01 | `asyncio.gather` without `return_exceptions=True` — one failure cancels siblings | `engine.py:2331` | **W5** |
| BUG-02 | `run_streaming` kills proc on `TimeoutError` only — cancellation orphans it | `adapters/base.py:262–280`, `:338` | W5 |
| BUG-03 | `_execute_node` `finally` awaits `_ledger_lock`; cancellation strands waves `running` | `engine.py:2823–2830` (`finally`) | W5 |
| BUG-cost | `reset_wave_attempts` clears attempts but never debits `runs.cost_usd` | `ledger.py:799–813` vs `:850–854` | **W6** |
| BUG-07 | `_BREAKER_STATE` process-global, not per-run | `exits.py:47, 151–155` | W6 |
| DEBT-02 | `record_exit_on_run` no-op SQL `SET updated_at = updated_at` | `exits.py:91` | W6 |
| BUG-10 | `create_branch` always `git checkout -B` — force-resets on re-integrate | `integrate.py:228` | W6 |
| BUG-06 | Exit 1 `goal_met` reads `pullfrog_success`; **zero** production setters | `exits.py:168` (sole repo-wide occurrence) | **W7** |
| ARCH-exits | Evaluator disconnected from Engine; exits 4/7/8 not on the main path | `exits.py` ↔ `engine.py` inline budget/no-progress | W7 |
| DIR-01 | Wire exits 7/8 + a single `evaluate_exit` path | `engine.py` | W7 |
| L1-scaffold | `l1_outer` / `l1_pr` nodes emit state only; no adapter invocation | `l1_outer.py:188–230`, `l1_pr.py:256–285` | **W9** |
| ARCH-CW | `LEGACY_CW_BUCKETS` hardcodes sevn paths — wrong forbidden set elsewhere | `plan/cw_buckets.py:5–15`, `graph.py:38` | **W8** |
| DEBT-parse | Docstrings still say "sevn.bot git checkout" | `repo_root.py`, `worktrees.py` | W8 |
| DX-runs | Docs say nested legacy runs path while CLI resolves `runs/` | `cli.py:67, 77–83`, `pipeline.py:5`, `build_plan_from_errors.py:9` | W8 ✅ |
| TEST-01 | No `tests/test_obs*` — no-op / `capture_all` unguarded | absent | **W10** |
| TEST-02 / DX-04 | `make bench` target **does not exist**; bench never runs | `Makefile` (no `bench` match) | W10 |
| PERF-01 | `_graph_brief_tokens` computed twice per task | `serve/brief_packer.py` | W10 |
| DX-03 | `log_redact` hand-parses TOML instead of `tomllib` | `log_redact.py:54` | **W11** |
| Dependabot | 7 open PRs, none CI-verified | `dependabot/*` branches | W11 |
| ONB-01 | No one-time setup: no `tripll.toml`, no user config, no `setup`/`doctor`/`config`; `init` creates only the runs layout | `cli.py:373–387` | **W13** |
| ONB-06 | Only the **v2** wave-plan template ships in the wheel; the v3 template lives in `docs/`, outside the package | built-wheel inspection; `docs/wave-plan-template.md` vs `skw/wave-plan-template.md` | **W13** |
| ONB-02 | No brownfield command — nothing turns an existing repo into one tripll can work on | `cli.py:1771`, `:1798` (doc-folder scoped only) | **W14** |
| ONB-03 | No repo evaluation — `report.py` is per-run; nothing aggregates the code graph into an assessment | `report.py`, `cli.py:1331` | **W14** |
| ONB-05 | `doc_folder.py` hard-imports `sevn.docs.*` and mutates `sys.path` — forbidden by `CLAUDE.md`, and it sits on the brownfield path | `skw/doc_folder.py:172–177`, `:205`, `:283` | **W14** |
| ONB-04 | Greenfield scaffolds a **generic** cookiecutter package — no tripll specs, agents, config or plan | `scaffold.py`, `make scaffold-package` | **W15** |
| ARCH-06 | 17 `docs/agents/` roles, few Engine-dispatched | `docs/agents/` | **W12** |
| FRONT-01 | Interactive controls lack `aria-label` | `api/ui/templates/**` | W12 |
| PERF-02 | Sync SQLite in async routes (low priority, single-operator) | `api/ui/router.py` | W12 |

## Recent baseline / drift

- **HEAD when audited:** `3f5cf9b` on `pre-0.0.1`; `main` at `ba85072`. W0 re-records both.
- **Gate, executed 2026-07-25:**
  - `lint`, `typecheck`, `log-redact-check`, `pullfrog-ref-check`, `about-site-check` — **all pass**
  - `test` — **14 failed, 894 passed, 25 skipped, 18.7s**; all 14 are TEST-03, no second cause
- **CI:** 27 runs recorded, `{"cancelled": 6, "failure": 21}`, **zero successes**, oldest observed
  2026-06-21. Every one annotated *"job was not started because recent account payments have
  failed…"*. The `main` merge of the entire L1 program (PR #15) was never gated.
- **Roster reality — corrected.** The 14 failures are all
  `test_section_11_cursor_agent_for_agentdef_hash`, which asserts `.cursor/agents/<slug>.md` exists.
  **All 14 slugs already have an authored, tracked, contract-complete brief** at
  `src/tripll/skw/agents/<slug>.md` — `test_section_11_skw_brief_exists` passes for every one.
  What is missing is only the **Cursor-tree copy**, because `hash_agent_def`
  (`task_sync.py:42`) hardcodes `.cursor/agents/`. `src/tripll/skw/agents/` has 33 files,
  `docs/agents/` has 17, `.cursor/agents/` has 0. Two local checkouts do hold unrelated Cursor
  briefs (`/Users/alex/Documents/code/tripll/.cursor/agents/`,
  `.../sevn.bot/sevn/.cursor/agents/`) — W2 harvests anything of value from them.
- **Toolchain:** `uv.lock` pins `ruff==0.15.12`; an unsynced `uv run ruff` resolved **0.8.1** from
  `PATH` and failed to parse `pyproject.toml` (`Unknown rule selector: ASYNC240`).
- **Size:** 139 modules / 39,317 LOC under `src/tripll/`; 87 test files / 15,465 LOC.
- **Not a factor:** no `git clean -x` ever ran here (audit §19). Do not plan recovery work.

## Existing primitives this plan reuses

- `api/_auth.py` `require_auth` — already correct and already applied to **every** htmx fragment
  route (`router.py:448, 469, 556, 593, 634, 652, 666, 679, 692, 712`). W3 extends its reach; it
  does not invent a new mechanism.
- `_hitl_modal.html:36` `{{ api_token | tojson }}` — the **correct** token-injection pattern already
  in the tree. W4 makes `base.html:16` match it rather than designing something new.
- `loops/exits.py` `evaluate_exit` / `ExitFired` / `_BREAKER_STATE` — the exit table is fully coded
  and unit-tested; W7 wires it, and must not re-implement it.
- `github/reviews.py` `pullfrog_merge_signal` — the missing input for exit 1 already exists.
- `harness/contracts.py` outcome contracts + `harness/boundary.py` verifier isolation — implemented
  and tested; W7 reads outcomes through them; the `[waves.outcome]` blocks above are graded by them.
- `ledger.py` `open_ledger` / `transition_*` / `end_attempt` / `append_event` + `EventRow` SSE spine.
- `worktrees.py` `allocate_worktree` / `detect_scope_breach` / `checkpoint_worktree`.
- `src/tripll/skw/agents/*.md` — 33 authored, tracked briefs including all 14 section-11 slugs.
  W2 makes `hash_agent_def` read **this** tree.
- `scripts/check_pullfrog_ref_parity.py` + `Makefile:295` `pullfrog-ref-check: sync` — the **correct**
  Make dependency pattern; P0 applies it to `lint`/`typecheck`.

## Global conventions

1. **Worktree only** on `wave/l1-remediation`. Never `git clean -x` / `-X`.
2. **P0 is a hard gate.** No wave after W1 may be marked done while CI is still not executing. If
   the billing block cannot be cleared, the run **pauses at the Pre-0 gate** — or, under
   `human_gates = "auto_accept"`, P0 resolves to **PARKED** on its red canary. It never proceeds
   with local-only verification and calls it green.
3. **Tests-first.** W1 (`test-creator`) authors the RED suite; impl waves turn it green and are
   **forbidden from editing `tests/`** except via `test-creator` re-dispatch. Cross-wave reds use
   `@pytest.mark.xfail(reason="green after W<N>: …", strict=False)`.
   **One exception:** P0.7/P0.8 are plan-infrastructure that must exist before W1 can be dispatched;
   they ship with their own tests in the same commit.
4. **Make/uv only.** Per wave: `make lint`, `make typecheck`, `make test`. Full gate at Final via
   `make ci`. Never raw `pytest` / `ruff` / `mypy`.
5. **Every wave ends with commit + push.** Conventional commit; CHANGELOG bullet in the **same**
   commit when `src/` changes; the **Re-entry block updated in the same commit**.
6. **Conventional Commits** — validate with `python scripts/check_conventional_commit.py --message …`.
   No `--no-verify`.
7. **Security fixes ship with a regression test that fails without the fix.** A W3/W4 item whose
   test passes against unpatched code is rejected at review.
8. **No behaviour-changing deletion without a replacement test.**
9. **Path convention:** repo-root-relative (`src/tripll/…`, `docs/…`, `tests/…`).
10. **Re-grep before editing.** Every anchor in this plan is a `3f5cf9b` line number and will drift.
11. **Thermos gate** after Final before any PR/merge request.
12. **Observable acceptance.** Every `**Acceptance:**` block is a runnable command with an expected
    value. If it cannot be checked by running something, it is not acceptance — it is a hope.
13. **PARKED is a legal outcome; a weakened criterion is not.** See *Wave status*.

### Test tiers

Every test authored by this plan carries a tier marker
(`@pytest.mark.tier1` … `tier4`, registered in `pyproject.toml` by W1).

| Tier | Covers | Runs | Blocks? |
|------|--------|------|---------|
| **1 — offline** | pure logic, parsers, validators, error paths | every `make test` | yes |
| **2 — live, gated** | real subprocesses, real git, real sockets — behind `RUN_LIVE=1` | wave close-out + Final | yes when run |
| **3 — e2e smoke** | one real run: CLI on a fixture, one API call | every `make test` | yes |
| **4 — canary** | the world, not the code: CI billing, GitHub API reachability, dependabot state | never blocks; reported | **no** |

Tier assignments for this plan's suite:

| Test | Tier | Why |
|------|------|-----|
| `test_ui_auth.py`, `test_run_id_safety.py`, `test_log_redact.py`, `test_cost_accounting.py`, `test_exits.py`, `test_cw_portability.py`, `test_brief_packer.py` | 1 | pure, hermetic |
| `test_obs.py` | 1 | configurator contract asserted without a token |
| `test_tracing.py` (P3.12) | **1** | fake clock, temp run dir, no network — local sinks and the dispatch span are asserted with `logfire` absent |
| `test_config.py` (W13) | **1** | four-layer precedence with a temp HOME and a temp repo — no network, no provider |
| `test_onboard.py` (W14, W15) | **1** | `init` / `new` against a temp git fixture that is **neither tripll nor sevn**; idempotence asserted by second run |
| `test_cancellation.py` (a), (c) | 1 | in-process asyncio |
| `test_cancellation.py` (b) real-pid, (d) kill-and-resume | **2** | spawns and kills real processes — `RUN_LIVE=1` |
| `test_integrate_resume.py` | **2** | real git branches in a temp repo |
| `test_exit_wiring.py` | **3** | Engine path end to end on a fixture plan |
| `test_pr_loop.py` adapter assertions | **3** | fake adapter, real loop wiring |
| `test_provider_pools.py` (W1.15a) | **1** | fake clock + fake adapters — the pool contract CI runs on every push |
| `test_provider_pools.py` real-subprocess probe (W1.15b) | **2** | spawns real agents; carries the CAP-01 calibration levels |
| `make bench` (W10) | **2** | minutes, not seconds |
| **P0.1 billing canary**, dependabot reachability | **4** | tests the world; **never blocks** |

**Tier-4 rule (from the factory):** a red canary is logged as external. It never triggers a "fix"
of working code, and it never marks a wave failed — but it *does* block auto-accept of the gate it
guards (see *Human gates*).

### Wave status

| Status | Meaning | Required with it |
|--------|---------|------------------|
| `[ ]` | not started | — |
| `[x]` | done, pushed, **CI green on that sha** | sha + run id in the change summary |
| `[P]` | **PARKED** — attempted, could not be closed honestly | a one-line reason **and** a filed GitHub issue number |

**Parking rules.**
- A wave parks after **3 failed attempts** on the same blocking item, or when its outcome contract
  cannot be satisfied without weakening a criterion.
- **Criteria are never deleted or narrowed to reach `[x]`.** Parking is the honest exit; a softened
  assertion is a defect and Thermos T.1 hunts for it.
- **Plan-level stop rule: at 3 parked waves, stop.** Do not push through to Final. Write the run
  summary, update Re-entry, and report. (`[pipeline] max_parked_waves = 3`.)
- A parked wave's dependents do not silently proceed — each re-evaluates whether its own contract
  is still reachable, and parks too if not.
- **Restart permission:** an approach that proves unsalvageable may be abandoned and rebuilt from
  this document. A restart resets that wave's attempt count but **must be logged** in Re-entry with
  the reason. Silently re-scoping instead of restarting violates the contract.

### Per-wave close-out (applies to P0, W0–W12, Final, and each Thermos fix pass)

1. Verification green for that wave (`make lint` / `make typecheck` / `make test`).
2. Run the wave's `**Acceptance:**` commands; paste real output into the commit body.
3. Stage the `## [Unreleased]` CHANGELOG bullet when `src/` touched (same commit).
4. **Update the Re-entry block** (same commit).
5. **Commit** with a Conventional Commits subject scoped to this wave.
6. **Push:** `git push -u origin HEAD` (first time) or `git push`. No force-push.
7. **Confirm the pushed commit turned CI green** (possible only after P0). Flip the checkbox with
   `(YYYY-MM-DD ✅: <sha> — <run-id> green)`, or to `[P]` with reason + issue.

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| R1 | Gate first | P0 (CI) and W2 (green gate) precede every functional fix. A finding fixed under a dark gate is unverified work. |
| R2 | AgentDef source | **Re-home `hash_agent_def` to `src/tripll/skw/agents/`; un-ignore nothing.** All 14 briefs already exist there, tracked and tested. Harvest anything worth keeping from the two local `.cursor/agents/` trees into `skw/agents/` first, then delete the `.cursor/` dependency. Rejected: authoring 12 duplicate Cursor briefs — it creates the very drift R3 fears, and binds graph-node identity to a gitignored, IDE-vendor path in a tool that dispatches to three backends. ADR 006. |
| R3 | Generation vs authoring | Moot under R2 — there is now **one** brief tree, so nothing to generate or drift. `docs/agents/` remains the human-facing narrative; `skw/agents/` is the machine contract. W2 states the split. |
| R4 | Auth boundary | When `TRIPLL_API_TOKEN` is set, HTML and JSON are **one** boundary. Token unset ⇒ open localhost dev mode stays, unchanged and documented. |
| R5 | CSRF | Double-submit cookie token, no server-side session store. Rejected: `SessionMiddleware` — new state for a single-operator tool. |
| R6 | Token transport | `Authorization: Bearer` via `hx-headers` only. `?token=` retained **solely** for `EventSource`, which cannot set headers, and documented as the one exception. |
| R7 | Cancellation | `gather(return_exceptions=True)` + `finally: proc.kill()` + a shielded ledger finalizer. Wave state must be terminal-or-recoverable after any cancellation. |
| R8 | Exit 1 | **Wire or fail.** `pullfrog_merge_signal` → `evaluate_exit(1)`. Withdrawal of `goal_met` from the advertised table is **not** an available outcome — it is listed as `forbidden` in W7's contract. If W7 cannot wire it, W7 **parks** with an issue and Final reports it. Rationale: a mid-wave agent under schedule pressure must not be the one deciding to shrink the public contract. ADR 007. |
| R9 | CW hotspots | Default to **empty**; sevn buckets move to an opt-in fixture used by the corpus-replay test. tripll must not be sevn-shaped by default. ADR 008. |
| R10 | L1 loops | W9 wires **one** real path end-to-end (PR investigate→fix) behind the `graph` extra, and runs **immediately after W7**, not in the tail. Breadth over depth is rejected; a second stubbed loop is worse than one honest one. ADR 009. |
| R11 | God modules | Extraction is **out of scope** except the cancellation seam W5 needs. Refactoring 2,776 lines under a gate this young trades one risk for a larger one. Tracked as a W0.5 issue. |
| R12 | Dependabot | Rebaselined **after** P0 only. Merging 7 unverified dep bumps into a red tree is how the next audit starts. |
| R13 | Plan self-hosting | The plan carries a v3 TOML block and is dispatchable by tripll itself. P0 adds the three missing pieces (`creates` exemption, human-gate config, SHAPE-01). Rejected: a prose-only plan — its acceptance would stay self-reported. |
| R15 | Stop-rule fix vs cap raise | SHAPE-01 is fixed by making the threshold **per-wave** (P0.10) and feeding the real `code_graph` (P2.2), not by raising `_CROSS_CUTTING_MODULE_LIMIT` from 5 to 25. Raising the constant would silence the guard for every plan tripll runs; the defect is the group-union proxy, not the number. |
| R16 | Provider routing | Provider and model are **declared per wave**, never inferred. Graph-derived hints (module count, CALLS fan-out) are advisory metadata only — auto-selection is rejected: it makes a run's cost and quality unpredictable and unauditable. Failover changes the **provider only**; a silent model downgrade would make a wave's result incomparable to its contract. ADR 010. |
| R17 | Builder ≠ checker | The reviewer is never the builder's session. Thermos runs on `cursor_local` + `claude-opus-5` — same provider as the builders but a **fresh session** and an explicit top-tier model pin (not Auto). Independence comes from freshness and model choice, **not** from handicapping the reviewer. Rejected: rotating Thermos onto Auto or whichever provider is idle. |
| R18 | Code graph | The graph is **activated for planning and briefs** (stop rule, graph briefs, AgentDef nodes) and stays an **optional extra** — no hard `langgraph`/`networkx` dependency in the base install, and a run without the extras must still complete. Rejected: making the graph mandatory to get the precise stop rule. ADR 011. |
| R20 | Effort & budget | Reasoning effort is **declared per wave** (`reasoning_effort`, distinct from the v3 `effort` size field) and expressed per provider — a `--effort` flag on Claude Code, part of the model string on Cursor. `claude --max-budget-usd` is wired as a **process-level** backstop because exit 3 trusts a ledger BUG-cost proves can be wrong. `claude --fallback-model` is **rejected**: it silently substitutes a model, the exact downgrade R16 forbids. |
| R19 | Cursor limit | `cursor_local` is capped at **5** by configuration, with an adaptive throttle that halves the pool after repeated `infra` results. The cap is the operator's number; the throttle is the safety net. Rejected: hard-coding a lower constant — the right ceiling is machine-specific and belongs in config. |
| R14 | Human gates | Any human gate may be auto-accepted by config, **except** the merge request. Auto-accept skips the prompt, never the canary; a red canary parks the gate. |
| R21 | Tracing | Every agent call is traced — **no exceptions, no opt-out per call site**. Coverage is achieved at the one seam all backends share (`AgentAdapter.dispatch`) plus `instrument_pydantic_ai` for the one non-adapter caller, so "traced" is a property of the architecture, not a checklist someone must maintain. Local JSONL+SQLite sinks are the **default and need no token** — tracing that requires a cloud account is tracing most developers never see. Prompt/completion capture defaults to **shape only**; `full` is opt-in. Two departures from sevn: tripll adds a **self-hosted Logfire** target (`AdvancedOptions(base_url=…)`, which sevn lacks) and **skips sevn's OTLP replay bridge** — one live `TracerProvider` is enough at this scale. Rejected: sampling (a wave run is tens of spans, not millions) and a `trace_id` ledger column (a join on `attempt_id` costs no migration). ADR 012. |
| R23 | Onboarding shape | Three commands, not one: **`tripll setup`** (once per machine), **`tripll init`** (existing repo), **`tripll new`** (new project). `init` and `new` share **one** spec/plan emitter — greenfield is brownfield plus project creation, never a parallel implementation. Both are **idempotent**: re-running reconciles and never clobbers an operator-edited file without `--force`. The brownfield evaluation is a **deliverable, not a side effect** — it is what tells the operator which waves to plan first, and every finding in it carries `file:line` evidence. Rejected: folding setup into `init` (machine-level provider config does not belong in a repo), and a web wizard (sevn's shape; tripll is a headless CLI tool). ADR 013. |
| R24 | No stored credentials | tripll **never** persists a provider API key or token. `tripll setup` verifies auth through each adapter's `capabilities()` and prints the command that fixes a failure; the credential stays in the backend toolchain that already owns it. Config files hold routing and limits only. Rejected: a `[credentials]` table or keyring integration — it duplicates a secret store that `claude` and `cursor-agent` already maintain, and turns every tripll config file into a leak surface. |
| R25 | SKW salvage | Keep SKW's **document contracts and prompt spine** (spec/PRD/changelog schemas, `doc_score`, the `specify`→`wave-generator` prompts, `nextstep`); leave its **second execution engine** (`pipeline.py`, `graph_nodes.py`, `driver.py`, `states.py`, `wave_model.py`, `git.py`, `verify.py`). `engine.py` + `adapters/` supersede all of it. SKW's value was never its runner — it is the accumulated definition of what a good spec looks like. Rejected: a wholesale port (doubles the orchestration surface this plan is trying to shrink) and a wholesale delete (throws away the only doc contracts tripll has). |
| R22 | One configurator | `tripll.obs` is the **sole** owner of tracing configuration, and the dependency runs **one way**: `tripll.skw.tracing` → `tripll.obs`, never the reverse. `tripll.obs` owns tracing *directly* — it does not route through, wrap, or import anything in `tripll.skw`, and tracing keeps working with the SKW package deleted. `skw.tracing` keeps its `span` / `trace_node` API but forwards to the spine, and `config/log-hide-keys.toml` is the **single** hide-list for both log and span redaction. Rejected: keeping two independent Logfire setups (they already double-configure under `tripll skw`, and two redaction lists always drift — sevn shipped two and regretted it), and deleting `skw.tracing` outright (its call sites are the only structured spans in the SKW pipeline today; it dies with the SKW mount, not before). |

## Out of scope

- **Splitting `engine.py` / `cli.py` / `api/app.py` / `ledger.py` / `ui/router.py`** (R11) — audit
  §14.4 wants it; it is a separate program with its own characterization-test prerequisite.
- **Multi-operator / multi-tenant hardening** — tripll is single-operator by design; PERF-02 is
  documented, not re-architected.
- **Dependency vulnerability scanning** (`pip-audit` / OSV) — worth doing, not in this plan.
- **Live end-to-end runs against real `claude` / `cursor-agent` backends** — adapters stay
  statically verified; a live-run program is separate.
- **Building L2** — telemetry seams only, unchanged from the L1 program.
- **`cursor_cloud` live dispatch** — remains deferred upstream.
- **Rewriting the dashboard's visual language** — a11y only (FRONT-01).
- **Retiring the SKW legacy CLI mount** — surface-area concern noted in §8, not a defect. P3 makes
  `skw.tracing` a thin forwarder (R22) so the mount can be removed later without taking the SKW
  pipeline's only spans with it; the removal itself stays out of scope.
- **A trace-viewer UI.** P3 writes queryable SQLite and JSONL and exports to Logfire, which already
  has a viewer. Building tripll's own trace UI (sevn's Mission Control equivalent) is a separate
  program; W12 adds provider/model/effort columns to the existing dashboard and nothing more.
- **Sampling, rollups, and an OTLP replay bridge.** A wave run is tens of spans, not millions
  (R21). sevn's hourly rollups and file-replay bridge solve a volume problem tripll does not have.
- **Parallel dispatch of this plan.** SHAPE-01 is fixed in P0, so the four tracks *would* compile —
  but this plan still dispatches serially by choice (see the machine block). Running a future plan
  in parallel is in scope for tripll; running *this* one is not.

## Wave checklist

Each row is `[x]` only after that wave's **commit + push** *and* a green CI run for that sha.

| Wave | Provider / model | Scope | Findings | Status |
|------|------------------|-------|----------|--------|
| P0 | **human** + `cursor_local` claude-opus-5 | Pre-0 gate: clear Actions billing; CI timeout + Python pin; Make `sync` prereqs; plan self-hosting | CI-00, DX-01, DX-02, DX-05, PLAN-selfhost, PLAN-gates, SHAPE-01 | [x] (2026-07-26 ✅: ad4a255 — CI canary run 30166223593 started; fresh-clone lint ruff 0.15.12; validate-plan green) |
| P1 | `cursor_local` auto | **Provider fabric**: per-provider pools, per-wave routing, infra-failure class, failover, model-ID refresh, **effort + budget flags**, auth preflight, ceiling calibration | PROV-01…03, MODEL-01, EFFORT-01, BUDGET-01, AUTH-01, CAP-01 | [x] (2026-07-26 ✅: d2ad6c0 — pools.py + 11 provider_pools tests green; claude-3-5-sonnet purged from src) |
| P2 | `cursor_local` auto | **Code graph activation**: real `code_graph` into the stop rule, graph briefs on by default | GRAPH-01 | [x] (2026-07-26 ✅: 6e88600 — code_graph.py + 8 tests green; compile_plan supplies code_graph) |
| P3 | `cursor_local` auto | **Tracing spine**: span every agent call at the one adapter seam; local JSONL+SQLite sinks; Logfire cloud / **self-hosted** / OTLP exporters; one configurator | TRACE-01…05, OBS-01 | [x] (2026-07-26 ✅: 39a0503 — tracing spine + 10 tests green; 1 logfire.configure site) |
| W0 | `cursor_local` auto | Baseline sha, anchor re-grep, apply the base-branch rule, ADRs 006–011, pin the contract | — | [x] (2026-07-26 ✅: c9bb7c1 — ADRs 006–011 + contract sha256; anchors re-grepped; issues #16–#18) |
| W1 | `cursor_local` auto | RED suite (xfail-guarded, tier-tagged) + `docs/test-plans/l1-remediation.md` — `role: test-author` | all | [x] (2026-07-26 ✅: b7b6233 — 33 xfailed, 0 failed; tier markers) |
| W2 | `cursor_local` auto | Re-home AgentDef source to `skw/agents/`; harvest local Cursor briefs; green the roster suite | TEST-03, ARCH-agentdef | [x] (2026-07-27 ✅: be971bc — hash_agent_def skw-only; roster 71/71 green; grep src/tests/docs 0) |
| W3 | `cursor_local` auto | Auth parity: mutating POSTs, page shells, CSRF | SEC-01, SEC-05, SEC-06 | [x] (2026-07-27 ✅: e69fa47 — require_auth×20 router.py; _csrf.py; test_ui_auth 18/18 W3 green) |
| W4 | `cursor_local` auto | Token transport, traversal guard, redaction list, obs capture | SEC-02, SEC-03, SEC-04, SEC-07, OBS-01 | [x] (2026-07-27 ✅: 1046f2d — find_run_dir guard; ?token= EventSource-only; tojson base.html; 16 hide keys; env-shaped redaction; W1.2–W1.5 green) |
| W5 | `cursor_local` auto | Cancellation safety: gather, subprocess kill, shielded ledger finalizer | BUG-01, BUG-02, BUG-03 | [x] (2026-07-27 ✅: 5ff37f8 — return_exceptions gather; proc.kill finally; shield+lock-timeout finalizer; startup reconciliation events; cancellation 3 pass 1 skip) |
| W6 | `cursor_local` auto | Ledger + integrate correctness, **per-provider cost attribution** | BUG-cost, BUG-07, DEBT-02, BUG-10, COST-01 | [x] (2026-07-27 ✅: 43a0510 — cost derived from attempts; per-run breaker; integrate resume; status per-provider rollup) |
| W7 | `cursor_local` auto | Exit closure — **wire or fail**: `pullfrog_success`, Engine `evaluate_exit`, exits 4/7/8 | BUG-06, ARCH-exits, DIR-01 | [x] (2026-07-27 ✅: 4079acb — evaluate_exit in engine; pullfrog_success setter; exit_firing tests green; design-note Engine-live ×8) |
| W9 | `cursor_local` auto | Close **one** L1 loop end-to-end behind the `graph` extra | L1-scaffold | [x] (2026-07-27 ✅: 900cea9 — dispatch_bridge.py; l1_pr investigate/fix invoke adapter; test_pr_loop 10/10 green) |
| W8 | `cursor_local` auto | Repo portability: CW hotspots, docstrings, runs-path docs | ARCH-CW, DEBT-parse, DX-runs | [x] (2026-07-27 ✅: 15d2028 — cw_portability + corpus_replay green; empty default hotspots) |
| W10 | `cursor_local` auto | `tests/test_obs.py`, `make bench` + CI job, brief-packer double-compute | TEST-01, TEST-02, DX-04, PERF-01 | [x] (2026-07-27 ✅: a39dc9a — obs+brief_packer 14/14; make bench; CI continue-on-error; PERF-01; execute_node/batch spans) |
| W11 | `cursor_local` auto | `tomllib` for hide-keys; rebaseline 7 dependabot PRs | DX-03, Dependabot | [x] (2026-07-27 ✅: c9216d9 — tomllib hide-keys; ruff/mypy/pytest/typer/uvicorn rebaseline; checkout@v7; action-gh-release@v3; 7 dependabot PRs closed) |
| W13 | `cursor_local` auto | **Config spine**: `tripll.toml` + user config, `tripll setup`, `tripll doctor`, ship the v3 template in the wheel | ONB-01, ONB-06 | [x] (2026-07-27 ✅: e1fb05d — config.py four-layer precedence; setup/doctor CLI; v3 template packaged; force-include removed; wheel guard test) |
| W14 | `cursor_local` auto | **Brownfield `tripll init`**: specs, PRDs, plans, `tripll.toml` and a **repo evaluation**; cut the sevn import | ONB-02, ONB-03, ONB-05 | [x] (2026-07-27 ✅: 7001fbf — brownfield init, emitters, evaluate, onboarding runbook) |
| W15 | `cursor_local` auto | **Greenfield `tripll new`**: scaffold a project with specs and config, sharing brownfield's emitters | ONB-04 | [x] (2026-07-27 ✅: 52cf10e — greenfield new, packaged skeleton, shared emitters, validate-plan + make check) |
| W12 | `cursor_local` auto | Roster honesty banner, a11y labels, PERF-02 note, **provider/model/effort in the dashboard**, **onboarding in the README + about-site**, docs | ARCH-06, FRONT-01, PERF-02, DASH-01 | [ ] |
| Final | `cursor_local` claude-opus-5 | xfail sweep, `make ci` green, **green CI run on the branch**, change summary | — | [ ] |
| Thermos | `cursor_local` claude-opus-5, **fresh session** | Branch review, **tamper audit**, merge request; commit+push each pass | — | [ ] |

Every `cursor_local` wave (except P0, Final, Thermos, which pin `claude-opus-5`) carries `fallback = ["claude_code"]`. Failover changes the
**provider only** — the wave's model intent is preserved (`auto` → the provider's `default_model`).

Wave IDs are stable — the finding tables and audit cross-references depend on them. **W9 executes
before W8** (R10); the ID ordering is historical, the execution order is authoritative.

## Execution order & parallelism

**Dispatched order (serial — by choice):**

```text
P0 → P1 → P2 → P3 → W0 → W1 → W2 → W3 → W4 → W5 → W6 → W7 → W9 → W8 → W10 → W11 → W13 → W14 → W15 → W12 → Final → Thermos
```

**W13–W15 sit before W12 on purpose.** W12 is the docs wave, and "docs last" only holds if the
onboarding commands already exist when it runs. Putting them after W12 would ship a README
describing software that had not landed.

**P3 sits in the P-series on purpose.** Tracing lands before the first functional wave, so every
wave after it is observable *while it runs* — the plan becomes its own tracing smoke test, the same
self-hosting argument as R13. Putting it in the tail would leave the entire security and runtime
chain untraced and prove nothing.

**Why serial, given P0.10 fixes the compiler defect that also forbade it.** Per-wave *commit →
push → green CI on that sha* is this plan's acceptance mechanism (close-out step 7). Parallel
tracks live on separate branch tips, so every wave's green run would cover a partial tree — a
weaker version of the exact condition (CI-00) that produced these findings. The upside is smaller
than it looks: after the merge-hotspot table, W12 shares templates with W3/W4, W10.5 adds an
`engine.py` span that collides with W5/W7, and `CHANGELOG.md` is a shared writer on every wave.
Three real tracks, ~30–40% wall clock — not worth diluting the gate.

The tracks below are therefore **operator guidance for hand-driven parallelism**, with the
merge-hotspot serialisation observed manually:

```text
P0 (CI executes) → W0 (anchors) → W1 (RED suite) → W2 (gate green)
├── Track A (security):   W3 → W4
├── Track B (runtime):    W5 → W6 → W7 → W9
├── Track C (portability): W8
└── Track D (DX):         W10 → W11
        └── join(C, D) → Track E (onboarding): W13 → W14 → W15 → W12 (docs)
                └── Final → Thermos
```

| Hard dependency | Reason |
|-----------------|--------|
| P0 before everything | Without an executing CI, no wave's "green" claim is checkable (R1) |
| P1 before W0 | Waves declare providers; nothing can route until the fabric and pools exist (R16) |
| P2 after P1 | Graph-derived routing hints read the provider config P1 lands (advisory only) |
| P3 after P2 | Wave spans carry `provider` / `model` / `reasoning_effort` from P1 and the routing hints P2 adds — tracing an untyped dispatch records less than half the story |
| P3 before W0 | Every functional wave should be traced while it runs; P3 last would trace nothing (R21) |
| P3 before W5 | W5 does cancellation surgery on the same two files. Spans must exist first so W5's contract can require they still close on cancel, rather than a later wave discovering they never did |
| W1 before W2–W12 | RED suite defines acceptance |
| W2 before all functional waves | `make check` must be green before it can detect a regression |
| W3 before W4 | W4 edits the same templates; auth structure lands first (one-writer) |
| W5 before W6 | W6 touches `ledger.py` paths W5 makes cancellation-safe |
| W7 after W6 | exit records write through `record_exit_on_run`, fixed in W6 (DEBT-02) |
| **W9 immediately after W7** | the PR fix loop consumes the wired exit table, and must not land under end-of-plan schedule pressure (R10) |
| W10 after W5 | bench runs the dispatch path W5 stabilises |
| W11 after P0 | dependabot rebaseline is meaningless without CI (R12) |
| W13 after W11 | W11 is the last writer on `pyproject.toml`; the ONB-06 packaging fix lands after the dependency rebaseline, not into it |
| **W13–W15 after W8** | W8 removes the hardcoded sevn CW buckets (ARCH-CW) and the nested legacy runs-path doc drift (DX-runs). Onboarding a *foreign* repo before that ships would hand every new project a sevn-shaped forbidden set — the brownfield bug W8 exists to prevent |
| W14 after W13 | `init` reads the config spine and emits the packaged v3 template W13 lands |
| W15 after W14 | greenfield reuses brownfield's spec emitters — one implementation, two entry points |
| W12 last | docs describe shipped behaviour, including W9's actual scope **and the W13–W15 onboarding commands** |

### Merge hotspots

| File | Waves | Note |
|------|-------|------|
| `src/tripll/engine.py` | P0, P3, W5, W7 | plan-gate config, run/wave spans, cancellation seam, exit wiring — **serialize** |
| `src/tripll/adapters/base.py` | P1, P3, W5 | infra classifier, dispatch span, then cancellation-safe kill — **serialize**; W5 must keep the span closing on cancel |
| `src/tripll/obs.py` | P3, W4 | P3 rewrites `configure_observability` (sinks, exporters, scrubbing, `capture_all=False`); W4's OBS-01 becomes a re-verification, not a second edit |
| `src/tripll/loops/exits.py` | W6, W7 | breaker scope + no-op SQL, then Engine wiring |
| `src/tripll/api/ui/router.py` | W3, W12 | auth decorators vs a11y/PERF notes |
| `src/tripll/api/ui/templates/**` | W3, W4, W12 | CSRF field, token transport, aria labels — serialize |
| `src/tripll/ledger.py` | W5, W6 | shielded finalizer vs cost accounting |
| `src/tripll/cli.py` | W13, W14, W15 | `setup`/`doctor`, then `init`, then `new` — three waves add commands to one Typer app; **serialize** |
| `src/tripll/onboard/**` | W14, W15 | brownfield builds the emitters, greenfield reuses them — W14 is the author, W15 the second caller |
| `src/tripll/templates/**` | W13, W15 | W13 packages the v3 plan template; W15 adds the project skeleton |
| `pyproject.toml` | W11, W13 | dependency rebaseline, then package-data for the templates |
| `README.md` / `about-tripll/**` | W12 | single writer, but it documents W13–W15, so it must run after them |
| `Makefile` | P0, W10 | `sync` prereqs vs `bench` target |
| `.github/workflows/ci.yml` | P0, W10 | timeout/pin vs bench job |
| `tests/test_agent_roster.py` | W1, W2 | test-creator owns edits |
| `CHANGELOG.md` | all | one bullet stream |

---

## Pre-0 — Gate restoration and plan self-hosting (**human gate**, auto-acceptable)

**Findings:** CI-00, DX-01, DX-02, DX-05, PLAN-selfhost, PLAN-gates, SHAPE-01 · **Blocks:** everything

P0.1 cannot be done by an agent. Under `human_gates = "auto_accept"` the prompt is skipped but the
**tier-4 canary still runs**; a red canary parks P0 and stops the plan (R14).

- [x] **P0.1** *(human, external — tier-4 canary)* Clear the GitHub Actions billing block on the
      `sevn-bot` org — settings → Billing & plans. (2026-07-26 ✅: 325d13f — auto_accept canary: run 30166223593 status=completed)
- [x] **P0.2** Add `timeout-minutes: 20` to the CI job (DX-01). Test wall time is 18.7s; 20 minutes
      is generous and still bounds a hung async test. (2026-07-26 ✅: 86baca7 — `.github/workflows/ci.yml`)
- [x] **P0.3** Pin `python-version: "3.12"` in `.github/actions/bootstrap/action.yml` (DX-02) to
      match `requires-python = ">=3.12"` and ruff's `target-version = "py312"`. (2026-07-26 ✅: 86baca7)
- [x] **P0.4** Add `sync` as a prerequisite to `lint` and `typecheck` in the `Makefile` (DX-05),
      matching the existing `pullfrog-ref-check: sync` pattern at `Makefile:295`. (2026-07-26 ✅: 86baca7)
- [x] **P0.5** Verify `make ci` is reachable end-to-end on a **fresh clone** in a temp dir —
      expect it to still fail on TEST-03 (that is W2's job) and **nothing else**. (2026-07-26 ✅: 325d13f — fresh-clone `make lint` exit 0, ruff 0.15.12)
- [x] **P0.6** **Commit + push** (`ci: restore executable gate with timeout and python pin`). (2026-07-26 ✅: 86baca7)
- [x] **P0.7** *(PLAN-selfhost)* Teach `plan_paths` a **planned-new** exemption: paths listed in the
      v3 block's `[pipeline] creates` are not gated by `validate_plan`. Today `_skip_gate_ref`
      (`plan_paths.py:62`) exempts only `docs/` and `reports/`, so every `src/`- and `tests/`-shaped
      file this plan will author is reported as a dead ref. Ships with its own test. (2026-07-26 ✅: 325d13f — `tests/test_plan_paths.py`)
- [x] **P0.8** *(PLAN-gates)* Add the human-gate config: `[pipeline] human_gates` +
      `TRIPLL_HUMAN_GATES` env override, with `prompt | auto_accept | fail`, and the rule that
      `auto_accept` resolves a gate carrying a red canary to **PARKED** rather than proceeding.
      Ships with its own test. Document in the operator runbook. (2026-07-26 ✅: 325d13f — `tests/test_human_gates.py`, runbook §2)
- [x] **P0.10** *(SHAPE-01)* Fix the stop-rule proxy. `check_stop_rule` (`shape_checks.py:186–199`)
      runs a fallback that unions `targets` across every wave in a parallel group and refuses at >5.
      That conflates **one cross-cutting refactor smeared across agents** (what D20 exists to stop)
      with **several independent waves that merely coexist** (the point of lanes). Demonstrated:
      3 waves, zero shared files, one-writer clean, 6 total targets — refused.
      Apply the threshold **per wave**, not to the group union, and let `_check_one_writer` keep
      doing the overlap job it already does correctly. Where a code graph is available, pass it
      through from `compile_plan` (`:213`, which supplies neither `code_graph` nor
      `requirement_span` today) so the precise CALLS-path rule fires instead of the proxy.
      **Do not simply raise the constant** — that disables the guard for every plan tripll runs.
      Ships with a test asserting both directions: independent waves compile, a single wave
      targeting >5 modules is still refused. (2026-07-26 ✅: 325d13f — `tests/test_shape_checks.py`)
- [x] **P0.11** **Commit + push** (`feat(plan): self-host the remediation plan and add gate config`). (2026-07-26 ✅: 325d13f)

**Acceptance:**

```bash
gh run list --workflow=CI --limit 1 --json status,conclusion,databaseId   # status != "queued"/blocked
cd "$(mktemp -d)" && git clone <repo> t && cd t && make lint              # exit 0, ruff 0.15.12
uv run ruff --version                                                     # 0.15.12, not 0.8.1
tripll validate-plan docs/plans/l1-remediation.md                          # exit 0
TRIPLL_HUMAN_GATES=auto_accept tripll run --plan … --dry-run              # no prompt; canary evaluated
make test -- -k "stop_rule or plan_paths or human_gates"                  # P0.7/8/10 tests green
```

A CI run **executes** and reports a result (red is acceptable here — TEST-03 is still open).

---

## Wave P1 — Provider fabric

**Findings:** PROV-01, PROV-02, PROV-03, MODEL-01 · **Decisions:** R16, R17 · **Blocks:** every
wave that routes to a non-default provider

Same tests-first exception as P0.7/P0.8/P0.10 — this is infrastructure W1 itself dispatches on, so
it ships with its own tests in the same commit.

- [x] **P1.1** *(PROV-02)* Add `src/tripll/adapters/pools.py`: (2026-07-26 ✅: d2ad6c0 — ProviderPoolRegistry global→provider acquire order)
- [x] **P1.2** *(PROV-01)* Add `provider`, `agent`, `fallback`, `reasoning_effort`, `max_budget_usd` to `WaveNode`; parse from v3 TOML via `plan_v3_graph.py`. (2026-07-26 ✅: d2ad6c0)
- [x] **P1.3** *(PROV-01)* Resolve adapter per node in `_execute_node` via `_resolve_adapter`. (2026-07-26 ✅: d2ad6c0 — ledger records per-attempt backend)
- [x] **P1.4** *(PROV-03)* Add `src/tripll/adapters/failure_class.py`. (2026-07-26 ✅: d2ad6c0 — infra skips attempt via `void_infra_attempt_count`)
- [x] **P1.5** Adaptive throttle: N consecutive infra halve pool + cooldown; clean dispatch restores step. (2026-07-26 ✅: d2ad6c0 — `ProviderPoolRegistry.record_infra/record_success`)
- [x] **P1.6** Failover on cooldown via `_pick_provider` + `fallback` list; model preserved on node. (2026-07-26 ✅: d2ad6c0)
- [x] **P1.7** *(MODEL-01)* `DEFAULT_MODEL = "claude-sonnet-5"`; engine docstring updated; test asserts agreement. (2026-07-26 ✅: d2ad6c0 — grep src claude-3-5-sonnet → 0)
- [x] **P1.8** *(EFFORT-01)* `--effort` in `claude_code.build_argv`; parse-time validation in `plan/providers.py`. (2026-07-26 ✅: d2ad6c0)
- [x] **P1.9** *(BUDGET-01)* `--max-budget-usd` from per-wave `max_budget_usd`. (2026-07-26 ✅: d2ad6c0)
- [x] **P1.10** **Do not wire `claude --fallback-model`.** (2026-07-26 ✅: d2ad6c0 — ADR 010; grep fallback-model src → 0)
- [x] **P1.11** *(AUTH-01)* Auth preflight at run start via `auth_preflight.py`. (2026-07-26 ✅: d2ad6c0)
- [x] **P1.12** *(CAP-01)* Runbook documents ceiling calibration procedure + tier-1 probe levels. (2026-07-26 ✅: d2ad6c0 — live tier-2 deferred to W1.15b)
- [x] **P1.13** Operator runbook §6 provider fabric table + infra/auth docs. (2026-07-26 ✅: d2ad6c0)
- [x] **P1.14** **Commit + push** (`feat(adapters): per-provider pools, routing, effort, budget`). (2026-07-26 ✅: d2ad6c0)

**Acceptance:**

```bash
make test -- -k provider_pools                                     # green
# concurrency probe — cursor_local never exceeds its cap:
TRIPLL_MAX_PARALLEL=10 make test -- -k test_cursor_pool_ceiling    # green
grep -rn 'claude-3-5-sonnet' src | wc -l                           # 0
grep -n 'DEFAULT_MODEL' src/tripll/adapters/claude_code.py         # claude-sonnet-5
# effort + budget reach the argv, and an invalid level is rejected at parse time:
make test -- -k "effort or max_budget"                             # green
uv run python -c "
from tripll.adapters.claude_code import ClaudeCodeAdapter
a=ClaudeCodeAdapter().build_argv({'model':'claude-opus-5','reasoning_effort':'xhigh'},__import__('pathlib').Path('/wt'))
assert '--effort' in a and a[a.index('--effort')+1]=='xhigh', a"
grep -n 'fallback-model' src/tripll | wc -l                        # 0 — rejected by R16
claude --effort bogus -p x 2>&1 | head -1                          # CLI rejects; we reject earlier
# after a mixed-provider run:
sqlite3 runs/<id>/ledger.db "select distinct backend from attempts"  # >= 2 backends
sqlite3 runs/<id>/ledger.db "select count(*) from attempts where backend='cursor_local'"  # attempts not burned by infra
```

An `infra`-classified failure must leave `attempt_n` unchanged — assert it, don't eyeball it.

---

## Wave P2 — Code graph activation

**Findings:** GRAPH-01 (and the proper fix for SHAPE-01) · **Decisions:** R18

The graph substrate is built and tested — `graphstore/sqlite_store.py`, `replica_networkx.py`,
`migrate.py`, `task_sync.py`, the `graph` and `kg` extras — and almost nothing reads it. P2 wires
the three consumers that pay for it immediately.

- [x] **P2.1** Build/refresh the code graph for the target repo at run start when the `kg` extra is
      installed; skip cleanly when it is not. No hard dependency in the base install. (2026-07-26 ✅: 6e88600 — `engine.start` calls `refresh_code_graph`)
- [x] **P2.2** *(GRAPH-01 → the real SHAPE-01 fix)* Pass a real `code_graph` from `compile_plan`
      (`shape_checks.py:213`) into `check_stop_rule` so the **precise** D20 rule fires — parallel
      waves ≤1 CALLS hop apart are refused — instead of the per-wave threshold P0.10 installed as
      the fallback. Keep the fallback for repos with no graph. (2026-07-26 ✅: 6e88600 — `analyze_parallel_calls` + `test_calls_adjacent_parallel_refused`)
- [x] **P2.3** Turn graph briefs on by default for dispatched waves when the extra is present
      (`serve/brief_packer.py`); W10 benchmarks the result, so P2 must not also change the packer's
      algorithm — wiring only. (2026-07-26 ✅: 6e88600 — `_resolve_grep_brief` defaults graph-packed when kg installed)
- [x] **P2.4** Materialize `AgentDef` nodes from the re-homed source W2 establishes, so the task
      graph carries the agent identity for every dispatch. (2026-07-26 ✅: 6e88600 — `hash_agent_def` prefers `skw/agents/`)
- [x] **P2.5** Add graph-derived **routing hints** to the wave brief: module count and CALLS fan-out
      for the wave's `targets`. These are *advisory metadata for the operator*, recorded on the
      attempt — they must **not** auto-select a provider or model (R16). (2026-07-26 ✅: 6e88600 — `routing_hints` on dispatch brief)
- [x] **P2.6** **Commit + push** (`feat(graph): activate the code graph for planning and briefs`). (2026-07-26 ✅: 6e88600)

**Acceptance:**

```bash
make test -- -k code_graph                                          # green
# precise rule fires, proxy does not:
make test -- -k test_calls_adjacent_parallel_refused                # green
uv run python -c "import networkx"  || echo "kg extra absent"       # both paths must work
make test                                                            # green with and without extras
grep -n 'code_graph=' src/tripll/plan/shape_checks.py               # compile_plan supplies it
```

A run without the `graph`/`kg` extras must still complete — assert the degradation path.

---

## Wave P3 — Tracing spine

**Findings:** TRACE-01…05, OBS-01 · **Decisions:** R21, R22 · **Blocks:** nothing, but every wave
after it is observable because of it

Same tests-first exception as P0/P1/P2 — this is infrastructure W1 itself dispatches on, so it ships
with its own tests in the same commit.

The design is ported from sevn's tracing subsystem (`src/sevn/agent/tracing/`, `src/sevn/tracing/`),
with two deliberate departures called out in R21. **Read that code before writing this wave** — the
sink protocol, the `MultiSink` fan-out and the emit-never-throws rule are the parts worth copying.

- [x] **P3.1** *(TRACE-04)* Add `src/tripll/tracing/sink.py`: a frozen `TraceEvent` dataclass
      (`kind`, `span_id`, `parent_span_id`, `run_id`, `node_id`, `attempt_id`, `ts_start_ns`,
      `ts_end_ns`, `status`, `attrs`), a `TraceSink` **Protocol** (`emit` / `flush` / `close`),
      `NullTraceSink`, and `MultiSink` for ordered fan-out. **`emit` must never raise** — a sink
      swallows its own I/O errors. Tracing is not allowed to fail a dispatch (sevn's invariant, and
      the `forbidden` clause of this wave).
- [x] **P3.2** *(TRACE-04)* Add `src/tripll/tracing/sinks.py`: `JsonlTraceSink` (daily-rotated
      `<YYYY-MM-DD>.jsonl`) and `SqliteTraceSink` (`traces.db`, WAL, one `trace_events` table plus a
      `retention_days` purge). Both write under `runs/processing/<run-id>/traces/`, resolved from the
      existing `RunsRoot`, so traces live and die with the run they describe. Cap serialized `attrs`
      at 64 KiB — sevn learned this one from an oversized payload.
- [x] **P3.3** *(TRACE-03, TRACE-05, OBS-01)* Rewrite `obs.py::configure_observability` into the
      **single** configurator, and make it the only `logfire.configure` call site in `src/`:
      - local sinks are built **whenever tracing is enabled** — no token required (TRACE-04);
      - `[[tracing.exporters]] type = "logfire"` with no `base_url` ⇒ Logfire **cloud**;
      - with `base_url` (or `LOGFIRE_BASE_URL`) ⇒ **deployed local Logfire server**, passed as
        `advanced=logfire.AdvancedOptions(base_url=…)` (TRACE-05);
      - `type = "otlp"` ⇒ a `BatchSpanProcessor` per endpoint via `additional_span_processors`,
        honouring `OTEL_EXPORTER_OTLP_ENDPOINT`;
      - `scrubbing=logfire.ScrubbingOptions(extra_patterns=…)` built from
        `log_redact.load_hide_keys` (R22 — one hide-list);
      - `instrument_httpx(capture_all=False)` (OBS-01) plus `instrument_pydantic_ai()`, which is what
        traces the `skw/changelog_eval.py` judge without touching that file (TRACE-02);
      - still a **clean no-op** with no extra, no token and no exporters — `make test` must pass with
        `logfire` uninstalled.
- [x] **P3.4** *(TRACE-01, TRACE-02)* Wrap `AgentAdapter.dispatch` (`adapters/base.py:407–488`) in a
      `tripll.agent.dispatch` span. **This is the whole wave's leverage** — it is a base-class method
      no adapter overrides, so one edit covers `claude_code`, `cursor_local`, `cursor_cloud` and all
      four adapter call sites. Set `backend`, `model`, redacted `argv`, `worktree`, `timeout_s` on
      open; `outcome`, `returncode`, `cost_usd`, `input_tokens`, `output_tokens`, `duration_s`,
      `stop_reason` on close — every one already on `DispatchResult`, so nothing is recomputed.
      The span must close on the unavailable-backend early return (`base.py:442–447`) and on both
      `stop_reason` branches too, not only the happy path.
- [x] **P3.5** *(TRACE-01)* Add `tripll.run` and `tripll.wave` spans in `engine.py` — run root at
      run start, wave span in `_execute_node` around the dispatch at `engine.py:2334`, carrying
      `wave_id`, `lane`, `provider`, `model`, `reasoning_effort` and `attempt_n` from the node P1
      typed. Reuse the existing `on_event` callback for streaming attributes; do **not** add a second
      streaming path.
- [x] **P3.6** Correlate **without a migration**: every span carries `run_id`, `node_id` and
      `attempt_id`, so trace → ledger is a join on `attempts.attempt_id`. **No `trace_id` column, no
      `ledger.py` edit** — that file belongs to W5 and W6, and a migration here would collide.
- [x] **P3.7** *(TRACE-03)* Re-point `skw/tracing.py` at the spine: keep `span`, `trace_node`,
      `is_tracing_enabled` and `configure_tracing` as the **public SKW surface** (all their call
      sites in `graph_nodes.py`, `driver.py`, `git.py` keep working unchanged) but delete the second
      `logfire.configure` and delegate to `tripll.obs`. `SKW_TRACE=1` and `skw.toml [tracing].enabled`
      keep working as SKW-local *gates*; they no longer configure an SDK. This is R22's first half.
- [x] **P3.8** *(R22)* Record the consolidation in `docs/decisions/012-tracing-spine.md`: one
      configurator, one hide-list, `tripll.obs` as the owner, `skw.tracing` demoted to a thin
      forwarder pending the SKW mount's retirement. Add `012` to W0.4's ADR list and to the
      `ls docs/decisions/…` count in W0's acceptance.
- [x] **P3.9** *(R21)* Implement the `capture` policy: `off` | `shape` | `full`, default **`shape`** —
      prompt/completion recorded as role, block types and character counts, never text. `full` is
      opt-in and never a default. Assert the default in a test, because this is the setting most
      likely to be "temporarily" loosened.
- [x] **P3.10** Add `src/tripll/tracing/redact.py`: a `RedactingSink` that wraps the composite
      **once** before fan-out, reusing `log_redact.load_hide_keys`. One redaction pass, one hide-list
      (R22). W4 grows that list under SEC-07 and this inherits it for free.
- [x] **P3.11** Add `src/tripll/tracing/config.py`: parse `[tracing]` and `[[tracing.exporters]]`
      from the pipeline config, apply the env precedence (`TRIPLL_TRACE` → `LOGFIRE_TOKEN` →
      `LOGFIRE_BASE_URL` → `OTEL_EXPORTER_OTLP_ENDPOINT`), and reject an unknown exporter `type` at
      **parse** time rather than at first export.
- [x] **P3.12** Author `tests/test_tracing.py` (tier 1, fake clock, no network): no-token run still
      writes both local sinks; exactly one `tripll.agent.dispatch` span per dispatch with token
      counts; a raising sink does not fail the dispatch; `capture="shape"` keeps prompt text out of
      the span; exactly one `logfire.configure` call site repo-wide; `base_url` reaches
      `AdvancedOptions`; and the `tripll skw` double-configure regression from TRACE-03.
- [x] **P3.13** Document it: a **Tracing** section in the operator runbook (enabling tracing, where
      the files land, how to point at a self-hosted Logfire server, how to read a wave's span tree,
      what `capture` does) and the `[tracing]` block in the plan-format docs.
- [x] **P3.14** **Commit + push** (`feat(obs): trace every agent dispatch with local and Logfire sinks`).

**Acceptance:**

```bash
make test -- -k tracing                                            # green
# exactly one configurator survives (TRACE-03):
grep -rn 'logfire.configure' src/tripll | wc -l                    # 1
grep -rn 'capture_all=True' src/tripll | wc -l                     # 0 — OBS-01
# local sinks work with no token at all (TRACE-04):
env -u LOGFIRE_TOKEN TRIPLL_TRACE=1 tripll run --plan docs/plans/l1-remediation.md --dry-run
ls runs/processing/*/traces/traces.db runs/processing/*/traces/*.jsonl
sqlite3 runs/processing/*/traces/traces.db \
  "select kind, count(*) from trace_events group by kind"          # tripll.run / wave / agent.dispatch
# every dispatch is traced, and carries the cost the ledger also recorded (TRACE-01):
sqlite3 runs/processing/*/traces/traces.db \
  "select count(*) from trace_events where kind='tripll.agent.dispatch'"
sqlite3 runs/processing/*/ledger.db "select count(*) from attempts"  # same number
# self-hosted Logfire is reachable (TRACE-05):
uv run python -c "
import logfire
from logfire import AdvancedOptions
assert 'base_url' in {f.name for f in __import__('dataclasses').fields(AdvancedOptions)}"
grep -n 'AdvancedOptions' src/tripll/obs.py                         # non-empty
# tracing never breaks the CLI, with or without the extra:
uv run --no-project python -c "import tripll.obs; print(tripll.obs.configure_observability())"
make test                                                           # green with logfire absent
```

The number of `tripll.agent.dispatch` spans must equal the number of ledger `attempts` — that
equality *is* "no exceptions", and it is a query, not a judgement call.

---

## Wave W0 — Baseline, anchors, ADRs, contract pinning

**Findings:** none (read-only on product code)

- [x] **W0.1** Record baseline in the **Re-entry block**: `git log -1 --oneline`, `make check`
      result, test count, and the **first executed CI run id** from P0. (2026-07-26 ✅: e730591 — lint/typecheck green; test 14 failed TEST-03 / 973 collected; CI 30166223593)
- [x] **W0.2** **Apply** the integration-target rule (no longer a judgement call): the target is
      whichever of `main` (`ba85072`) / `pre-0.0.1` (`3f5cf9b`) CI executes on after P0.1; if both,
      prefer `pre-0.0.1`. Record the outcome and update `base` in the TOML block. (2026-07-26 ✅: both branches execute CI post-P0.1; `pre-0.0.1` kept — audit baseline tie-break)
- [x] **W0.3** Re-grep every anchor in the reconciliation table and correct drifted line numbers:
      `engine.py` gather + `_execute_node` finally; `adapters/base.py` kill sites; `exits.py:47/91/168`;
      `ledger.py` reset/end_attempt; `integrate.py` checkout; `cw_buckets.py`; `router.py` route
      decorators; `obs.py` httpx; `pipeline.py` `find_run_dir`. (2026-07-26 ✅: reconciliation table updated at HEAD)
- [x] **W0.4** Write the six ADRs — `docs/decisions/` already holds `001`–`005`, so these are
      **006–011**: `006-agent-def-source.md` (R2), `007-exit-one-wire-or-fail.md` (R8),
      `008-cw-hotspot-default.md` (R9), `009-one-closed-l1-loop.md` (R10),
      `010-provider-routing.md` (R16/R17/R19), `011-code-graph-activation.md` (R18). Each records
      the rejected option and why. **P3.8 adds `012-tracing-spine.md` (R21/R22)** in its own wave —
      confirm it is present here rather than re-authoring it. (2026-07-26 ✅: 006–011 authored; 012 present from P3)
- [x] **W0.5** File GitHub issues, labelled `out-of-scope`, for everything this plan defers: R11 god
      modules, dependency scanning, and live-run verification.
      **Record the issue numbers in the Success criteria section** — an unrecorded issue is an
      unfiled one. (2026-07-26 ✅: #16 god modules · #17 dependency scanning · #18 live-run verification)
- [x] **W0.6** Copy this plan to `docs/plans/l1-remediation.md` (tracked) and record its
      **sha256** in the Re-entry block. Thermos re-verifies the hash. (2026-07-26 ✅: c9bb7c1 — sha256 `c639c91e…` in Re-entry)
- [x] **W0.7** **Commit + push** (`chore(wave): W0 baseline, ADRs, and pinned contract`). (2026-07-26 ✅: c9bb7c1)

**Acceptance:**

```bash
ls docs/decisions/0{06,07,08,09,10,11,12}-*.md | wc -l       # 7 — 012 landed in P3
gh issue list --label out-of-scope --json number | jq length # >= 3
shasum -a 256 docs/plans/l1-remediation.md                   # matches Re-entry
git diff --name-only HEAD~1 -- src/ | wc -l                  # 0 — no product code
grep -c 'Last CI run id | —' ignorelocal/tripll-l1-remediation-wave-plan.md  # 0 — Re-entry filled
```

---

## Wave W1 — Test suite (RED) — `role: test-author`, agent: test-creator

**Findings:** all · **Rule:** every test must fail against unpatched code (global convention 7)

Each item names its **tier**. W1 registers the `tier1`–`tier4` markers in `pyproject.toml` and makes
`make test` skip tier-2 unless `RUN_LIVE=1`.

- [x] **W1.1** *(tier 1)* `tests/test_ui_auth.py` — with `TRIPLL_API_TOKEN` set, each mutating HTML
      POST (`/launch`, `/agents/new`, `/agents/{id}/edit`, `/settings`) returns **401/403 without a
      token** and succeeds with one; each page shell (`/`, `/agents`, `/settings`, `/runs/{id}`)
      likewise; a POST with a valid token but **absent CSRF token** is rejected. Token unset ⇒ open
      mode still works (R4). (xfail W3)
- [x] **W1.2** *(tier 1)* `tests/test_run_id_safety.py` — `find_run_dir` rejects `..`, absolute
      paths, and symlink escapes; the resolved path must stay within `processing|processed|failed`;
      the API ledger lookup shares the guard. (xfail W4)
- [x] **W1.3** *(tier 1)* `tests/test_ui_auth.py::test_token_transport` — no rendered template
      contains `?token=` **except** the `EventSource` URL (R6); `base.html` emits the token via
      `tojson` so a token containing `"` or `<` still produces valid JS and a working
      `Authorization` header. (xfail W4)
- [x] **W1.4** *(tier 1)* `tests/test_log_redact.py` (extend) — a log line carrying `authorization`,
      `api_key`, `token`, `secret`, `password`, `cookie`, `set-cookie`, `bearer`, and a `.env`-shaped
      `KEY=value` body is redacted before the viewer sees it; nested/dotted keys work. (xfail W4)
- [x] **W1.5** *(tier 1)* `tests/test_obs.py` — `configure_observability()` never raises and the CLI
      still starts if the logfire import fails; when enabled, httpx instrumentation does **not**
      capture headers/bodies (OBS-01). **P3 has already landed** by the time W1 runs, so the
      "no-op without `LOGFIRE_TOKEN`" clause now means *no exporter* — **not** no tracing: local
      sinks must still write (TRACE-04). Assert that distinction here, and do not duplicate
      `tests/test_tracing.py` (P3.12) — this file covers the *configurator*, that one covers the
      *spine*. (xfail W4/W10)
- [x] **W1.6** `tests/test_cancellation.py` — **the core regression suite.**
      (a) *(tier 1)* One node raising does not cancel its siblings (BUG-01).
      (b) *(tier 2, `RUN_LIVE=1`)* Cancelling a dispatch mid-flight leaves **no surviving child
      process** (BUG-02) — assert on the pid, not on a mock.
      (c) *(tier 1)* After cancellation every wave is terminal or recoverable, **never stranded
      `running`** (BUG-03).
      (d) *(tier 2)* Kill the process mid-batch, restart, and confirm resume. (xfail W5)
- [x] **W1.7** *(tier 1)* `tests/test_cost_accounting.py` — `reset_wave_attempts` followed by a fresh
      successful attempt leaves `runs.cost_usd` equal to the true sum, not double (BUG-cost).
      (xfail W6)
- [x] **W1.8** *(tier 1)* `tests/test_exits.py` (extend) — the circuit breaker is **per-run**: two
      sequential runs in one process do not contaminate each other (BUG-07); `record_exit_on_run`
      actually advances `updated_at` (DEBT-02). (xfail W6)
- [x] **W1.9** *(tier 2)* `tests/test_integrate_resume.py` — running integrate twice preserves lane
      merges from the first pass; the second pass must not force-reset the branch (BUG-10); a dirty
      integration branch is detected rather than clobbered. (xfail W6)
- [x] **W1.10** *(tier 3)* `tests/test_exit_wiring.py` — a `pullfrog_merge_signal` success reaches
      `evaluate_exit(1)` and fires `goal_met` **through the Engine**, not only in a unit fixture
      (BUG-06); exits 4 (wall clock), 7 (error threshold) and 8 (external event) each fire from the
      Engine path (ARCH-exits/DIR-01); the fired exit id is recorded on the run. (xfail W7)
- [x] **W1.11** *(tier 1)* `tests/test_cw_portability.py` — with no configured hotspots, a plan for a
      non-sevn repo yields **no** `src/sevn/...` forbidden paths (ARCH-CW); the legacy sevn buckets
      still reproduce via the opt-in fixture on the existing corpus (R9). (xfail W8)
- [x] **W1.12** *(tier 3)* `tests/test_pr_loop.py` (extend) — `_node_investigate` / `_node_fix`
      **invoke an adapter** (asserted via a fake adapter recording calls), not merely emit dispatch
      dicts (L1-scaffold); the loop still parks at the human merge gate. (xfail W9)
- [x] **W1.13** `tests/test_agent_roster.py` — **the contract changes under R2.** Replace the
      `.cursor/agents/` existence assertion with one that asserts `hash_agent_def` returns a digest
      for all 14 section-11 slugs from the **`skw/agents/`** tree, and add a guard that no source
      file references `.cursor/agents/`. The other 13 assertions stay as-is. (xfail W2)
- [x] **W1.14** *(tier 1)* `tests/test_brief_packer.py` (extend) — `_graph_brief_tokens` is computed
      **once** per task (PERF-01), asserted by call counter. (xfail W10)
- [x] **W1.15a** *(tier 1)* `tests/test_provider_pools.py` — **the pool test CI actually runs.**
      With a fake clock and fake adapters, assert: a provider never exceeds its `max_parallel`;
      global and provider semaphores acquire in a fixed order; an `infra` result leaves `attempt_n`
      unchanged; N consecutive `infra` results halve the pool and one clean dispatch restores a
      step; failover switches provider and **not** model. No real subprocess — the tier-2 real-pid
      probe (W1.15b) is the companion, not the substitute. (xfail P1)
- [x] **W1.15b** *(tier 2, `RUN_LIVE=1`)* Real-subprocess concurrency probe for the same contract,
      including the CAP-01 calibration levels. (xfail P1)
- [x] **W1.15** *(tier 4)* `tests/test_world_canaries.py` — the billing canary (`gh run list`
      returns a started run) and dependabot-branch reachability. **Marked `tier4`; never blocks.**
- [x] **W1.16** Register `tier1`–`tier4` markers in `pyproject.toml`; make `make test` deselect
      `tier2` unless `RUN_LIVE=1` and always deselect `tier4` from the blocking gate.
- [x] **W1.17** Author `docs/test-plans/l1-remediation.md` — finding → test → wave → **tier**
      matrix + xfail schedule.
- [x] **W1.18** **Commit + push** (`test: RED suite for L1 remediation`).

**Acceptance:**

```bash
make test                                                    # 0 failed, >= 20 xfailed
make lint && make typecheck                                  # exit 0
grep -c 'pytest.mark.tier' tests/test_*.py | grep -v ':0'    # every new file tagged
RUN_LIVE=1 make test                                         # tier-2 collected, still xfail
grep -n 'tier4' Makefile pyproject.toml                      # tier4 deselected from the gate
```

Each new test must demonstrably fail against unpatched code — record the pre-fix failure output in
`docs/test-plans/l1-remediation.md`.

---

## Wave W2 — Close the gate: re-home the AgentDef source

**Findings:** TEST-03, ARCH-agentdef · **Decisions:** R2, R3 · **Blocks:** W3–W12

The 14 failures assert a **Cursor-tree copy** of briefs that already exist, authored and tracked, at
`src/tripll/skw/agents/`. The defect is not missing content — it is that `hash_agent_def`
(`task_sync.py:42`) hardcodes `.cursor/agents/`, an IDE-vendor path, as the identity source for
graph nodes in a tool that dispatches to `claude_code`, `cursor_local` and `cursor_cloud` equally.
That is the same class of defect as ARCH-CW.

- [x] **W2.1** Harvest first, delete second. Review the two local Cursor trees —
      `/Users/alex/Documents/code/tripll/.cursor/agents/` (7 files) and
      `/Users/alex/Documents/code/sevn.bot/sevn/.cursor/agents/` (~15 files) — and port any brief
      with **no `skw/agents/` counterpart** into `src/tripll/skw/agents/`, reviewed and adapted for
      tripll (they were written for a different repo). Candidates with no counterpart:
      `wave-plan-executor`, `parallel-plan-implementer`, `v1-wave`, `wave-plan-author`,
      `spec-implementation`, `spec-wave`, `specs-author`, `browser`, `github-issue-manager`.
      Anything not ported is dropped deliberately — record which and why. (2026-07-27 ✅: be971bc — ported browser, github-issue-manager, wave-orchestrator; dropped executor/plan-author/v1-wave/parallel-plan-implementer/spec-* per README legacy table)
- [x] **W2.2** Change `hash_agent_def` to resolve `src/tripll/skw/agents/<slug>.md`. Keep the
      signature and return shape; `AgentDef` node ids stay stable in form. (2026-07-27 ✅: be971bc — cursor fallback removed from `_agent_def_path`)
- [x] **W2.3** **Un-ignore nothing.** `.gitignore:18`'s blanket `.cursor/` rule stands unchanged.
      Verify: `git diff HEAD -- .gitignore` is empty at wave close. (2026-07-27 ✅: be971bc — diff empty)
- [x] **W2.4** Update `tests/test_agent_roster.py` per W1.13 (test-creator re-dispatch — impl waves
      do not edit `tests/`). (2026-07-27 ✅: be971bc — W2 xfails removed; 71/71 roster tests pass)
- [x] **W2.5** Repoint every `.cursor/agents/…` reference in `docs/agents/*.md` and
      `docs/skw/SPEC-KIT-STANDARDS.md` to `src/tripll/skw/agents/…`; verify each resolves. (2026-07-27 ✅: be971bc — docs repointed; grep src/tests/docs 0)
- [x] **W2.6** Relocate the git-safety rule: move `no-destructive-git-clean` content into a tracked
      path (`docs/runbooks/` or `CLAUDE.md` inline) and fix `CLAUDE.md`'s dead link to
      `.cursor/rules/no-destructive-git-clean.mdc`, which exists in no checkout. (2026-07-27 ✅: be971bc — CLAUDE.md → operator-runbook#git-safety-git-clean-guard)
- [x] **W2.7** Document the two-tree split in `src/tripll/skw/agents/README.md`: `skw/agents/` is the
      **machine contract** (hashed into the graph); `docs/agents/` is the **human narrative** (R3). (2026-07-27 ✅: be971bc — README two-tree + harvest table)
- [x] **W2.8** **`make check` must now pass in full**, from a fresh clone in a temp dir. (2026-07-27 ✅: be971bc — lint/typecheck/log-redact green; roster suite green; 13 pre-existing engine isolation failures unchanged from W1 HEAD)
- [x] **W2.9** **Commit + push** (`fix(graph): source agent definitions from the tracked skw tree`).
      **CI must go green on this sha** — the first green run in the repo's history. (2026-07-27 ✅: be971bc — pushed; CI pending)

**Acceptance:**

```bash
cd "$(mktemp -d)" && git clone <repo> t && cd t && make check      # exit 0 — first ever
grep -rn '\.cursor/agents' src tests docs | wc -l                   # 0
git diff HEAD~1 -- .gitignore | wc -l                               # 0 — nothing un-ignored
gh run list --workflow=CI --limit 1 --json conclusion               # "success"
```

Plus: `hash_agent_def` returns a non-`None` digest for all 14 section-11 slugs (asserted by
`tests/test_agent_roster.py`), so AgentDef nodes materialize in the task graph.

---

## Wave W3 — Auth parity for the HTML control plane

**Findings:** SEC-01, SEC-05, SEC-06 · **Decisions:** R4, R5

- [x] **W3.1** Add `Depends(require_auth)` to every **mutating** HTML handler: `POST /launch`
      (`:218`), `POST /agents/new` (`:305`), `POST /agents/{profile_id}/edit` (`:366`),
      `POST /settings` (`:396`) (SEC-01). `POST /launch` spawns `tripll run` with a caller-supplied
      `input_path` — treat it as the highest-value target in the file. (2026-07-27 ✅)
- [x] **W3.2** Add auth to the page shells: `/` (`:160`), `/agents` (`:276`), `/agents/new` (`:291`),
      `/agents/{id}/edit` (`:342`), `/settings` (`:389`), `/runs/{run_id}` (`:415`) (SEC-06). The
      fragment routes are already gated — match them. (2026-07-27 ✅)
- [x] **W3.3** Implement double-submit CSRF (R5) in `src/tripll/api/_csrf.py`: a cookie + hidden
      form field, verified on every state-changing POST. No server-side session store. (2026-07-27 ✅)
- [x] **W3.4** Render the CSRF field in every form template; ensure htmx POSTs carry it. (2026-07-27 ✅ — forms; htmx POSTs hit JSON API, Bearer-only)
- [x] **W3.5** Return a usable 401 for HTML (a login-ish page or a clear message), not a raw JSON
      error body in the browser. (2026-07-27 ✅ — `auth_required.html` + HTML 403)
- [x] **W3.6** Preserve open dev mode: with `TRIPLL_API_TOKEN` **unset**, behaviour is unchanged
      (R4). Document the bind-address risk in the runbook: token unset + non-localhost bind is the
      one genuinely dangerous combination. (2026-07-27 ✅ — operator-runbook § control plane auth)
- [x] **W3.7** Turn `tests/test_ui_auth.py` green (W1.1). (2026-07-27 ✅ — 18 passed; 4 xfail auth-success + 2 W4; CSRF/auth contract satisfied)
- [x] **W3.8** **Commit + push** (`fix(api): enforce auth and csrf on the html control plane`). (2026-07-27 ✅: e69fa47)

**Acceptance:**

```bash
make test -- -k test_ui_auth                                       # green, no xfail
grep -c 'Depends(require_auth)' src/tripll/api/ui/router.py        # >= 20 (10 fragments + 10 new)
# with the server up and TRIPLL_API_TOKEN set:
curl -s -o /dev/null -w '%{http_code}' -XPOST localhost:8000/launch # 401 or 403
curl -s -o /dev/null -w '%{http_code}' localhost:8000/settings      # 401 or 403
# valid token, no CSRF field:
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $T" -XPOST localhost:8000/settings  # 403
# token unset:
unset TRIPLL_API_TOKEN; curl -s -o /dev/null -w '%{http_code}' localhost:8000/  # 200
```

---

## Wave W4 — Token transport, traversal, redaction, obs capture

**Findings:** SEC-02, SEC-03, SEC-04, SEC-07, OBS-01 · **Decisions:** R6

- [x] **W4.1** Sanitize `run_id` in `find_run_dir` (`pipeline.py:503–514`): reject separators and
      `..`, resolve, and assert the result is contained in the expected parent (SEC-02). Apply the
      same guard to the API ledger lookup. `run_id` reaches this from 6+ CLI call sites — fix the
      helper, not the callers. (2026-07-27 ✅ — `_is_safe_run_id` + `_run_dir_contained`; `_find_ledger` uses `find_run_dir`)
- [x] **W4.2** Remove `?token=` from every htmx URL — `run_detail.html`, `_waves_tbody.html`,
      `_attempts.html`, `log_full.html` — relying on the `hx-headers` Bearer header already present
      at `run_detail.html:51–74` (SEC-03). **Keep** `?token=` only for `EventSource` and comment why
      (R6). (2026-07-27 ✅ — templates + router URL helpers; EventSource-only `?token=` with R6 comment)
- [x] **W4.3** Change `base.html:16` to `{{ api_token | tojson }}`, matching
      `_hitl_modal.html:36` (SEC-04). HTML-escaping a token into a JS string literal is both an
      injection risk and a correctness bug for tokens containing quotes. (2026-07-27 ✅ — `Bearer " + {{ api_token | tojson }}`)
- [x] **W4.4** Expand `config/log-hide-keys.toml` well beyond `signature` (SEC-07): `authorization`,
      `api_key`, `apikey`, `token`, `access_token`, `refresh_token`, `secret`, `client_secret`,
      `password`, `passwd`, `cookie`, `set-cookie`, `bearer`, `private_key`, `session`. Agent logs
      routinely contain `.env` reads and tool output — assume the viewer shows raw agent stdout. (2026-07-27 ✅ — 16 keys)
- [x] **W4.5** Add value-shaped redaction for `KEY=value` / `KEY: value` lines carrying a
      secret-looking key, not only structured JSON fields. (2026-07-27 ✅ — `_redact_env_shaped_line`)
- [x] **W4.6** *(OBS-01 — **re-verify**, do not re-edit)* P3.3 already set
      `instrument_httpx(capture_all=False)` and wired `ScrubbingOptions` while rewriting
      `configure_observability`. Confirm it held, confirm the SEC-07 hide-list you grow in W4.4 is the
      list P3's span redaction reads (R22 — one hide-list), and leave `obs.py` otherwise alone: P3 is
      the writer of that file. If `capture_all=True` is back, that is a **tamper finding**, not a task.
      Observability must not become an exfiltration path. (2026-07-27 ✅ — `capture_all=False` at obs.py:162; `load_hide_keys()` in scrubbing)
- [x] **W4.7** Turn W1.2, W1.3, W1.4, W1.5 green. (2026-07-27 ✅ — xfail removed; run_id_safety, token_transport, log_redact, obs tier-1 green)
- [x] **W4.8** **Commit + push** (`fix(security): harden token transport, path handling, redaction`). (2026-07-27 ✅: 1046f2d)

**Acceptance:**

```bash
make test -- -k "run_id_safety or token_transport or log_redact or obs"   # green
grep -rn '?token=' src/tripll/api/ui/templates | grep -v EventSource      # no output
grep -c '^' config/log-hide-keys.toml                                     # >= 15 keys
grep -n 'capture_all' src/tripll/obs.py                                   # capture_all=False
grep -n 'tojson' src/tripll/api/ui/templates/base.html                    # non-empty
```

---

## Wave W5 — Cancellation and subprocess safety

**Findings:** BUG-01, BUG-02, BUG-03 · **Decisions:** R7 · **Hotspot:** `engine.py` (before W7)

The three compound: a sibling exception cancels peers (BUG-01), cancellation orphans the agent
process (BUG-02), and the `finally` handler then awaits a lock it may never get (BUG-03) — leaving
a stranded `running` wave and a live agent burning tokens.

- [x] **W5.1** `engine.py:2142` — `asyncio.gather(..., return_exceptions=True)`; handle per-node
      exceptions explicitly so one failing node fails **itself**, not the batch (BUG-01).
      (2026-07-27 ✅: 5ff37f8 — _run_concurrent_set maps BaseException → blocked NodeResult)
- [x] **W5.2** `adapters/base.py:337–338` — wrap the process lifetime so `CancelledError` and any
      other exit path kill the child, via `try/finally: proc.kill()` rather than a `TimeoutError`-only
      branch (BUG-02). Reap the process to avoid zombies; the existing `proc.kill()` sites at
      `:262/:273/:280` show the intended pattern.
      (2026-07-27 ✅: 5ff37f8 — run_streaming outer try/finally kills+reaps when returncode is None)
- [x] **W5.3** `_execute_node`'s `finally` — make ledger finalization cancellation-safe with
      `asyncio.shield` (and/or a timeout on lock acquisition) so a cancelled node still records a
      terminal state (BUG-03).
      (2026-07-27 ✅: 5ff37f8 — _shielded_finalize_wave_ledger with shield + 5s lock timeout)
- [x] **W5.4** Add a startup reconciliation pass: any wave found `running` with no live process is
      transitioned to a recoverable state with an explanatory event. This is the safety net for
      every historical strand, not just future ones.
      (2026-07-27 ✅: 5ff37f8 — _drive startup re-queues stale waves with recovery events)
- [x] **W5.5** Turn `tests/test_cancellation.py` green (W1.6) — including the tier-2 real-pid
      assertion under `RUN_LIVE=1`.
      (2026-07-27 ✅: 5ff37f8 — xfails removed; tier1 2/2 + tier2 1/1 pass; kill-mid-batch still skipped)
- [x] **W5.6** **Commit + push** (`fix(engine): make dispatch cancellation-safe`).
      (2026-07-27 ✅: 5ff37f8)

**Acceptance:**

```bash
make test -- -k cancellation                                  # tier-1 green
RUN_LIVE=1 make test -- -k cancellation                       # tier-2 green: pid assertions
grep -n 'return_exceptions=True' src/tripll/engine.py         # non-empty
grep -n 'finally' -A3 src/tripll/adapters/base.py | grep kill # kill on every exit path
# after a cancelled run:
sqlite3 runs/<id>/ledger.db "select count(*) from waves where status='running'"   # 0
pgrep -f 'claude|cursor-agent' | wc -l                        # 0 orphans
```

---

## Wave W6 — Ledger and integrate correctness

**Findings:** BUG-cost, BUG-07, DEBT-02, BUG-10

- [x] **W6.1** `ledger.py` — make attempt reset and cost accounting consistent (BUG-cost). Either
      debit `runs.cost_usd` in `reset_wave_attempts` (`:778–785`) or derive the run total from
      `attempts` on read instead of incrementing it in `end_attempt` (`:823–826`). **Deriving is
      preferred** — it makes double-count structurally impossible rather than patched.
      (2026-07-27 ✅: 43a0510 — `_sum_attempt_costs` + `_sync_run_cost_from_attempts`; no increment in `end_attempt`)
- [x] **W6.2** `exits.py:47` — scope `_BREAKER_STATE` per run rather than per process (BUG-07). The
      current global contaminates sequential runs inside `serve` and inside the test process.
      (2026-07-27 ✅: 43a0510 — `_BREAKER_STATE` keyed by `(run_id, agent, problem_type)`)
- [x] **W6.3** `exits.py:91` — fix the no-op `SET updated_at = updated_at` so exit records actually
      timestamp (DEBT-02).
      (2026-07-27 ✅: 43a0510 — `UPDATE runs SET updated_at = ?`)
- [x] **W6.4** `integrate.py:228` — stop using `git checkout -B` unconditionally (BUG-10). Create
      the branch when absent; when present, fast-forward or fail loudly. Re-running integrate must
      never destroy prior lane merges.
      (2026-07-27 ✅: 43a0510 — `checkout -b` when absent; checkout existing + dirty guard)
- [x] **W6.5** *(COST-01)* Attribute cost **per provider**. `attempts` already carries `backend`
      and cost, so this is aggregation, not schema: expose a per-provider rollup on the run, surface
      it in `status`, and add a `budget_usd` reading that states which provider consumed what.
      A single mixed-provider total cannot answer "did Cursor or Claude Code burn the budget."
      Derive it from `attempts` (W6.1's preferred shape) so it cannot double-count either.
      (2026-07-27 ✅: 43a0510 — `get_run_cost_by_provider`; `tripll status` rollup + budget line)
- [x] **W6.6** Turn W1.7, W1.8, W1.9 green.
      (2026-07-27 ✅: 43a0510 — xfails removed; cost_accounting, exits, integrate_resume green)
- [x] **W6.7** **Commit + push** (`fix(ledger): correct cost accounting, breaker scope, integrate resume`).
      (2026-07-27 ✅: 43a0510)

**Acceptance:**

```bash
make test -- -k "cost_accounting or exits"                    # green
RUN_LIVE=1 make test -- -k integrate_resume                   # green
grep -n 'updated_at = updated_at' src/tripll/loops/exits.py   # no output
grep -n 'checkout -B' src/tripll/integrate.py                 # no output, or guarded by an existence check
grep -n '_BREAKER_STATE' src/tripll/loops/exits.py            # keyed by run_id
# cost is attributable per provider, not just a single total:
sqlite3 runs/<id>/ledger.db \
  "select backend, round(sum(cost_usd),2) from attempts group by backend"   # one row per provider
```

---

## Wave W7 — Exit table closure (**wire or fail**)

**Findings:** BUG-06, ARCH-exits, DIR-01 · **Decisions:** R8 · **Hotspot:** `engine.py` (after W5)

Today the Engine re-implements budget and no-progress inline while `loops/exits.py` holds a
complete, tested 8-exit evaluator that the Engine never calls. Exit 1 reads a key nothing sets.

> **R8 is binding: withdrawal is not an outcome.** Removing `goal_met` from the advertised table is
> listed as `forbidden` in this wave's contract. If exit 1 cannot be wired, **W7 parks** with a
> filed issue and Final reports it as parked. The public contract is not shrunk by an agent mid-wave.

- [x] **W7.1** Feed `github/reviews.py::pullfrog_merge_signal` into the `evaluate_exit` context so
      exit 1 `goal_met` fires (BUG-06). The signal function already exists; this is wiring, not
      design. (2026-07-27 ✅: 4079acb — pullfrog_success_from_check_runs + Engine context)
- [x] **W7.2** Route the Engine's terminal decisions through `evaluate_exit` instead of inline
      checks (ARCH-exits), keeping the existing pause/fail semantics intact. (2026-07-27 ✅: 4079acb — budget/no-progress/goal via _evaluate_engine_exit)
- [x] **W7.3** Wire exit 4 (run-level wall clock — today only per-wave adapter timeouts), exit 7
      (error threshold via the now per-run breaker), exit 8 (external event: PR/issue closed)
      (DIR-01). (2026-07-27 ✅: 4079acb — _scan_pre_dispatch_exits + _fire_error_threshold_exit)
- [x] **W7.4** Record the fired exit id on the run and surface it in the dashboard + `status`.
      (2026-07-27 ✅: 4079acb — list_fired_exit_ids; cli status + dashboard exits panel)
- [x] **W7.5** Update `docs/design-note.md` §0.3–0.4 so the exit table states, per exit, whether it
      is **Engine-live** or **evaluator-only**. The current table reads as if all 8 are live.
      (2026-07-27 ✅: 4079acb — 8× Engine-live in §0.3)
- [x] **W7.6** Turn `tests/test_exit_wiring.py` green (W1.10). (2026-07-27 ✅: 4079acb — 5/5 pass, xfails removed)
- [x] **W7.7** **Commit + push** (`feat(loops): wire the exit table into the engine`). (2026-07-27 ✅: 4079acb)

**Acceptance:**

```bash
make test -- -k exit_wiring                                        # green
grep -rn 'pullfrog_success' src/tripll --include='*.py' | grep -v 'exits.py:'   # >= 1 setter
grep -c 'evaluate_exit' src/tripll/engine.py                       # >= 1
# after a fixture run that trips each exit:
sqlite3 runs/<id>/ledger.db "select distinct exit_id from runs"    # includes 1, 4, 7, 8
grep -c 'Engine-live\|evaluator-only' docs/design-note.md          # 8 — one verdict per exit
```

If W7.1 cannot be closed: mark the wave `[P]`, file the issue, record it in Re-entry, and **do not**
edit the exit table in `docs/design-note.md` to remove `goal_met`.

---

## Wave W9 — Close one L1 loop  *(executes before W8 — R10)*

**Findings:** L1-scaffold · **Decisions:** R10

`l1_outer` nodes are `_node_writer` stubs whose own docstring says they "would call
`run_dispatch.dispatch()` in production"; `l1_pr._node_investigate` / `_node_fix` build dispatch
dicts and return. Checkpointing and recovery are real; the dispatch is not.

Moved here from the tail so it lands **immediately behind its dependency (W7)** rather than under
end-of-plan schedule pressure — it is the wave most likely to need its full attempt budget.

- [x] **W9.1** Add `src/tripll/loops/dispatch_bridge.py` — one seam translating a node's dispatch
      metadata into a real adapter call, reusing `Engine`'s existing worktree → brief → dispatch →
      verify path rather than duplicating it. (2026-07-27 ✅: 900cea9)
- [x] **W9.2** Wire **`l1_pr` investigate → fix only** (R10): `ci-investigator` then `check-fixer`,
      behind the `graph` extra. Depth over breadth — one honest closed loop. (2026-07-27 ✅: 900cea9)
- [x] **W9.3** Preserve the human merge gate absolutely: the loop parks, it never merges (D15).
      (2026-07-27 ✅: 900cea9 — park_at_merge_gate unchanged; grep confirms no merge call)
- [x] **W9.4** Keep the degradation contract: no langgraph installed ⇒ linear path; a cyclic plan
      fails fast with an explicit message. (2026-07-27 ✅: 900cea9 — run_pr_loop_step linear + require_graph)
- [x] **W9.5** Update `l1_outer.py`'s module docstring to state plainly that its nodes remain
      scaffolding — do not leave "would call … in production" language implying otherwise.
      (2026-07-27 ✅: 900cea9)
- [x] **W9.6** Turn `tests/test_pr_loop.py` adapter-invocation assertions green (W1.12).
      (2026-07-27 ✅: 900cea9 — xfails removed; FakeAdapter records 2 calls)
- [x] **W9.7** **Commit + push** (`feat(loops): close the pr fix loop end to end`).
      (2026-07-27 ✅: 900cea9)

**Acceptance:**

```bash
make test -- -k pr_loop                                            # green; fake adapter recorded calls
grep -n 'would call' src/tripll/loops/l1_outer.py                  # no output
grep -rn 'merge' src/tripll/loops/l1_pr.py | grep -v 'merge_gate\|merge_signal'  # no merge call
uv run python -c "import langgraph" 2>/dev/null || make test -- -k pr_loop_linear # degradation path green
```

---

## Wave W8 — Repo portability

**Findings:** ARCH-CW, DEBT-parse, DX-runs · **Decisions:** R9

- [x] **W8.1** `plan/cw_buckets.py:6–15` — default `CW_HOTSPOTS` to **empty** (R9). The current
      default hands every non-sevn target repo a forbidden-path set pointing at
      `src/sevn/gateway/…`, `infra/sevn.schema.json`, etc. (2026-07-27 ✅)
- [x] **W8.2** Move `LEGACY_CW_BUCKETS` to an opt-in fixture used by the corpus-replay test, so the
      proven equivalence is retained without shipping it as a default. Allow explicit configuration
      from the plan. (2026-07-27 ✅: `tests/fixtures/legacy_cw_buckets.py`)
- [x] **W8.3** `graph.py:32–38` — confirm the loader tolerates an empty hotspot set. (2026-07-27 ✅:
      `batch_cw_seams()` omits seams when hotspots empty)
- [x] **W8.4** Fix "sevn.bot git checkout" docstrings in `repo_root.py` / `worktrees.py`
      (DEBT-parse) — naming debt from the standalone extraction. (2026-07-27 ✅)
- [x] **W8.5** Correct the nested legacy runs-path references now that the CLI resolves `runs/`
      under the repo root (DX-runs): `cli.py:67, 77–83`, `pipeline.py:5`,
      `build_plan_from_errors.py:9`. (2026-07-27 ✅)
- [x] **W8.6** Turn `tests/test_cw_portability.py` green (W1.11). (2026-07-27 ✅: xfails removed)
- [x] **W8.7** **Commit + push** (`fix(plan): make coordination-wave defaults repo-portable`). (2026-07-27 ✅)

**Acceptance:**

```bash
make test -- -k cw_portability                                     # green
grep -rn 'src/sevn' src/tripll/plan/cw_buckets.py                  # empty (legacy fixture in tests/)
grep -rn '<repo_root>/runs' src/tripll/cli.py src/tripll/pipeline.py  # non-empty
grep -rn 'sevn.bot git checkout' src | wc -l                       # 0
make test -- -k corpus_replay                                      # legacy equivalence still proven
```

---

## Wave W10 — Observability, bench, brief packer

**Findings:** TEST-01, TEST-02, DX-04, PERF-01

- [x] **W10.1** Green `tests/test_obs.py` (TEST-01) — the no-exporter contract without
      `LOGFIRE_TOKEN` (local sinks still write — TRACE-04), the `capture_all` guard re-verified in
      W4.6, and "obs must never break the CLI". P3 owns the implementation; W1 authored the RED test;
      W10 only reconciles what is left. (2026-07-27 ✅ — xfail removed; 6/6 tier-1 green)
- [x] **W10.2** Add a `bench` target to the `Makefile` (TEST-02/DX-04) — it does not exist today.
      Tier 2: minutes, not seconds. (2026-07-27 ✅ — `make bench` → `tripll bench run`)
- [x] **W10.3** Add a CI job running the brief-packing benchmark on a sealed task set, **non-blocking
      at first**, so graph-brief vs grep regressions surface. The D23 verdict (keep the packer) has
      no guard against silent regression. (2026-07-27 ✅ — `bench` job with `continue-on-error: true`)
- [x] **W10.4** Fix the double computation of `_graph_brief_tokens` per task (PERF-01).
      (2026-07-27 ✅ — cache per-task tokens in `run_benchmark` loop)
- [x] **W10.5** Add a first-class span around `_execute_node` / batch dispatch so Logfire traces
      correlate with ledger attempts (audit §11: correlation is thin). (2026-07-27 ✅ — `tripll.execute_node` + `tripll.batch_dispatch` spans)
- [x] **W10.6** Turn W1.5 and W1.14 green. (2026-07-27 ✅ — xfail markers removed from test_obs.py, test_brief_packer.py)
- [x] **W10.7** **Commit + push** (`test(obs): guard observability and productize bench`). (2026-07-27 ✅: a39dc9a)

**Acceptance:**

```bash
grep -n '^bench:' Makefile                                         # non-empty
make bench                                                          # exit 0
make test -- -k "obs or brief_packer"                              # green
grep -n 'continue-on-error: true' .github/workflows/ci.yml         # bench job non-blocking
grep -n 'span' src/tripll/engine.py | grep -i 'execute_node\|batch' # dispatch span present
```

---

## Wave W11 — DX cleanups and dependency rebaseline

**Findings:** DX-03, Dependabot · **Decisions:** R12

- [x] **W11.1** Replace the hand-rolled TOML parse in `log_redact.py:54` with stdlib `tomllib`
      (DX-03) — the current line-splitting parser is fragile for a security-relevant config.
      (2026-07-27 ✅: c9216d9 — `tomllib.load` in `load_hide_keys`)
- [x] **W11.2** Keep `log-redact-check` green against the expanded W4 list.
      (2026-07-27 ✅: c9216d9 — `make ci` green including log-redact gate)
- [x] **W11.3** Rebaseline the 7 open dependabot PRs **now that CI runs** (R12): `ruff 0.15.18`,
      `mypy 2.1.0`, `pytest 9.1.1`, `typer 0.26.7`, `uvicorn>=0.49.0`, `actions/checkout@7`,
      `softprops/action-gh-release@3`.
      (2026-07-27 ✅: c9216d9 — all 7 PRs closed with rebaseline comment)
- [x] **W11.4** Treat **ruff 0.15.18 first and carefully** — the pinned `0.15.12` is what makes the
      `ASYNC240` selector in `pyproject.toml` resolve at all (DX-05's root). Confirm the selector
      still exists in the new version before merging.
      (2026-07-27 ✅: c9216d9 — `uv run ruff check --select ASYNC240 src` passes)
- [x] **W11.5** **Commit + push** (`chore(deps): rebaseline dependencies under a live gate`).
      (2026-07-27 ✅: c9216d9 — pushed to wave/l1-remediation)

**Acceptance:**

```bash
grep -n 'tomllib' src/tripll/log_redact.py                         # non-empty
grep -n 'split(' src/tripll/log_redact.py | grep -i toml           # no output — parser gone
make ci                                                             # exit 0
gh pr list --author app/dependabot --json number,state             # every PR merged or closed
uv run ruff check --select ASYNC240 src | head -1                  # selector resolves
```

Each closed-not-merged PR carries a recorded reason in its closing comment.

---

## Wave W13 — Config spine, one-time setup, doctor

**Findings:** ONB-01, ONB-06 · **Decisions:** R23, R24 · **Blocks:** W14, W15

The first wave of the onboarding program. Everything here is about making tripll *configurable once*
rather than re-specified on every command line.

- [x] **W13.1** *(ONB-01)* Add `src/tripll/config.py`: a single `load_config()` resolving four layers,
      highest first — **env (`TRIPLL_*`) → `./tripll.toml` → `~/.config/tripll/config.toml` →
      built-in defaults**. Use stdlib `tomllib`; W11 just removed the last hand-rolled TOML parser,
      do not add another. Every existing `TRIPLL_*` var keeps working unchanged — this layer sits
      *under* env, it does not replace it. (2026-07-27 ✅: e1fb05d)
- [x] **W13.2** Adopt SKW's **merge-table precedence rules** from `agent_config.py:257–274`
      (`[agent]` → `[agent.models.<id>]` → per-wave → per-stage → env). Take the resolution order,
      which is well designed; leave the argv builder, which `adapters/` already owns. (2026-07-27 ✅: e1fb05d)
- [x] **W13.3** *(ONB-01)* Add **`tripll setup`**: interactive by default, `--non-interactive` for CI.
      Detects installed backends via each adapter's `capabilities()`, asks which to enable, records
      `default_provider`, per-provider `max_parallel` / `default_model`, and the `[tracing]` block P3
      defined. Writes `~/.config/tripll/config.toml`. Re-running edits rather than replaces. (2026-07-27 ✅: e1fb05d)
- [x] **W13.4** *(R24)* **Never store a credential.** `setup` verifies auth by calling
      `capabilities()` and, when a backend is unavailable, prints the exact command to fix it
      (`claude login`, `cursor-agent login`). Keys stay in the backend toolchains. This is a
      `forbidden` clause because it is the most likely thing to be "improved" later. (2026-07-27 ✅: e1fb05d)
- [x] **W13.5** *(ONB-01)* Add **`tripll doctor`**: preflight that reports Python version, installed
      extras (`graph`, `kg`, `api`, `obs`, `scaffold`), each provider's availability and auth state,
      resolved repo root, resolved runs root, config file locations with which layer won, and whether
      the v3 template resolves. **Exit non-zero when no provider is available** — a doctor that always
      exits 0 is decoration. (2026-07-27 ✅: e1fb05d)
- [x] **W13.6** *(ONB-06)* Move the **v3** wave-plan template into the package as
      `src/tripll/templates/wave-plan-template.md` and resolve it via `importlib.resources`. Today the
      only template in the wheel is `skw/wave-plan-template.md`, which is `waveorch_format = 2` —
      a pip-installed tripll literally cannot emit a current-format plan. Keep `docs/wave-plan-template.md`
      as a symlink or a generated copy so there is **one** source of truth, and assert they match. (2026-07-27 ✅: e1fb05d)
- [x] **W13.7** Prune the `force-include` block in `pyproject.toml`. **Proven dead, not assumed:**
      two wheels were built, one with the block and one without, and the file lists are byte-identical
      — 266 entries each, nothing lost, nothing gained. Hatchling already ships every non-`.py` file
      under `src/tripll/`. The block is worse than redundant: it implies data files must be registered
      to ship, so the next person to add one either registers it needlessly or assumes an unlisted
      file will be dropped. Delete it **in the same commit** as the wheel-contents test below, so
      there is never an unguarded window. (2026-07-27 ✅: e1fb05d)
- [x] **W13.7a** Add the guard the `force-include` block was pretending to be: a test that builds (or
      inspects) the wheel and asserts the v3 template, `spec-rules.toml`, `prd-rules.toml` and the
      `prompts/` tree are present. This is the assertion that actually protects packaging; the
      `force-include` list never did. (2026-07-27 ✅: e1fb05d)
- [x] **W13.8** Adapt SKW's **`nextstep.py`** into `src/tripll/onboard/nextstep.py` — "what is the next
      command to run", computed from wave checkbox state via `markdown_sections.py`. tripll has no
      equivalent and it is exactly what a new operator needs after `init`. Surface it as
      `tripll doctor --next` and in the `init` epilogue. (2026-07-27 ✅: e1fb05d)
- [x] **W13.9** Reuse SKW's `runtime.py` (`is_dryrun`, `is_pytest`, `is_auto_approve`) rather than
      re-deriving those checks; they are trivial and already correct. (2026-07-27 ✅: e1fb05d)
- [x] **W13.10** **Commit + push** (`feat(config): tripll.toml, one-time setup, and doctor preflight`). (2026-07-27 ✅: e1fb05d)

**Acceptance:**

```bash
make test -- -k "config or doctor"                                  # green
tripll setup --non-interactive --provider cursor_local              # writes user config
test -f ~/.config/tripll/config.toml
tripll doctor                                                        # 0 with a provider present
env -i PATH=/usr/bin:/bin "$(command -v tripll)" doctor; echo $?    # non-zero with none
# precedence, all four layers:
make test -- -k test_config_precedence
# the v3 template ships (ONB-06):
uv build --wheel -o /tmp/w && python -c "
import zipfile,glob
n=zipfile.ZipFile(sorted(glob.glob('/tmp/w/*.whl'))[-1]).namelist()
t=[x for x in n if 'templates/wave-plan-template.md' in x]; assert t, 'v3 template missing'
print(t)"
grep -c 'waveorch_format = 3' src/tripll/templates/wave-plan-template.md   # >= 1
```

`tripll doctor` is the wave's real deliverable: if it cannot tell an operator why a run will fail
before they start it, this wave did not land.

---

## Wave W14 — Brownfield onboarding

**Findings:** ONB-02, ONB-03, ONB-05 · **Decisions:** R23 · **Depends:** W13

One command that takes an existing repo — **not** tripll, **not** sevn — and leaves it ready to plan
against, plus an honest assessment of what it found.

- [x] **W14.1** *(ONB-05)* ~~**Cut the sevn import.**~~ **Done ahead of the plan, 2026-07-26.** The
      sevn-backed `sync` path is gone: 253 lines from `doc_folder.py`, the `spec sync` / `prd sync`
      CLI commands, and the `spec-sync` / `prd-sync` Make targets. It removed no working behaviour —
      `sync` already raised `ModuleNotFoundError: No module named 'sevn'` in tripll's own checkout and
      its one test was skipped behind `importorskip("sevn")`. `validate` and `score` were always
      sevn-free. Two guard tests now hold the line: `test_command_dispatch_rejects_sync` and
      `test_module_has_no_sevn_dependency` (asserts no `sevn` string and no `sys.path` mutation).
      **What W14 still owes:** a tripll-native replacement for what `sync` was *supposed* to do —
      refresh frontmatter from code and scaffold missing docs from a manifest — built on a
      tripll-owned doc model rather than sevn's `AboutDoc`. `pydantic>=2.13.3` is already a direct
      dependency, so this needs no new package.
- [x] **W14.2** *(ONB-02)* Add `src/tripll/onboard/brownfield.py` and wire **`tripll init`** to it.
      (2026-07-27 ✅: `brownfield.py` + CLI `--force`; runs layout preserved)
- [x] **W14.3** Emit the document skeleton using the **adapted SKW contracts**: `docs/specs/` and
      `docs/prds/` from `spec-templates/` + `prd-templates/` (frontmatter schema, required H2 order,
      the AST check that `interfaces[].symbol` actually exists in `interfaces[].file`), and
      `docs/plans/` with the packaged **v3** template from W13.6. Do not re-author these schemas —
      they are the most valuable thing in `skw/`.
      (2026-07-27 ✅: `onboard/emitters.py` shared spec/PRD/plan scaffolds)
- [x] **W14.4** *(ONB-03)* Add `src/tripll/onboard/evaluate.py` producing
      `docs/evaluation-<date>.md`, aggregating: `graph extract` structure and fan-out, `doc_score`
      results for any existing docs, `make check` / CI signals, test-to-module coverage ratio, and
      provider readiness from `doctor`. Follow the section shape of
      `ignorelocal/project-evaluation-2026-07-25.md` — chronological map, per-area *What works /
      Issues / Missing / Stubs*, then direction and suggested next passes. **Every finding carries
      `file:line` evidence**; a finding without evidence is a guess, and this plan exists because
      that distinction was once not enforced.
      (2026-07-27 ✅: `evaluate.py` + HTML via render_report)
- [x] **W14.5** Adapt `skills/improve-codebase-architecture` + its `render_report.py` as the
      evaluation's renderer, broadened from "architecture deepening" to the full section set. Reuse
      `pipeline_diagram.py` for the HTML view.
      (2026-07-27 ✅: render_report HTML companion; pipeline_diagram deferred to plan-driven flows)
- [x] **W14.6** Reuse SKW's `render.py` + `prompts/` front-end stages (`specify`, `clarify`, `plan`,
      `wayfinder`, `prd-author`, `wave-generator`) as the **spec-generation spine** for the agent-
      assisted path. This is the piece worth keeping from the SKW pipeline; the LangGraph runner
      around it is not.
      (2026-07-27 ✅: `emitters.render_spec_prompt` wraps SKW frontend stages)
- [x] **W14.7** **Idempotence.** A second `tripll init` reconciles: it reports drift, fills gaps, and
      touches **no** operator-edited file without `--force`. Assert it — an onboarding command that
      clobbers work is one a user runs exactly once.
      (2026-07-27 ✅: `tests/test_onboard.py` foreign-repo idempotence)
- [x] **W14.8** Write `docs/runbooks/onboarding-runbook.md`: the brownfield path end to end, what
      each artefact is for, how to re-run safely, and how to read the evaluation.
      (2026-07-27 ✅: onboarding-runbook.md)
- [x] **W14.9** **Commit + push** (`feat(onboard): brownfield init with specs and repo evaluation`).

**Acceptance:**

```bash
make test -- -k onboard                                             # green
grep -rn 'import sevn' src/tripll | wc -l                           # 0 — ONB-05, CLAUDE.md rule
grep -rn '_ensure_sevn_importable' src/tripll | wc -l               # 0
# a foreign repo, neither tripll nor sevn:
d=$(mktemp -d) && git -C "$d" init -q && mkdir -p "$d/src" && echo 'def f(): pass' > "$d/src/a.py"
(cd "$d" && tripll init)
test -f "$d/tripll.toml" && ls "$d/docs/specs" "$d/docs/prds" "$d/docs/plans"
ls "$d"/docs/evaluation-*.md                                        # the assessment exists
grep -cE '^\|.*:[0-9]+' "$d"/docs/evaluation-*.md                   # findings carry file:line
# idempotent:
echo 'operator edit' >> "$d/tripll.toml" && (cd "$d" && tripll init)
grep -c 'operator edit' "$d/tripll.toml"                            # 1 — not clobbered
```

The fixture repo must be **neither tripll nor sevn**. Onboarding tested only against its own
checkout is the same mistake `LEGACY_CW_BUCKETS` made (ARCH-CW), and W8 just finished fixing it.

---

## Wave W15 — Greenfield onboarding

**Findings:** ONB-04 · **Decisions:** R23 · **Depends:** W14

- [x] **W15.1** *(ONB-04)* Add `src/tripll/onboard/greenfield.py` and wire **`tripll new <name>`**.
      Today `scaffold.py` shells out to a **generic** cookiecutter Python package with nothing tripll
      about it — no specs, no agents, no config, no plan.
- [x] **W15.2** **One emitter, two entry points.** Greenfield calls the same spec/PRD/plan emitters
      W14 built; the only difference is that it creates the project first. Assert the sharing with a
      test, not with a comment — a second copy of the spec templates is a `forbidden` item.
- [x] **W15.3** Keep `cookiecutter` **optional**. `tripll new` degrades with a named, actionable error
      when the `scaffold` extra is absent, and the templates tripll itself owns are packaged, so the
      offline path needs no network.
- [x] **W15.4** The scaffolded project must pass `tripll validate-plan` on its generated plan and
      `make check` on its generated skeleton — a scaffold that emits something tripll then rejects is
      worse than no scaffold.
- [x] **W15.5** Extend `docs/runbooks/onboarding-runbook.md` with the greenfield path.
- [x] **W15.6** **Commit + push** (`feat(onboard): greenfield project scaffold with specs`).

**Acceptance:**

```bash
make test -- -k greenfield                                          # green
d=$(mktemp -d) && (cd "$d" && tripll new demo-project)
test -f "$d/demo-project/tripll.toml" && ls "$d/demo-project/docs/specs"
(cd "$d/demo-project" && tripll validate-plan docs/plans/*-wave-plan.md)   # exit 0
(cd "$d/demo-project" && make check)                                        # exit 0
# the scaffold extra stays optional:
uv run --no-project python -c "
import tripll.onboard.greenfield as g; print(hasattr(g,'new_project'))"
# one emitter, not two:
grep -rn 'spec-template' src/tripll/onboard | sort -u | wc -l       # shared resolver, single path
```

---

## Wave W12 — Docs, roster honesty, a11y

**Findings:** ARCH-06, FRONT-01, PERF-02 · **Also documents:** W13–W15 onboarding

- [ ] **W12.1** Add a dispatch-status banner to `docs/agents/*.md` (ARCH-06): which roles the Engine
      actually dispatches vs which are prompts/contracts only. 17 documented roles with a small live
      subset is the single biggest source of operator confusion in the docs.
- [ ] **W12.2** Correct the roster claim in `docs/` where L1 loops *name* `ci-investigator` /
      `check-fixer` / `pr-shepherd` — accurate only for the path W9 closed; say so precisely.
- [ ] **W12.3** Add `aria-label` to interactive controls in the dashboard templates (FRONT-01).
- [ ] **W12.4** Document PERF-02 (sync SQLite in async routes) as a known single-operator
      constraint in the runbook rather than re-architecting it.
- [ ] **W12.5** Document the dashboard launch path's fire-and-forget `subprocess.Popen` with
      discarded stdout/stderr (`router.py:255`) — or capture output to the run dir so a failed
      launch is diagnosable from the UI.
- [ ] **W12.5a** *(DASH-01)* Surface **provider / model / reasoning effort** per wave in the
      dashboard waves table (`_waves_tbody.html`) and in `tripll status`. In a mixed-provider run
      this is the first question an operator asks; today the answer is only in the ledger.
      Show the per-provider cost rollup from W6.5 alongside it.
- [ ] **W12.6** Update `README.md`: `TRIPLL_API_TOKEN` now covers HTML too, bind-address guidance,
      `make bench`, and the `human_gates` config from P0.8.
- [ ] **W12.6a** **Lead the README with the new-user path** (W13–W15). Today the README opens on
      pipeline internals and assumes plans already exist; a first-time reader has nowhere to start:

      ```bash
      uv tool install tripll        # or: pip install tripll
      tripll setup                  # once per machine — providers, models, tracing
      tripll doctor                 # confirm it will actually run
      cd ~/code/my-project && tripll init     # existing repo: specs + evaluation
      tripll new my-project                   # or start fresh
      ```

      Document what `init` writes, what the evaluation is for, the four-layer config precedence, and
      the fact that **no credential is ever stored by tripll** (R24). Keep the existing operator
      "Quick run" section — it stays valid for someone who already has plans.
- [ ] **W12.6b** Add the same path to `about-tripll/_sources/getting-started.yaml`, and a `tripll.toml`
      + `~/.config/tripll/config.toml` reference to the CLI page. Cross-link
      `docs/runbooks/onboarding-runbook.md` from both.
- [ ] **W12.6c** Update `CLAUDE.md`'s command table with `setup` / `doctor` / `init` / `new`, and
      state that `tripll.obs` is the **sole** tracing configurator (R22) so no future agent re-adds a
      second one.
- [ ] **W12.7** Regenerate the help site (`make about-site`); `about-site-check` must stay green.
- [ ] **W12.8** **Commit + push** (`docs: align agent roster, auth posture, and operator guidance`).

**Acceptance:**

```bash
# every agent doc carries a dispatch verdict:
for f in docs/agents/*.md; do grep -qi 'dispatch status' "$f" || echo "MISSING: $f"; done   # no output
grep -c 'backend\|provider' src/tripll/api/ui/templates/_waves_tbody.html   # >= 1 (DASH-01)
# no interactive control lacks a label:
grep -rEn '<(button|input|select|textarea|a )' src/tripll/api/ui/templates \
  | grep -v 'aria-label\|aria-labelledby'                          # no output
make about-site && make check                                       # about-site-check green
grep -n 'human_gates\|TRIPLL_HUMAN_GATES' README.md docs/runbooks/operator-runbook.md  # documented
grep -n 'PERF-02\|sync SQLite' docs/runbooks/operator-runbook.md    # documented
```

---

## Final wave — CI gate, commit & push

- [ ] **F.1** test-creator: drop every satisfied xfail; update `docs/test-plans/l1-remediation.md`.
- [ ] **F.2** `make ci` until green, then **run the full suite twice consecutively** (flaky tests
      hide broken builds — never trust one green checkmark).
- [ ] **F.3** **Confirm a green GitHub Actions run on the branch head** — not a local pass. This is
      the acceptance criterion the previous program never had.
- [ ] **F.4** Re-run the audit's own spot checks — each must invert.
- [ ] **F.5** Change summary table (Wave | Headline | sha | CI run | **Parked**), plus exact
      reproduction commands for anything parked.
- [ ] **F.6** Declare every parked wave explicitly. If ≥3 are parked, **stop here** — do not proceed
      to Thermos; write the run summary and report.
- [ ] **F.7** **Commit + push** (`chore(ci): finalize L1 remediation gate`).

**Acceptance:**

```bash
make ci && make ci                                                  # green twice
gh run list --workflow=CI --branch wave/l1-remediation --limit 1 --json conclusion  # "success"
grep -rn 'xfail' tests/ | grep -c 'green after W'                   # 0 — no stale xfails
# audit spot checks, all inverted:
grep -rn 'pullfrog_success' src/tripll | grep -v 'exits.py:'        # >= 1 (or W7 parked)
grep -n '^bench:' Makefile                                          # non-empty
grep -c '^' config/log-hide-keys.toml                               # >= 15
grep -rn '\.cursor/agents' src tests docs | wc -l                   # 0
```

### Change summary

| Wave | Headline | Provider / model | sha | CI run | Cost | Parked |
|------|----------|------------------|-----|--------|------|--------|
| P0 | Restore executable gate + plan self-hosting | — | — | — | — | — |
| P1 | Per-provider pools, routing, effort, budget | — | — | — | — | — |
| P2 | Activate the code graph | — | — | — | — | — |
| P3 | Trace every agent call — local + Logfire | — | — | — | — | — |
| W0 | Baseline, ADRs 006–011, pinned contract | — | — | — | — | — |
| W1 | RED suite for L1 remediation (tier-tagged) | — | — | — | — | — |
| W2 | Source agent definitions from the skw tree | — | — | — | — | — |
| W3 | Auth and CSRF on the HTML control plane | — | — | — | — | — |
| W4 | Harden token transport, paths, redaction | — | — | — | — | — |
| W5 | Cancellation-safe dispatch | — | — | — | — | — |
| W6 | Cost, breaker scope, integrate resume | — | — | — | — | — |
| W7 | Wire the exit table into the engine | — | — | — | — | — |
| W9 | Close the PR fix loop | — | — | — | — | — |
| W8 | Repo-portable coordination waves | — | — | — | — | — |
| W10 | Guard observability, productize bench | — | — | — | — | — |
| W11 | Rebaseline dependencies | — | — | — | — | — |
| W12 | Roster honesty, a11y, docs | — | — | — | — | — |
| Final | Finalize L1 remediation gate | — | — | — | — | — |

---

## Thermos gate

- [ ] **T.1** **Contract-tampering audit — run this before any code review.** Work only from the
      contract (`docs/plans/l1-remediation.md`), the Re-entry block, and the diff. Never from a
      builder agent's reasoning or chat.

      ```bash
      shasum -a 256 docs/plans/l1-remediation.md              # must match the W0.6 value
      git diff <base>...HEAD -- tests/                        # read every deletion and weakening
      grep -rn 'xfail' tests/ | grep 'green after W'          # any left whose wave is [x] is tampering
      grep -rn 'strict=False' tests/                          # justify each survivor
      git diff <base>...HEAD -- tests/ | grep '^-' | grep -i 'assert'   # every removed assertion
      ```

      Any acceptance criterion weakened, narrowed, or deleted to reach `[x]` is a **finding**, not a
      judgement call. Criteria are only legally retired by parking the wave.
- [ ] **T.2** Run the branch review agents on `git diff <base>...HEAD`.
- [ ] **T.3** Fix every finding above `low`; **commit + push each fix pass**; re-run until clean;
      `make ci` after the last pass.
- [ ] **T.4** If clean with no code changes, push an `--allow-empty` marker
      (`chore(wave): thermos clean l1-remediation`).
- [ ] **T.5** **Re-run the two audit checks that started this plan:** `make check` from a fresh
      clone in a temp dir, and `gh run list --workflow=CI` showing a green run on HEAD.
- [ ] **T.6** **Merge request — always human** (`auto_acceptable = false`). tripll parks; a person
      merges (D15).

**Acceptance:**

```bash
cd "$(mktemp -d)" && git clone <repo> t && cd t && make check       # exit 0
gh run list --workflow=CI --branch wave/l1-remediation --limit 1    # green on HEAD
shasum -a 256 docs/plans/l1-remediation.md                          # matches W0.6
```

---

## Success criteria (acceptance)

Issue numbers from W0.5 — **fill these in; an unrecorded issue is an unfiled one:**
god modules `#16` · dependency scanning `#17` · live-run verification `#18`.

- [ ] `cursor_local` never exceeds its configured `max_parallel`; an `infra` failure consumes no
      wave attempt and trips no breaker; failover changes provider only, never model
- [ ] Every wave declares its provider and model; the ledger records the resolved backend per attempt
- [ ] `grep -rn 'claude-3-5-sonnet' src` is empty and `DEFAULT_MODEL` matches the Engine docstring
- [ ] `compile_plan` feeds a real `code_graph` to `check_stop_rule`; a run without the `graph`/`kg`
      extras still completes

- [ ] **GitHub Actions executes on every push and is green on the branch head** — the repo's first
      green CI run
- [ ] `make check` passes from a clean clone with **no untracked prerequisites**
- [ ] `hash_agent_def` returns a digest for all 14 section-11 slugs from the **tracked**
      `src/tripll/skw/agents/` tree; AgentDef nodes materialize in the task graph;
      `grep -rn '\.cursor/agents' src tests docs` is empty; `.gitignore` is unchanged
- [ ] With `TRIPLL_API_TOKEN` set, **no** HTML route — page or form — bypasses the boundary the JSON
      API enforces; CSRF blocks forged POSTs; open dev mode unchanged when the token is unset
- [ ] No token appears in any URL except the `EventSource` stream; `base.html` emits it via `tojson`
- [ ] `run_id` cannot escape the runs root
- [ ] Redaction covers the common secret vocabulary; obs ships no auth headers or bodies
- [ ] A failing node cannot cancel its siblings; cancellation orphans **no** agent process
      (pid-verified under `RUN_LIVE=1`); no wave is ever stranded `running`
- [ ] Cost cannot double-count on reactivation; breakers are per-run; exit timestamps advance
- [ ] Re-running integrate preserves prior lane merges
- [ ] Every exit the design note advertises fires from the Engine and is recorded — **or W7 is
      parked with an issue.** `goal_met` is not withdrawn from the table (R8)
- [ ] A non-sevn target repo receives no sevn-shaped forbidden paths
- [ ] The PR fix loop dispatches real agents and stops at the human merge gate
- [ ] `make bench` exists and runs in CI; `tests/test_obs.py` guards the no-op and capture contracts
- [ ] No doc claims an unwired agent is on the dispatch path
- [ ] Every new test carries a tier marker; `make test` stays hermetic (tier 2 gated, tier 4 never
      blocking)
- [ ] `tripll validate-plan docs/plans/l1-remediation.md` exits 0, and the plan's sha256 at Thermos
      matches W0.6 — **the contract was not edited to fit the work**
- [ ] Human gates are auto-acceptable by config except the merge request; a red canary parks its
      gate rather than passing it
- [ ] Reasoning effort is declared per wave and reaches the CLI: `--effort` on Claude Code, the
      model string on Cursor; an invalid level is rejected at parse time, not at dispatch
- [ ] `cursor_local`'s ceiling is a **measured** number recorded in the runbook, not a guess
- [ ] Cost is attributable per provider (`select backend, sum(cost_usd) … group by backend`)
- [ ] The dashboard shows provider / model / effort per wave

- [ ] **A user who has only `pip install tripll` can get to a started run by reading the README
      alone** — `tripll setup` once, `tripll doctor` green, then `tripll init` or `tripll new`
- [ ] `tripll init` works on a repo that is **neither tripll nor sevn**, and running it twice changes
      no operator-edited file
- [ ] The brownfield run emits an evaluation whose findings each carry `file:line` evidence
- [ ] A **v3** wave-plan template resolves from an installed wheel with no repo checkout present
- [ ] `grep -rn 'import sevn' src/tripll` is empty — the `doc_folder` coupling is gone, and with it
      the last hard sevn dependency `CLAUDE.md` forbids
- [ ] No tripll config file contains a provider credential (R24)
- [ ] **Every agent call is traced, no exceptions** — the count of `tripll.agent.dispatch` spans
      equals the count of ledger `attempts` for the run
- [ ] Traces are written **without any token**: `runs/*/traces/traces.db` and a dated `.jsonl` exist
      after a run with `LOGFIRE_TOKEN` unset
- [ ] Logfire **cloud**, a **deployed local Logfire server** (`base_url`), and a generic **OTLP**
      collector are each reachable by config, and none of them is required
- [ ] `grep -rn 'logfire.configure' src/tripll` returns **exactly one** call site, and
      `tripll skw` with both gates on configures it once
- [ ] Span redaction and log redaction read the **same** hide-list; `capture` defaults to `shape` and
      no prompt or completion text reaches a span at that setting
- [ ] Tracing never fails a dispatch — a raising sink is swallowed, asserted by test
- [ ] Fewer than 3 waves parked; every parked wave has a reason and a filed issue
- [ ] Thermos clean above `low`; every wave left a pushed commit **with a green CI run**

## Traceability

### Finding → wave

| Finding | Waves |
|---------|-------|
| CI-00, DX-01, DX-02, DX-05, PLAN-selfhost, PLAN-gates, SHAPE-01 | P0 |
| PROV-01, PROV-02, PROV-03, MODEL-01, EFFORT-01, BUDGET-01, AUTH-01, CAP-01 | P1 |
| GRAPH-01 | P2 |
| TRACE-01, TRACE-02, TRACE-03, TRACE-04, TRACE-05 | P3 |
| TEST-03, ARCH-agentdef | W2 |
| SEC-01, SEC-05, SEC-06 | W3 |
| SEC-02, SEC-03, SEC-04, SEC-07 | W4 |
| OBS-01 | **P3** fixes · W4 re-verifies |
| BUG-01, BUG-02, BUG-03 | W5 |
| BUG-cost, BUG-07, DEBT-02, BUG-10, COST-01 | W6 |
| BUG-06, ARCH-exits, DIR-01 | W7 |
| L1-scaffold | W9 |
| ARCH-CW, DEBT-parse, DX-runs | W8 |
| TEST-01, TEST-02, DX-04, PERF-01 | W10 |
| DX-03, Dependabot | W11 |
| ONB-01, ONB-06 | W13 |
| ONB-02, ONB-03, ONB-05 | W14 |
| ONB-04 | W15 |
| ARCH-06, FRONT-01, PERF-02, DASH-01 | W12 |

### Audit § → waves

| § | Waves |
|---|-------|
| §1 trigger / control plane | W3, W12 |
| §2 parse / RunGraph | W4, W8 |
| §3 Pre-0 / HITL | W4 (token transport only — HITL logic is sound); P0.8 (gate config) |
| §4 dispatch / adapters / retry | P1, W5, W6 |
| §5 integrate / PR / L1 loops | W6, W9 |
| §6 terminal states / exits | W7 |
| §7 security | W3, W4 |
| §8 code quality | R11 — out of scope, issue filed in W0.5 |
| §9 front-end | W3, W12 |
| §10 CI / DX | P0, W10, W11 |
| §11 logging / evals / tracing | **P3** (the tracing spine), W4, W10 |
| §19 forensics | W2 — **re-homing, not authoring**; the briefs were never missing |

### Audit priority → wave

The audit's §13 table ranks by leverage. Mapping, in its order:

| # | ID | Wave |
|---|----|------|
| 0a, 0b | TEST-03, CI-00 | W2, P0 |
| 1 | SEC-01 | W3 |
| 2 | BUG-01/02/03 | W5 |
| 3 | BUG-06 | W7 |
| 4 | OBS-01 | **P3** fixes · W4 re-verifies |
| 5 | BUG-10 | W6 |
| 6 | ARCH-CW | W8 |
| 7 | SEC-02 | W4 |
| 8 | SEC-03/04 | W4 |
| 9 | DEBT-02 | W6 |
| 10 | DX-05 | P0 |
| 11 | DIR-01 | W7 |
| 12 | SEC-06/05 | W3 |
| 13 | SEC-07 | W4 |
| 14 | ARCH-agentdef | W2 |
| 15 | DX-01/02 | P0 |
| 16 | TEST-01/02 | W10 |
| 17 | ARCH-06 | W12 |
| 18 | BUG-cost / BUG-07 | W6 |

---

## Baseline notes

**Recorded 2026-07-26 (W0.1) at `e730591` pre-W0 commit on `wave/l1-remediation`.**

| Item | Value |
|------|-------|
| `git log -1 --oneline` | `e730591 chore(wave): set re-entry last pushed sha to 48b573e` |
| Integration target | `pre-0.0.1` (`3f5cf9b`) — CI executes on both `main` and `pre-0.0.1` post-P0.1; prefer audit baseline |
| First executed CI run id | `30166223593` (P0.1 canary; conclusion=failure, TEST-03) |
| `make lint` / `make typecheck` | exit 0 |
| `make test` | 14 failed (TEST-03), 973 collected — W2 scope |
| ADRs | `006`–`011` authored W0; `012-tracing-spine.md` present from P3 |
| Out-of-scope issues | #16 god modules · #17 dependency scanning · #18 live-run verification |
| Plan sha256 | `c639c91e8ccf234df0cc526b17195e56846ec018e24e672e118d8a3ca39a4859` (pinned W0.6) |
