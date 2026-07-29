# tripll AI-layer compounding — derived rules, bug-to-rule, calibration, tracker round trip — wave plan

**Status:** W0 complete — W1 (test-creator) next
**Date:** 2026-07-29
**Source evaluation:** external review of [`coleam00/ai-native-starter-pack`](https://github.com/coleam00/ai-native-starter-pack)
@ `main` (2026-07-29), read in full: 20 skills, 3 agents, 4 references, 6,115 lines of markdown, **zero code**
**Target repo:** [`sevn-bot/tripll`](https://github.com/sevn-bot/tripll) — this checkout
**Audit baseline:** `a4fbd0d` on `refactor/mergecraft-replace-pullfrog` — every anchor below line-checked at this sha
**Owner agents:** `wave-runner` (W0, W2–W7, Final, Thermos) · `test-creator` (W1 `role: test-author`)
**Contract copy:** `docs/plans/ai-layer-compounding.md` (tracked; W0.5 copies this file there and records its sha256)

---

## Re-entry

> **The crash-test rule.** A fresh session in any tool must read this block and continue without
> re-explanation. Whoever finishes a wave updates it **in the same commit** as the wave's work.
> If this block is stale, the run is not resumable — treat that as a defect, not an inconvenience.

| Field | Value |
|-------|-------|
| **Current wave** | W0 ✅ (2026-07-29) — W1 next |
| **Stage** | Baseline recorded; anchors re-grepped at `a4fbd0d`; ADRs 014–017 pinned; contract at `docs/plans/ai-layer-compounding.md` |
| **Next action** | Dispatch **W1** via `test-creator` — RED suite + `docs/test-plans/ai-layer-compounding.md` |
| **Blocked on** | — |
| **Last pushed sha** | `2d85526` |
| **Last CI run id** | *(CI not yet reported for branch — docs-only W0)* |
| **Parked waves** | 0 of 3 (plan-level stop rule) |
| **Integration target** | `refactor/mergecraft-replace-pullfrog` (`a4fbd0d`); `main` at `9a3f19d`, **26 commits behind**, not merged |
| **Plan sha256** | `119d3ff2d95cef77bbab5f387cdfd75f79751ca978f95f5220afaa42dc642b51` |
| **Contract sha256 (W0 pin)** | `119d3ff2d95cef77bbab5f387cdfd75f79751ca978f95f5220afaa42dc642b51` |

---

## What this plan is, and what it is not

A read of the starter pack against tripll produced six ideas worth taking. **Nothing in the pack
threatens tripll's engine** — the pack has no ledger, no state machine, no exit criteria, no scope
enforcement, and a `merge-worktrees` skill that handles exactly two branches with hardcoded
`uv run pytest`. Its engine ideas are strictly behind tripll's and are **not** in scope here.

What the pack is genuinely ahead on is **compounding**: the loop where a failure becomes a durable
rule that the next run cannot repeat. tripll records more failure signal than the pack ever will —
`Finding` nodes, scope breaches, attempt counts, `exit_fired` events, env fingerprints — and then
does nothing with it. That is the whole subject of this plan.

**The six ideas, and where each lands:**

| # | Idea | Pack source | Wave |
|---|------|-------------|------|
| 1 | **Bug-to-rule loop** — a confirmed defect yields a durable rule + a regression test, not just a fix | `rca/SKILL.md:54`, `system-review/SKILL.md:148` | **W3** |
| 2 | **Derived rules + on-demand context modules** — `CLAUDE.md` and `.claude/context/<topic>.md` generated from real code, every rule cited to `file:line` | `create-rules/SKILL.md:23–79` | **W2** |
| 3 | **Predicted first-pass confidence, calibrated against the ledger** | `plan-feature/SKILL.md:460` | **W5** |
| 4 | **Tracker round trip** — read the epic, write the breakdown back, file the tickets idempotently | `spec/SKILL.md:89–133` | **W6** |
| 5 | **Executable rules** — a rule that fails the build beats a rule that is prose in a brief | `ast-grep/SKILL.md` | **W4** |
| 6 | **Adoption artifacts** — the two-lane narrative and the diagrams that make the thing adoptable | `README.md:80–92` | **W7** |

**Explicitly rejected from the pack** (recorded so nobody re-proposes them):

- The **PIV loop** itself — a strict subset of tripll's `W0 gate → test-creator RED → impl → verify`.
- `merge-worktrees` / `new-worktrees` — two-branch merge with a prose `git` driver. `integrate.py`
  supersedes it, and driving `git checkout -B` from a markdown file is the class of bug W6 of the
  L1 plan just fixed (BUG-10).
- `validate` (43 lines, trusts the agent) — `harness/contracts.py` already refuses self-report.
- `execute` — no scope enforcement, no attempt budget, no exits.
- The plan-length slice heuristic ("500–700 lines, split if longer") — a worse proxy than
  `effort` + `bullets_in_scope` + the `check_stop_rule` module count.

---

## The compounding gap — what tripll records and never reads

**The problem.** tripll has the richest failure telemetry of any tool in this space and **no
consumer for it**. A wave fails five times, escalates, gets fixed by a human, and the next run
starts from exactly the same priors. Findings are per-run (`{run_id}#{finding_id}`); the run
directory is archived; the lesson evaporates.

| Gap | Evidence | Wave |
|-----|----------|------|
| **CTX-01** — `tripll init` emits specs, PRDs, plans and an evaluation, but **no rules artifact**. Nothing generates a `CLAUDE.md` or any context module from the code it just analysed | `onboard/emitters.py` (`emit_doc_skeletons`); `grep -rn "context/" src/tripll/onboard/*.py` → empty | **W2** |
| **CTX-02** — the graph-packed brief carries **AST-derived structure only**. There is no channel for tacit knowledge the AST cannot see: "the formatter reverts this", "auth has two systems, JWT is forward", "this env var must be set locally" | `brief.enrich_brief_with_graph_pack`, `brief.GRAPH_PACKED_DIRECTIVE` | **W2** |
| **CTX-03** — `docs/evaluation-<date>.md` is written once and **never read by anything**. It tells an operator which waves to plan; it does not reach the agent that runs them | `onboard/evaluate.py::write_evaluation`; no reader in `src/` | **W2** |
| **RULE-01** — the ontology's `finding` layer has `Finding`, `Fix`, `Verdict`, `Escalation`, `Metric`, `Hypothesis`, `Experiment` — and **no durable `Rule`**. Every kind there is keyed `{run_id}#…`; nothing outlives its run | `ontology/ontology.yaml:127–190` | **W3** |
| **RULE-02** — the only learning channel is **negative**. `export_learnings` filters `state == "rejected"` and writes `.mergecraft/learnings.md` so mergeCraft stops re-raising false positives. A **confirmed** defect produces no artifact at all — the valuable half of the loop is missing | `github/learnings.py:30` (`rejected = [f for f in findings if f.get("state") == "rejected"]`) | **W3** |
| **RULE-03** — no plan-vs-actual reconciliation. `report.py` is a per-run ops summary; `orchestrator_status.py` is a live feed. Neither diffs a wave's **declared contract** against what the attempt actually did, so "the plan was wrong" and "the agent ignored the plan" are indistinguishable | `report.py`, `orchestrator_status.py` | **W3** |
| **AST-01** — **no structural-rule engine anywhere.** A rule can only ever be prose in a brief, which means it is enforced by hope | `grep -rn "ast.grep\|ast_grep" src scripts Makefile` → empty | **W4** |
| **AST-02** — `harness/boundary.py` enforces **path** scope (may this wave touch this file?) and nothing enforces **shape** (may this wave write `logging.getLogger`?). The CLAUDE.md rule "loguru only, never stdlib logging" is unenforceable today | `harness/boundary.py` | **W4** |
| **CAL-01** — nothing predicts wave difficulty before dispatch. `effort` is an operator's guess at *size*; there is no prediction of *success*, so there is nothing to be wrong about and nothing to learn from | `graph.py` `WaveNode.effort` | **W5** |
| **CAL-02** — the ontology **already defines** `Hypothesis`, `Experiment`, `Metric` and the `PREDICTED` / `REALIZED` predicates. **Nothing in `src/` `*.py` writes any of them** — the data model for calibration is built and unused | `ontology.yaml:141–172`; `grep -rn "Hypothesis" src/tripll --include='*.py'` → empty | **W5** |
| **CAL-03** — design-note §0.4 names *attempts-to-green* and *first-attempt pass rate* as recorded L2 telemetry. `bench/__init__.py` lists them as frozen baseline keys only; **no aggregator computes them from `ledger.attempts`** | `grep -rn "attempts_to_green\|first_attempt" src/tripll --include='*.py'` → `bench/__init__.py` METRIC_KEYS only | **W5** |
| **PM-01** — GitHub-only upstream, with no tracker abstraction. `github/` hardcodes `gh`; there is no seam an org on Jira or Linear could implement | `grep -rn -i "jira\|confluence" src/tripll` → empty | **W6** |
| **PM-02** — no downstream publish. A generated wave plan lives in the repo and nowhere a PM can see it, so tripll is a dev tool rather than a process | `skw/scaffold.py`, `wave-generator` | **W6** |
| **ADOPT-01** — `README.md` is 37 KB of operator reference with no adoption narrative. A reader learns *how* before they are ever told *why* | `README.md` | **W7** |
| **ADOPT-02** — no human-facing diagram of the pipeline. `skw/pipeline_diagram.py` renders a **plan**, not the product | `skw/pipeline_diagram.py` | **W7** |

**Already present — do not rebuild.**

- `graphstore/` + `ontology/ontology.yaml` — three-layer graph with a real store. W3 adds one node
  kind and two predicates; it does **not** add a second store.
- `github/findings.py` + `findings sync` / `list` / `triage` / `export-learnings`
  (`cli/__init__.py:1442–1560`) — the finding intake path is complete. W3 adds the **promotion**
  step on top of it and reuses `export_learnings`'s renderer.
- `skw/doc_score.py` — deterministic 0–100 with a scaffold-phrase penalty. W2 scores derived rules
  with it rather than inventing a second quality metric.
- `onboard/evaluate.py` `_build_findings` — already emits `file:line`-cited findings. W2's rule
  derivation consumes that output; it does not re-analyse the repo.
- `plan/shape_checks.py` `check_stop_rule` + the code graph — W5's difficulty features come from
  here (module count, CALLS fan-out), already computed for every compile.
- `ledger.attempts` — `attempt_n`, `outcome`, `backend`, cost, and the `EnvFingerprint` are already
  per-attempt columns. **W5 needs no ledger migration.**
- `harness/boundary.py` — W4's structural check is a **new checker at the same gate**, not a new gate.

---

## Rules — the object this plan is really about

A **Rule** is a durable, repo-scoped constraint with provenance. It is the thing that survives a run.

```
Finding (this run failed here)  →  Rule (this class must not recur)  →  {prose | executable}
                                        ↓                                      ↓
                              packed into the next brief            fails `make rules-check`
```

**The three states.** A rule is `proposed` (an agent suggested it), `active` (an operator accepted
it), or `retired` (superseded or wrong). **Only an operator promotes `proposed → active`** (R27) —
an agent that can write its own binding constraints will eventually write one that excuses its own
failure, and there is no gate that catches it afterwards.

**The two forms.** Every rule is prose. Some rules are *also* executable — an `ast-grep` pattern
that fails `make rules-check`. R29: **a rule that can be executable must be**, because a prose rule
in a brief is enforced by the agent's attention and an executable rule is enforced by the gate.

**Storage.** Rules live in the graph (`Rule` kind, natural key `{repo}#{rule_id}` — repo-scoped,
**not** run-scoped, which is the whole point) and render to `.tripll/rules/<rule_id>.md`. The
rendered files are committed; the graph is derived and rebuildable from them.

### Config surface (W2 implements)

```toml
[rules]
enabled = true
dir = ".tripll/rules"                # rendered rule files, committed
context_dir = ".tripll/context"      # on-demand context modules, committed
auto_propose = true                  # findings may propose; only an operator activates
pack_budget_tokens = 1200            # ceiling on rules+context injected into one brief
executable = "ast-grep"              # off | ast-grep
```

### Rule file shape

```markdown
---
rule_id: no-stdlib-logging
state: active
origin: finding://l1-remediation#F-014
scope: ["src/tripll/**"]
executable: ast-grep
severity: error
---

Use loguru; never stdlib `logging`.

**Why:** `logging` bypasses `log_redact`, so a redacted key ships to disk unredacted.
**Evidence:** `src/tripll/log_redact.py:54`, finding F-014 (2026-07-27).
**Test:** `tests/test_rules.py::test_no_stdlib_logging`
```

`origin` is mandatory and is `codebase://<file>:<line>` (derived, W2) or `finding://<run>#<id>`
(promoted, W3). **A rule with no origin is not a rule — it is an opinion**, and W2's validator
rejects it. This is the pack's best single instruction (`create-rules/SKILL.md:25`, *"Every rule
must trace to something real in the code — cite it (file:line)"*), and it is the reason its output
is worth generating at all.

---

## Context modules — the channel the graph pack cannot provide

The graph-packed brief is AST-derived and therefore blind to everything not in the AST. Context
modules are the complement, **not a competitor**: short, human-editable markdown loaded *on demand*
by topic, carrying the knowledge a parser cannot recover.

| Source | Carries | Cost |
|--------|---------|------|
| Graph pack (today) | modules, symbols, call edges, tests, specs | computed per dispatch |
| **Rules** (W2/W3) | binding constraints with provenance | ≤ `pack_budget_tokens`, always packed |
| **Context modules** (W2) | tacit knowledge: gotchas, legacy-vs-forward patterns, local env quirks | packed only when the wave's `targets` intersect the module's `scope` |

Three instructions taken verbatim from `create-rules` because they are the difference between a
useful artifact and a generated lie:

1. **Order by descending generality** — project one-liner, naming, core patterns, build commands,
   the context table, then hard rules, then gotchas. Hard rules go near the **bottom**; global rules
   are for things that apply to every task, and an implementation one-off in that slot is noise on
   every dispatch forever.
2. **Be honest about tests.** If the repo has no unit tests, the artifact says so. Do not emit a
   coverage standard the codebase does not enforce. (tripll's own `doc_score.py` already penalises
   scaffold phrasing — W2 runs derived rules through it for exactly this reason.)
3. **A running "Gotchas" section** — an explicit append-only catch-all, so the things that do not
   fit a taxonomy still land somewhere instead of being dropped.

---

## Calibration — the loop only tripll can close

The pack's `plan-feature` ends with a self-reported *"Confidence Score: #/10 that execution will
succeed on first attempt."* **Self-reported alone is noise.** It is worth taking anyway, because
tripll is the one system in this space that can *score* it: `ledger.attempts.attempt_n` already
records what actually happened.

```
compile_plan  →  predict(wave) → Metric{first_pass_probability}   [PREDICTED]
                                              ↓
run                                     ledger.attempts
                                              ↓
tripll calibrate  →  Metric{attempts_to_green, first_attempt_pass} [REALIZED]
                                              ↓
                            Brier score per predictor version
```

The ontology already has every node and predicate this needs (`Hypothesis`, `Experiment`, `Metric`,
`PREDICTED`, `REALIZED` — `ontology.yaml:167–190`). **W5 writes them; it does not design them.**

**The rule that keeps this honest (R28):** the predictor's output is **advisory metadata**. It may
be shown, logged and scored. It may **never** change routing, model selection, attempt budget or
gate behaviour. A prediction that steers the run it is predicting cannot be scored against a
counterfactual, and a miscalibrated predictor would silently starve exactly the waves that need the
most attempts. Feedback into routing is a separate program with its own evidence bar.

---

## Tracker round trip — the seam, not the integration

The pack ships `.mcp.json` pointing at the Atlassian MCP and calls Jira from inside a skill
(`spec/SKILL.md:36–48`). tripll must not do that: MCP tool ids in prose are exactly the coupling
`CLAUDE.md`'s external-dependency rule exists to prevent.

W6 ships a **`Tracker` protocol** with one real implementation (`github`, wrapping the existing
`github/` module) and a documented shape for others. Jira/Confluence is **out of scope as an
implementation** and in scope as a proof that the protocol is not GitHub-shaped:

```python
class Tracker(Protocol):
    def fetch_epic(self, ref: str) -> Epic: ...
    def list_children(self, ref: str) -> list[Ticket]: ...
    def create_child(self, parent: str, ticket: Ticket) -> str: ...
    def publish_breakdown(self, parent: str, markdown: str) -> str | None: ...
```

Two rules taken from `spec/SKILL.md` because they are what makes it re-runnable rather than
destructive:

- **Idempotence by pre-read.** List existing children *first*, match each slice against them, create
  only what is genuinely missing. Never create a near-duplicate. (Step 3, `spec/SKILL.md:118`.)
- **Ordered side effects.** Write the local artifact → publish the summary → create the tickets. If
  ticket creation fails partway, the breakdown still exists and the run is re-runnable.

---

## Machine block (`waveorch_format = 3`)

> **Why this exists.** Prose "Acceptance:" lines are self-reported. `[waves.outcome]` contracts are
> graded (D16 — *graders decide completion; agents do not self-report done*).
>
> **Verified 2026-07-29:** this block parses under `plan.format_v3.parse_plan_v3` and passes
> `plan.shape_checks.compile_plan` — **9 waves**, 0 dropped edges, max parallel group 1, no wave
> targeting more than 5 modules, no one-writer violation. Two authoring defects were found and fixed
> by that check, not by review: W1 and W2 exceeded the per-wave module threshold, and W5/W6 landed in
> the same antichain while both writing `cli/__init__.py`. W0.6 re-runs it at HEAD.

```toml
waveorch_format = 3
title = "tripll AI-layer compounding — derived rules, bug-to-rule, calibration, tracker round trip"
slug = "ai-layer-compounding"
base = "refactor/mergecraft-replace-pullfrog"
branch = "wave/ai-layer-compounding"
target_repo = "sevn-bot/tripll"

[pipeline]
max_turns = 3
deadline = "48h"
budget_usd = 45.0
human_gates = "prompt"
max_parked_waves = 3
max_parallel = 10
default_provider = "cursor_local"
extras = ["graph", "kg"]
creates = [
  "src/tripll/rules/__init__.py",
  "src/tripll/rules/model.py",
  "src/tripll/rules/derive.py",
  "src/tripll/rules/store.py",
  "src/tripll/rules/pack.py",
  "src/tripll/rules/promote.py",
  "src/tripll/rules/executable.py",
  "src/tripll/rules/postmortem.py",
  "src/tripll/calibrate/__init__.py",
  "src/tripll/calibrate/predict.py",
  "src/tripll/calibrate/score.py",
  "src/tripll/trackers/__init__.py",
  "src/tripll/trackers/base.py",
  "src/tripll/trackers/github.py",
  "tests/test_rules.py",
  "tests/test_rules_derive.py",
  "tests/test_rules_executable.py",
  "tests/test_postmortem.py",
  "tests/test_calibrate.py",
  "tests/test_trackers.py",
  "docs/decisions/014-rules-as-graph-nodes.md",
  "docs/decisions/015-calibration-advisory-only.md",
  "docs/decisions/016-tracker-protocol.md",
  "docs/decisions/017-executable-rules.md",
  "docs/runbooks/rules-runbook.md",
  "docs/test-plans/ai-layer-compounding.md",
  "docs/plans/ai-layer-compounding.md",
]

[providers.claude_code]
max_parallel = 3
default_model = "claude-opus-5"

[providers.cursor_local]
max_parallel = 5
default_model = "auto"
cooldown_s = 30

[[waves]]
id = "W0"
title = "Baseline, anchors, ADRs, contract pinning"
role = "impl"
effort = "S"
provider = "cursor_local"
model = "claude-opus-5"
targets = ["docs/decisions/014-rules-as-graph-nodes.md", "docs/decisions/015-calibration-advisory-only.md", "docs/decisions/016-tracker-protocol.md", "docs/decisions/017-executable-rules.md", "docs/plans/ai-layer-compounding.md"]
verify = ["make lint"]

  [waves.outcome]
  required = [
    "ADRs 014-017 exist and each states its rejected alternative",
    "every anchor in the gap table re-grepped at HEAD and corrected in place",
    "docs/plans/ai-layer-compounding.md exists and its sha256 is recorded in Re-entry",
    "tripll validate-plan on this plan exits 0",
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
targets = ["tests", "docs/test-plans/ai-layer-compounding.md"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W0"
  reason = "gate"
  detail = "contracts locked before the suite that grades them is authored"

  [waves.outcome]
  required = [
    "make test collects with 0 errors and 0 unexpected failures",
    "every new test is tier-tagged",
    "docs/test-plans/ai-layer-compounding.md maps finding to test to wave to tier",
  ]
  forbidden = ["strict=True on any cross-wave xfail", "any change under src/"]
  evidence = ["test_output"]

[[waves]]
id = "W2"
title = "Derived rules and on-demand context modules"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/rules", "src/tripll/onboard/emitters.py", "src/tripll/brief.py", "src/tripll/config.py", "src/tripll/cli/__init__.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W1"
  reason = "gate"
  detail = "RED suite defines acceptance"

  [waves.outcome]
  required = [
    "tripll rules derive on a foreign fixture repo writes .tripll/rules and .tripll/context",
    "every derived rule carries an origin resolving to a real file:line in that repo",
    "a rule whose origin does not resolve is rejected by the validator with the offending ref",
    "a dispatched brief carries the rules pack and only the context modules whose scope intersects the wave targets",
    "the rules pack never exceeds pack_budget_tokens",
    "derived rules with no supporting evidence are absent, not invented",
  ]
  forbidden = [
    "a rule written without an origin",
    "packing every context module into every brief",
    "a second doc-quality metric alongside doc_score",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W3"
title = "Bug-to-rule loop: Rule nodes, postmortem, operator promotion"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/ontology/ontology.yaml", "src/tripll/rules", "src/tripll/graphstore/task_sync.py", "src/tripll/github/learnings.py", "src/tripll/cli/__init__.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W2"
  reason = "artifact"
  detail = "promotion writes into the rule store W2 defines"

  [waves.outcome]
  required = [
    "Rule kind exists with a repo-scoped natural key and PREVENTS / PROMOTED_FROM predicates",
    "a resolved Finding yields a proposed Rule carrying its finding:// origin",
    "no agent-reachable path activates a rule: promotion requires tripll rules promote",
    "the wave postmortem diffs declared contract against attempt outcome and names which side was wrong",
    "export_learnings still exports rejected findings unchanged",
    "a rule survives run archival: it resolves after its origin run leaves runs/processing",
  ]
  forbidden = [
    "an agent-writable path from proposed to active",
    "a second learnings renderer alongside github/learnings.py",
    "run-scoped natural keys on Rule",
    "any change to the code or task ontology layers",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W4"
title = "Executable rules — structural checks at the boundary gate"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/rules/executable.py", "src/tripll/harness/boundary.py", "Makefile", "docs/harness-checks.md"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W3"
  reason = "artifact"
  detail = "a rule must exist before it can be made executable"

  [waves.outcome]
  required = [
    "make rules-check runs every executable rule and exits non-zero on a violation",
    "the no-stdlib-logging rule is executable and catches a planted violation",
    "a scope breach of shape is reported through the same harness path as a path breach",
    "ast-grep absent degrades to prose-only with a warning and a zero exit, never a crash",
  ]
  forbidden = [
    "a hard dependency on ast-grep in the base install",
    "a rules gate that always exits 0",
    "duplicating boundary.py's reporting path",
  ]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W5"
title = "Calibration — predicted first-pass, scored against the ledger"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/calibrate", "src/tripll/plan/shape_checks.py", "src/tripll/graphstore/task_sync.py", "src/tripll/report.py", "src/tripll/cli/__init__.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W3"
  reason = "artifact"
  detail = "postmortem rows are the realized-outcome source the scorer reads"

  [[waves.depends_on]]
  wave = "W4"
  reason = "artifact"
  detail = "rule-scope intersection is a predictor feature; W4 is the last wave that changes what an active rule means"

  [waves.outcome]
  required = [
    "compile_plan emits one PREDICTED Metric per wave from features already computed",
    "tripll calibrate reads ledger attempts and writes REALIZED Metrics plus a Brier score",
    "attempts_to_green and first_attempt_pass_rate are computed and reported per run",
    "the predictor is advisory: routing, model, attempt budget and gates are byte-identical with it on and off",
    "a run with no prior history still completes and reports the predictor as uncalibrated",
  ]
  forbidden = [
    "any prediction feeding routing, model selection, attempt budget or gate behaviour",
    "a ledger schema change",
    "new node kinds when Hypothesis, Experiment and Metric already exist",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W6"
title = "Tracker protocol and the plan round trip"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/trackers", "src/tripll/github/issues.py", "src/tripll/cli/__init__.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W5"
  reason = "artifact"
  detail = "cli.py is a serialized writer; W5 lands its calibrate command first"

  [waves.outcome]
  required = [
    "Tracker protocol has one working github implementation and no provider-specific names in base.py",
    "tripll plan publish is idempotent: a second run creates nothing and reports every skip",
    "side effects are ordered local artifact then summary then tickets, and a mid-way failure leaves the local artifact intact",
    "a second Tracker can be added without editing base.py, proven by a fake in the suite",
  ]
  forbidden = [
    "a hard dependency on any tracker SDK",
    "MCP tool ids in source or in an agent prompt",
    "a tracker call on the dispatch hot path",
  ]
  evidence = ["test_output", "command_output"]

[[waves]]
id = "W7"
title = "Adoption artifacts — the narrative, the diagram, the docs"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["README.md", "about-tripll/_sources", "docs/runbooks/rules-runbook.md", "CLAUDE.md", "CHANGELOG.md"]
verify = ["make lint", "make about-site-check"]

  [[waves.depends_on]]
  wave = "W6"
  reason = "gate"
  detail = "docs describe shipped behaviour"

  [waves.outcome]
  required = [
    "README opens with why before how and reaches a first run in under 20 lines",
    "one committed pipeline diagram renders without a network fetch",
    "docs/runbooks/rules-runbook.md covers derive, propose, promote, retire and the executable path",
    "make about-site-check passes",
    "every command named in the new docs exists in tripll --help",
  ]
  forbidden = ["documenting a command this plan did not ship", "an external asset fetch in the about-site"]
  evidence = ["command_output", "final_diff"]

[[waves]]
id = "Final"
title = "xfail sweep, full gate, change summary"
role = "impl"
effort = "S"
provider = "cursor_local"
model = "claude-opus-5"
targets = ["tests", "CHANGELOG.md", "docs/test-plans/ai-layer-compounding.md"]
verify = ["make ci-resume"]

  [[waves.depends_on]]
  wave = "W7"
  reason = "gate"
  detail = "the full gate runs on the finished tree"

  [waves.outcome]
  required = [
    "make ci-resume green twice consecutively",
    "a green GitHub Actions run on the branch head",
    "zero stale xfails referencing a wave that is done",
    "every parked wave declared with a reason and an issue number",
  ]
  forbidden = ["a weakened acceptance criterion anywhere in the diff"]
  evidence = ["test_output", "ci_run_id"]
```

---

## Worktree & branch

```bash
cd /Users/alex/Documents/code/sevn.bot/tripll
git worktree add ../tripll-ai-layer wave/ai-layer-compounding refactor/mergecraft-replace-pullfrog
cd ../tripll-ai-layer
make setup
```

- **Branch:** `wave/ai-layer-compounding`. **Worktree root:** `../tripll-ai-layer`.
- **Base — the rule, decided now.** Base on `refactor/mergecraft-replace-pullfrog` (`a4fbd0d`).
  `main` (`9a3f19d`) is **26 commits behind** and predates both the mergeCraft rename and the CLI
  extraction, so `src/tripll/cli/__init__.py` — which W5 and W6 both edit — does not exist there
  under that path. **If that branch merges to `main` before dispatch, rebase and set
  `base = "main"`;** record which was used in Re-entry either way.
- **Git safety:** never `git clean -x` / `-X` (`CLAUDE.md`).

## Docs touched

- `README.md` — the adoption narrative (W7), the rules commands, `tripll calibrate`
- `CLAUDE.md` — `rules` / `calibrate` / `plan publish` in the command table; the rule that
  **only an operator activates a rule** (R27), stated where an agent will actually read it
- `docs/harness-checks.md` — structural scope breach as a sixth harness failure class (W4)
- `docs/design-note.md` — §0.1 gains the `Rule` kind; §0.4 telemetry seams gain the calibration loop
- `docs/ontology.md` — `Rule`, `PREVENTS`, `PROMOTED_FROM`
- `about-tripll/_sources/*.yaml` — same narrative; regenerate with `make about-site`
- `CHANGELOG.md` — `## [Unreleased]` bullet per wave
- **new** `docs/decisions/014-*.md` … `017-*.md` — ADRs for the irreversible calls.
  **013 is reserved for the L1 plan's onboarding ADR (R23), which has not landed**; if it is still
  free at W0, this plan keeps 014–017 rather than backfilling, so no ADR number is ever reused
- **new** `docs/runbooks/rules-runbook.md`, `docs/test-plans/ai-layer-compounding.md`,
  `docs/plans/ai-layer-compounding.md`

## Goal

Close the compounding gap: a failure in run *N* becomes a constraint that run *N+1* cannot repeat,
and a prediction made before dispatch is scored against what actually happened. End state:
`tripll init` derives cited rules and context modules from real code; a resolved Finding proposes a
Rule that an operator activates; rules that can be executable are, and fail `make rules-check`;
every wave carries an advisory first-pass prediction scored against the ledger; a plan round-trips
to a tracker idempotently; and the README says why before it says how.

## Files in scope

| Area | Paths |
|------|-------|
| Rules core (W2, W3) | **new** `src/tripll/rules/{model,derive,store,pack,promote,postmortem}.py` |
| Brief packing (W2) | `src/tripll/brief.py`, `src/tripll/serve/brief_packer.py` |
| Onboarding (W2) | `src/tripll/onboard/{emitters,evaluate}.py` |
| Ontology (W3, W5) | `src/tripll/ontology/ontology.yaml`, `src/tripll/graphstore/task_sync.py` |
| Findings (W3) | `src/tripll/github/{findings,learnings}.py` |
| Executable rules (W4) | **new** `src/tripll/rules/executable.py`, `src/tripll/harness/boundary.py`, `Makefile` |
| Calibration (W5) | **new** `src/tripll/calibrate/{predict,score}.py`, `src/tripll/plan/shape_checks.py`, `src/tripll/report.py` |
| Trackers (W6) | **new** `src/tripll/trackers/{base,github}.py`, `src/tripll/github/issues.py` |
| CLI (W2–W6) | `src/tripll/cli/__init__.py` |
| Docs (W7) | `README.md`, `CLAUDE.md`, `about-tripll/**`, `docs/**` |
| Tests (W1) | **new** `tests/test_rules*.py`, `test_postmortem.py`, `test_calibrate.py`, `test_trackers.py` |

## Global conventions

1. **Worktree only** on `wave/ai-layer-compounding`. Never `git clean -x` / `-X`.
2. **Tests-first.** W1 (`test-creator`) authors the RED suite; impl waves turn it green and are
   **forbidden from editing `tests/`** except via `test-creator` re-dispatch. Cross-wave reds use
   `@pytest.mark.xfail(reason="green after W<N>: …", strict=False)`.
3. **Make/uv only.** Per wave: `make lint`, `make typecheck`, `make test`; mid-wave scoped gate
   `make ci-affected`. Full gate at Final via `make ci-resume`. Never raw `pytest` / `ruff` / `mypy`.
4. **Every wave ends with commit + push.** Conventional commit; CHANGELOG bullet in the **same**
   commit when `src/` changes; **Re-entry block updated in the same commit**.
5. **Conventional Commits** — validate with `python scripts/check_conventional_commit.py --message …`.
   No `--no-verify`.
6. **No new hard dependency.** `ast-grep` (W4) and every tracker SDK (W6) are optional and degrade.
   `CLAUDE.md`: tripll is standalone.
7. **loguru only.** W4's first executable rule is precisely this one — it must catch a planted
   violation in this repo, or the wave has not landed.
8. **Every rule cites its origin.** A rule without a resolving `file:line` or `finding://` ref is a
   defect, not a style preference. W2's validator enforces it; Thermos re-checks it.
9. **Path convention:** repo-root-relative.
10. **Re-grep before editing.** Every anchor here is an `a4fbd0d` line number and will drift.
11. **Observable acceptance.** Every `**Acceptance:**` block is a runnable command with an expected
    value.
12. **PARKED is a legal outcome; a weakened criterion is not.**

### Test tiers

| Tier | Covers | Runs | Blocks? |
|------|--------|------|---------|
| **1 — offline** | rule model, derivation on a fixture, pack budget, predictor math, tracker fakes | every `make test` | yes |
| **2 — live, gated** | real `ast-grep` binary, real `gh` against a scratch repo — behind `RUN_LIVE=1` | wave close-out + Final | yes when run |
| **3 — e2e smoke** | one real run: derive → propose → promote → pack into a brief | every `make test` | yes |
| **4 — canary** | `ast-grep` availability, GitHub API reachability | never blocks; reported | **no** |

| Test | Tier | Why |
|------|------|-----|
| `test_rules.py`, `test_rules_derive.py` | 1 | fixture repo, no network |
| `test_rules_executable.py` structural match | 1 | pattern matching against a fixture tree |
| `test_rules_executable.py` real binary | **2** | requires `ast-grep` on PATH |
| `test_postmortem.py` | 1 | synthetic ledger rows |
| `test_calibrate.py` | 1 | fixed feature vectors, asserted Brier score |
| `test_trackers.py` fake tracker | 1 | protocol conformance, no network |
| `test_trackers.py` real `gh` | **2** | scratch repo, `RUN_LIVE=1` |
| derive → promote → pack e2e | **3** | the loop this plan exists to build |
| `ast-grep` present, GitHub reachable | **4** | tests the world; never blocks |

### Wave status

| Status | Meaning | Required with it |
|--------|---------|------------------|
| `[ ]` | not started | — |
| `[x]` | done, pushed, **CI green on that sha** | sha + run id in the change summary |
| `[P]` | **PARKED** — attempted, could not be closed honestly | a one-line reason **and** a filed issue number |

A wave parks after **3 failed attempts** on the same blocking item, or when its outcome contract
cannot be satisfied without weakening a criterion. **Criteria are never deleted or narrowed to reach
`[x]`.** Plan-level stop rule: at **3 parked waves, stop**.

### Per-wave close-out

1. Verification green for that wave. 2. Run the wave's `**Acceptance:**` commands; paste real output
into the commit body. 3. Stage the CHANGELOG bullet when `src/` is touched. 4. Update Re-entry.
5. Commit. 6. Push (no force-push). 7. Confirm CI green on that sha; flip the checkbox with
`(YYYY-MM-DD ✅: <sha> — <run-id> green)`, or to `[P]` with reason + issue.

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| R26 | Rules are graph nodes, not a file format | A `Rule` is a first-class node with a **repo-scoped** natural key (`{repo}#{rule_id}`), rendered to committed markdown. Rejected: rules as a plain directory of markdown — it cannot express `PREVENTS` back to the Finding that produced it, and provenance is the only thing separating a rule from an opinion. Rejected: rules as run-scoped nodes — every other kind in the `finding` layer is `{run_id}#…`, which is exactly why nothing there compounds. ADR 014. |
| R27 | Only an operator activates a rule | Agents may propose; **`proposed → active` requires `tripll rules promote`**, a human command. An agent that can write its own binding constraints will eventually write one that excuses its own failure, and nothing downstream catches it. This is the same reasoning as D15 (tripll never auto-merges), applied to constraints instead of code. Rejected: auto-promotion on a confidence threshold — the failure mode is silent and permanent. |
| R28 | Calibration is advisory, permanently | Predicted first-pass probability may be displayed, logged and scored. It may **never** feed routing, model choice, attempt budget or gates (R16's reasoning: an unpredictable, unauditable run). A predictor that steers the run it predicts cannot be scored, and a miscalibrated one would starve the waves that need the most attempts. Feedback into routing is a separate program. ADR 015. |
| R29 | Executable beats prose | Where a rule *can* be expressed structurally, it **must** also be executable. A prose rule in a brief is enforced by the agent's attention; an executable rule is enforced by the gate. Prose-only remains legal for genuinely semantic rules. Rejected: prose-only rules everywhere (the pack's shape — it has no enforcement at all), and executable-only (most real constraints are semantic). ADR 017. |
| R30 | One tracker protocol, one implementation | W6 ships `Tracker` + `github`. Jira/Confluence is **not implemented** — the deliverable is a seam proven by a fake in the suite. Rejected: shipping an Atlassian integration (a hard dependency on another product's SDK, forbidden by `CLAUDE.md`), and calling MCP tool ids from an agent prompt (the pack's approach — it hardcodes `mcp__atlassian__*` in prose, which is unversioned coupling to a tool id). ADR 016. |
| R31 | Context modules complement the graph pack | Context modules carry **only** what the AST cannot: gotchas, legacy-vs-forward decisions, local environment quirks. They are packed **on demand** by scope intersection, under a token budget. Rejected: replacing graph packing with prose context (a regression to the pre-D23 grep brief), and packing every module into every brief (the context bloat `create-rules` itself warns against). |
| R32 | Derivation never invents | `tripll rules derive` emits a rule **only** where the code supports it, and says so plainly when it finds nothing — no coverage standard the repo does not enforce, no aspirational rule. Derived rules run through `doc_score.py`'s scaffold-phrase penalty for exactly this reason. Rejected: seeding from a best-practice template — that is the "generic pack" failure the source repo warns about and then commits itself, hardcoding `uv run pytest` and `mypy app/` into a supposedly codebase-agnostic skill. |

## Out of scope

- **Reimplementing the PIV loop** — a strict subset of tripll's wave model.
- **Porting `new-worktrees` / `merge-worktrees`** — `integrate.py` and lane worktrees supersede them.
- **Prediction-driven routing** (R28) — advisory only, permanently, until a separate program earns it.
- **A Jira or Confluence implementation** (R30) — the protocol only.
- **Rewriting `report.py` into an execution-report generator** — W3's postmortem is a new artifact
  beside it, not a replacement; `report.py` is the ops view and stays.
- **Auto-fix from a rule violation** — W4 reports; it never rewrites code.
- **Rule inheritance, priority, or conflict resolution** — flat `active` set under a token budget.
  Ordering matters only once the budget binds; revisit with evidence.
- **Retiring `.mergecraft/learnings.md`** — the negative channel keeps working unchanged (W3
  forbids touching its behaviour); the positive channel is added beside it.
- **Any L2 work beyond calibration telemetry** — unchanged from the L1 program.

## Wave checklist

| Wave | Provider / model | Scope | Findings | Status |
|------|------------------|-------|----------|--------|
| W0 | `cursor_local` claude-opus-5 | Baseline, anchor re-grep, ADRs 014–017, contract pin, compile the machine block | — | [x] (2026-07-29 ✅: f05f8e9 — 4 ADRs, validate-plan exit 0, issues #53–#55) |
| W1 | `cursor_local` auto | RED suite (tier-tagged) + `docs/test-plans/ai-layer-compounding.md` — `role: test-author` | all | [ ] |
| W2 | `cursor_local` auto | **Derived rules + context modules**: `tripll rules derive`, origin validator, scoped brief packing | CTX-01, CTX-02, CTX-03 | [ ] |
| W3 | `cursor_local` auto | **Bug-to-rule loop**: `Rule` node kind, wave postmortem, operator promotion | RULE-01, RULE-02, RULE-03 | [ ] |
| W4 | `cursor_local` auto | **Executable rules**: ast-grep backend, `make rules-check`, structural scope breach | AST-01, AST-02 | [ ] |
| W5 | `cursor_local` auto | **Calibration**: predicted first-pass, `tripll calibrate`, Brier score, attempts-to-green | CAL-01, CAL-02, CAL-03 | [ ] |
| W6 | `cursor_local` auto | **Tracker protocol** + idempotent plan round trip | PM-01, PM-02 | [ ] |
| W7 | `cursor_local` auto | **Adoption**: narrative README, committed diagram, rules runbook, about-site | ADOPT-01, ADOPT-02 | [ ] |
| Final | `cursor_local` claude-opus-5 | xfail sweep, `make ci-resume` green, green CI on the branch, change summary | — | [ ] |
| Thermos | `cursor_local` claude-opus-5, **fresh session** | Branch review, tamper audit, merge request | — | [ ] |

Every `auto` wave carries `fallback = ["claude_code"]`. Failover changes the **provider only**.

## Execution order & parallelism

**Dispatched order (serial — by choice):**

```text
W0 → W1 → W2 → W3 → W4 → W5 → W6 → W7 → Final → Thermos
```

| Hard dependency | Reason |
|-----------------|--------|
| W1 before W2–W7 | RED suite defines acceptance |
| **W2 before W3** | promotion needs somewhere to write. A `Rule` node with no store and no renderer is a schema change nobody can see |
| **W3 before W4** | a rule must exist before it can be made executable. Building the checker first produces an engine with nothing to run |
| W3 before W5 | the postmortem rows are the realized-outcome source the scorer reads |
| **W4 before W5** | rule-scope intersection is one of the predictor's features, so the rule set must be settled first. It is *also* what keeps W5 and W6 out of the same antichain — without this edge `compile_plan` reports a one-writer violation on `cli/__init__.py` |
| W5 before W6 | `cli/__init__.py` is a serialized writer — `calibrate` lands before `plan publish` |
| W7 last | docs describe shipped behaviour |

**Why serial.** Per-wave *commit → push → green CI on that sha* is this plan's acceptance mechanism.
W2→W3→W4 is a genuine chain (store → node → checker), and W5/W6/W7 all write `cli/__init__.py` or
docs describing the others. The honest parallel width is ~1.5 waves; it is not worth diluting the gate.

### Merge hotspots

| File | Waves | Note |
|------|-------|------|
| `src/tripll/cli/__init__.py` | W2, W3, W4, W5, W6 | five waves add commands to one Typer app — **serialize** |
| `src/tripll/ontology/ontology.yaml` | W3, W5 | `Rule` kind, then the calibration predicates — W3 is the author |
| `src/tripll/graphstore/task_sync.py` | W3, W5 | node materialization for both layers |
| `src/tripll/rules/**` | W2, W3, W4 | W2 authors the package; W3 and W4 add modules to it |
| `src/tripll/brief.py` | W2 | single writer, but W3's rules reach the brief through it — assert the seam |
| `Makefile` | W4 | `rules-check` target |
| `README.md` / `about-tripll/**` | W7 | single writer, documents W2–W6 |
| `CHANGELOG.md` | all | one bullet stream |

---

## Wave W0 — Baseline, anchors, ADRs, contract pinning

**Blocks:** everything

- [x] **W0.1** Record baseline: `git rev-parse HEAD`, the base branch actually used (see the base
      rule), and whether `refactor/mergecraft-replace-pullfrog` has merged to `main`.
      (2026-07-29 ✅: `a4fbd0d` on `wave/ai-layer-compounding` from `refactor/mergecraft-replace-pullfrog`; `main` at `9a3f19d`, 26 commits behind, not merged)
- [x] **W0.2** **Re-grep every anchor** in the gap table at HEAD and correct it in place. The five
      that matter most, because whole waves rest on them:
      `ontology.yaml` finding-layer line range; `github/learnings.py` rejected-filter line;
      `cli/__init__.py` findings-command range; the `Hypothesis` grep returning only a skill file;
      the `ast.grep` grep returning empty.
      (2026-07-29 ✅: corrected `learnings.py:30`, `cli:1442–1560`, CAL-02/03 anchors, `Hypothesis` *.py empty)
- [x] **W0.3** Write ADRs **014** (rules as graph nodes, R26/R27), **015** (calibration advisory
      only, R28), **016** (tracker protocol, R30), **017** (executable rules, R29). Each states its
      **rejected alternative** — an ADR without one is a description, not a decision.
      (2026-07-29 ✅: `docs/decisions/014-*.md` … `017-*.md` with `## Rejected` sections)
- [x] **W0.4** File out-of-scope issues: prediction-driven routing, a Jira implementation, rule
      conflict resolution. Record the numbers in *Success criteria*.
      (2026-07-29 ✅: #53 prediction routing, #54 Jira, #55 rule conflict)
- [x] **W0.5** Copy this file to `docs/plans/ai-layer-compounding.md`; record both sha256 values in
      Re-entry.
      (2026-07-29 ✅: copied; sha256 recorded in Re-entry)
- [x] **W0.6** **Re-compile the machine block at HEAD.** It compiled clean on 2026-07-29 (9 waves,
      0 dropped edges, max parallel group 1) — re-run `tripll validate-plan` and
      `plan.shape_checks.compile_plan` and confirm nothing drifted. If it does not compile,
      **fix this plan**, not the compiler.
      (2026-07-29 ✅: validate-plan exit 0)
- [x] **W0.7** **Commit + push** (`docs(plan): baseline and ADRs for AI-layer compounding`).
      (2026-07-29 ✅: f05f8e9 pushed)

**Acceptance:**

```bash
ls docs/decisions/01{4,5,6,7}-*.md | wc -l          # 4
grep -c 'Rejected' docs/decisions/014-*.md          # >= 1, and same for 015-017
tripll validate-plan docs/plans/ai-layer-compounding.md   # exit 0
shasum -a 256 docs/plans/ai-layer-compounding.md    # recorded in Re-entry
grep -rn 'Hypothesis' src/tripll | grep -v skills/  # still empty, or the anchor is corrected
```

---

## Wave W1 — Test suite (RED) — `role: test-author`, agent: test-creator

**Depends:** W0 · **Blocks:** W2–W7

- [ ] **W1.1** `tests/test_rules.py` — rule model, frontmatter round trip, the three states,
      **origin validation** (a rule whose `file:line` does not resolve is rejected, and the error
      names the offending ref).
- [ ] **W1.2** `tests/test_rules_derive.py` — derivation against a **foreign fixture repo**
      (neither tripll nor sevn): rules carry resolving origins; a repo with no tests produces an
      artifact that *says* there are no tests rather than one asserting a coverage standard (R32).
- [ ] **W1.3** `tests/test_rules.py` pack tests — scope intersection selects the right context
      modules; the pack never exceeds `pack_budget_tokens`; an empty rule set yields an empty pack,
      not a crash.
- [ ] **W1.4** `tests/test_rules_executable.py` — tier-1 structural matching on a fixture tree;
      **tier-2** real-binary run behind `RUN_LIVE=1`; `ast-grep` absent degrades with a warning and
      exit 0.
- [ ] **W1.5** `tests/test_postmortem.py` — synthetic ledger rows in, a delta out that names
      **which side was wrong**: contract-too-vague vs agent-diverged.
- [ ] **W1.6** `tests/test_calibrate.py` — fixed feature vectors produce an asserted Brier score;
      **the advisory assertion**: routing, model, attempt budget and gate decisions are byte-identical
      with the predictor on and off. That last one is the test that keeps R28 true.
- [ ] **W1.7** `tests/test_trackers.py` — a fake `Tracker` proves protocol conformance without
      touching `base.py`; idempotent publish creates nothing on a second run.
- [ ] **W1.8** e2e (tier 3): derive → propose → promote → pack, asserting the rule reaches a brief.
- [ ] **W1.9** `docs/test-plans/ai-layer-compounding.md` — finding → test → wave → tier matrix.
- [ ] **W1.10** **Commit + push** (`test: RED suite for AI-layer compounding`).

**Acceptance:**

```bash
make test                                            # collects clean; new tests xfail, none error
grep -rn 'strict=True' tests/test_rules*.py tests/test_calibrate.py | wc -l   # 0
grep -rc 'tier[1-4]' tests/test_rules.py             # >= 1, and same for each new file
```

---

## Wave W2 — Derived rules and on-demand context modules

**Findings:** CTX-01, CTX-02, CTX-03 · **Decisions:** R26, R31, R32 · **Depends:** W1

The wave that gives rules somewhere to live. Everything after it writes into what this builds.

- [ ] **W2.1** `src/tripll/rules/model.py` — the `Rule` dataclass, frontmatter schema, the three
      states, and the **origin validator**. Reuse the frontmatter machinery in `skw/spec_validate.py`
      rather than authoring a second parser.
- [ ] **W2.2** `src/tripll/rules/store.py` — read/write `.tripll/rules/<rule_id>.md`, listing and
      lookup. Files are the committed source; the graph replica lands in W3.
- [ ] **W2.3** *(CTX-01)* `src/tripll/rules/derive.py` + **`tripll rules derive`**. Consume
      `onboard/evaluate.py::_build_findings`, which already emits `file:line`-cited findings —
      **do not re-analyse the repo**. Emit rules in **descending generality** (project one-liner,
      naming, core patterns, build commands, context table, hard rules, gotchas) with hard rules
      near the bottom, and an append-only **Gotchas** section at the end.
- [ ] **W2.4** *(R32)* **Honesty gate.** Run every derived rule through `skw/doc_score.py`'s
      scaffold-phrase penalty and drop anything that scores as filler. Where the repo has no tests,
      emit "this repo has no unit tests" — never a coverage standard it does not enforce.
- [ ] **W2.5** *(CTX-02)* `src/tripll/rules/pack.py` — render the active rule set plus the context
      modules whose `scope` intersects the wave's `targets`, under `pack_budget_tokens`. Over budget
      drops **context modules first, rules never** — a constraint that silently falls out of a brief
      is worse than no constraint, because everyone believes it is in force.
- [ ] **W2.6** Wire the pack into `brief.py` **beside** `enrich_brief_with_graph_pack`, not inside
      it. The graph pack stays the structural channel; rules and context are a second, labelled
      section, so `--grep-brief` A/B replay still isolates the graph pack's contribution (D23).
- [ ] **W2.7** *(CTX-03)* `tripll init` emits `.tripll/rules/` and `.tripll/context/` alongside the
      existing specs/PRDs/plans, and the evaluation links to them. **Idempotent** — a second `init`
      reconciles and never clobbers an operator-edited rule without `--force`.
- [ ] **W2.8** Add `[rules]` to the config spine (`config.py`), inheriting the existing four-layer
      precedence. Do not add a fifth resolution path.
- [ ] **W2.9** **Commit + push** (`feat(rules): derive cited rules and on-demand context modules`).

**Acceptance:**

```bash
make test -- -k "rules or derive"                    # green
d=$(mktemp -d) && git -C "$d" init -q && mkdir -p "$d/src" \
  && printf 'import logging\nlog = logging.getLogger(__name__)\n' > "$d/src/a.py"
(cd "$d" && tripll init && tripll rules derive)
ls "$d"/.tripll/rules/*.md                           # non-empty
# every rule cites something real:
grep -h '^origin:' "$d"/.tripll/rules/*.md           # every line is codebase://<file>:<line>
python - "$d" <<'PY'
import pathlib,re,sys
root=pathlib.Path(sys.argv[1])
bad=[]
for r in (root/'.tripll/rules').glob('*.md'):
    m=re.search(r'^origin:\s*codebase://(.+):(\d+)',r.read_text(),re.M)
    assert m, f'{r}: no origin'
    f=root/m.group(1)
    if not f.exists() or len(f.read_text().splitlines())<int(m.group(2)): bad.append(str(r))
assert not bad, bad
print('all origins resolve')
PY
# no test claim in a repo with no tests (R32):
grep -ri 'coverage' "$d"/.tripll/rules/ | wc -l      # 0
# idempotent:
echo '<!-- operator edit -->' >> "$d"/.tripll/rules/*.md && (cd "$d" && tripll init)
grep -rc 'operator edit' "$d"/.tripll/rules/ | grep -v ':0'   # survived
```

The fixture repo must be **neither tripll nor sevn** — deriving rules only against our own checkout
is the mistake `LEGACY_CW_BUCKETS` made (ARCH-CW), and the L1 plan just finished fixing it.

---

## Wave W3 — Bug-to-rule loop

**Findings:** RULE-01, RULE-02, RULE-03 · **Decisions:** R26, R27 · **Depends:** W2

The wave this plan exists for. tripll already knows what went wrong; this is where that knowledge
stops evaporating when the run directory is archived.

- [ ] **W3.1** *(RULE-01)* Add `Rule` to the `finding` layer in `ontology.yaml` with natural key
      `{repo}#{rule_id}` — **repo-scoped**. Every other kind in that layer is `{run_id}#…`, which is
      precisely why nothing there compounds. Add predicates `PREVENTS` (`Rule` → `Finding`) and
      `PROMOTED_FROM` (`Rule` → `Finding`). Materialize in `graphstore/task_sync.py`.
- [ ] **W3.2** *(RULE-03)* `src/tripll/rules/postmortem.py` — after a wave reaches a terminal state,
      diff its **declared contract** (`[waves.outcome]` required / forbidden, `targets`) against the
      **attempt record** (outcome, scope breaches, attempt count, verify results). Classify the
      delta: *contract too vague* · *agent diverged* · *environment* · *external*. Write
      `runs/<run-id>/postmortem/<node-id>.md` beside `logs/`, so it travels with the run.
- [ ] **W3.3** *(RULE-02)* `src/tripll/rules/promote.py` — a Finding in a resolved state proposes a
      `Rule` in state `proposed`, carrying `origin: finding://<run>#<id>` and a **suggested
      regression test name**. Reuse `github/findings.py::list_findings_from_store`; do not add a
      second reader.
- [ ] **W3.4** *(R27)* **`tripll rules promote <rule_id>` / `retire <rule_id>` — operator-only.**
      There must be **no agent-reachable path** from `proposed` to `active`: not a CLI flag, not an
      env var, not an `--auto` switch. W1.1 asserts the absence. This is D15's reasoning applied to
      constraints — the failure mode of a self-activating rule is silent and permanent.
- [ ] **W3.5** The **positive** channel, beside the negative one. `.mergecraft/learnings.md` keeps
      exporting rejected findings **unchanged** (its behaviour is `forbidden` in this wave's
      contract); active rules render through the same `github/learnings.py` renderer into their own
      section. One renderer, two sections — sevn shipped two renderers and regretted it.
- [ ] **W3.6** Only `active` rules pack (W2.5). `proposed` rules are visible to the operator via
      `tripll rules list` and invisible to every agent.
- [ ] **W3.7** `docs/design-note.md` §0.1 gains the `Rule` kind; `docs/ontology.md` gains the two
      predicates.
- [ ] **W3.8** **Commit + push** (`feat(rules): promote findings to durable rules with provenance`).

**Acceptance:**

```bash
make test -- -k "rules or postmortem"                # green
grep -n 'Rule:' src/tripll/ontology/ontology.yaml    # present
grep -A2 'Rule:' src/tripll/ontology/ontology.yaml | grep 'natural_key'   # {repo}#{rule_id}
# no agent-reachable activation (R27):
grep -rn 'auto_promote\|auto-activate\|state="active"' src/tripll/rules/promote.py | wc -l   # 0
tripll rules list --state proposed                   # lists; does not activate
# the negative channel is untouched:
git diff <base>...HEAD -- src/tripll/github/learnings.py | grep '^-' | grep 'rejected' | wc -l  # 0
# a rule outlives its run:
tripll rules list --state active | head              # resolves with runs/processing empty
```

**The test that proves the wave:** a rule promoted from run A is packed into a brief in run B, after
run A's directory has been archived. If that does not hold, this wave built a report, not a loop.

---

## Wave W4 — Executable rules

**Findings:** AST-01, AST-02 · **Decisions:** R29 · **Depends:** W3

- [ ] **W4.1** *(AST-01)* `src/tripll/rules/executable.py` — an `ast-grep` backend behind
      `[rules] executable`. A rule may carry a structural pattern; the module runs it and returns
      matches with `file:line`. **Optional dependency**: absent binary ⇒ warn, prose-only, exit 0.
- [ ] **W4.2** `make rules-check` — run every `active` executable rule; exit non-zero on a
      violation. A gate that always exits 0 is decoration (the `doctor` lesson, W13 of the L1 plan).
- [ ] **W4.3** **The first executable rule is `no-stdlib-logging`**, derived from this repo's own
      `CLAUDE.md`. It must catch a planted `import logging` in `src/tripll/` — a rule engine that
      cannot enforce the one rule this repo states most loudly has not landed.
- [ ] **W4.4** *(AST-02)* Report a structural violation through **`harness/boundary.py`'s existing
      path**, as a scope breach of *shape* rather than *path*. Same reporting seam, new checker —
      do not add a second breach type with its own plumbing.
- [ ] **W4.5** Add `make rules-check` to `ci-affected` (scoped to changed paths) and to `ci-resume`.
- [ ] **W4.6** `docs/harness-checks.md` — structural scope breach as a sixth failure class.
- [ ] **W4.7** **Commit + push** (`feat(rules): executable structural rules and the rules gate`).

**Acceptance:**

```bash
make test -- -k executable                           # green
make rules-check                                     # exit 0 on a clean tree
printf 'import logging\n' >> src/tripll/repo_root.py && ! make rules-check; echo "caught=$?"
git restore src/tripll/repo_root.py
PATH=/usr/bin:/bin make rules-check                  # ast-grep absent: warns, exit 0
grep -n 'rules-check' Makefile                       # wired into ci-affected and ci-resume
grep -rn 'ast_grep\|ast-grep' pyproject.toml         # optional extra only, never a base dep
```

---

## Wave W5 — Calibration

**Findings:** CAL-01, CAL-02, CAL-03 · **Decisions:** R28 · **Depends:** W3

The ontology already has the nodes. This wave writes them.

- [ ] **W5.1** *(CAL-01)* `src/tripll/calibrate/predict.py` — a first-pass probability per wave from
      features **already computed** at compile: module count, CALLS fan-out, `effort`, target count,
      contract clause count, and whether the wave's targets intersect any active rule's scope. Start
      with an explicit linear model with published weights, not a fitted one — an uninterpretable
      predictor that cannot be argued with is worse than a crude one that can.
- [ ] **W5.2** *(CAL-02)* Emit one `Metric` node per wave via `PREDICTED`, grouped under an
      `Experiment` per run, using the kinds and predicates **already in `ontology.yaml:167–190`**.
      No new node kinds.
- [ ] **W5.3** *(CAL-03)* `src/tripll/calibrate/score.py` + **`tripll calibrate`** — read
      `ledger.attempts`, compute `attempts_to_green` and `first_attempt_pass_rate` per run, write
      `REALIZED` Metrics, and report a **Brier score** per predictor version. No ledger migration:
      `attempt_n` and `outcome` are already per-attempt columns.
- [ ] **W5.4** *(R28)* **The advisory assertion.** A run with the predictor enabled and one with it
      disabled must produce **byte-identical** routing, model selection, attempt budgets and gate
      decisions. W1.6 asserts this; it is the criterion that keeps R28 true after everyone forgets
      why it was written.
- [ ] **W5.5** Surface in `report.py`: predicted vs actual per wave, and the run's Brier score. With
      fewer than N prior runs, report **"uncalibrated"** rather than a meaningless number.
- [ ] **W5.6** `docs/design-note.md` §0.4 — the calibration loop as a named L2 seam.
- [ ] **W5.7** **Commit + push** (`feat(calibrate): predicted first-pass scored against the ledger`).

**Acceptance:**

```bash
make test -- -k calibrate                            # green
tripll calibrate --run <run-id>                      # prints per-wave predicted vs actual + Brier
grep -rn 'attempts_to_green' src/tripll | wc -l      # >= 1 — CAL-03 inverted
grep -rn 'Hypothesis\|Experiment' src/tripll --include='*.py' | wc -l   # >= 1 — CAL-02 inverted
# advisory only (R28) — no prediction on any decision path:
grep -rn 'predict' src/tripll/engine.py src/tripll/adapters/ | wc -l    # 0
make test -- -k test_prediction_does_not_change_routing                # green
# no ledger migration:
git diff <base>...HEAD -- src/tripll/ledger.py | grep -c 'CREATE TABLE\|ALTER TABLE'   # 0
```

---

## Wave W6 — Tracker protocol and the plan round trip

**Findings:** PM-01, PM-02 · **Decisions:** R30 · **Depends:** W5

- [ ] **W6.1** *(PM-01)* `src/tripll/trackers/base.py` — the `Tracker` `Protocol`
      (`fetch_epic`, `list_children`, `create_child`, `publish_breakdown`) with **no
      provider-specific vocabulary**. If the word `gh`, `issue` or `PR` appears in `base.py`, the
      protocol is GitHub-shaped and the wave has not landed.
- [ ] **W6.2** `src/tripll/trackers/github.py` — the one real implementation, wrapping the existing
      `github/` module. No new HTTP client.
- [ ] **W6.3** *(PM-02)* **`tripll plan publish <plan> --tracker github --parent <ref>`** — write the
      local artifact, publish the breakdown as a child, then create the missing tickets.
- [ ] **W6.4** **Idempotence by pre-read.** List existing children *first*; match each wave against
      them; create only what is genuinely missing; report every skip. Never create a near-duplicate.
- [ ] **W6.5** **Ordered side effects.** Local artifact → summary → tickets. A mid-way failure leaves
      the local artifact intact and the command re-runnable, because W6.4 makes creation idempotent.
- [ ] **W6.6** *(R30)* Prove the seam with a **fake tracker** in the suite that requires no edit to
      `base.py`. Jira is not implemented; the runbook documents what implementing it would take.
- [ ] **W6.7** **Commit + push** (`feat(trackers): tracker protocol and idempotent plan publish`).

**Acceptance:**

```bash
make test -- -k tracker                              # green
grep -riEn '\b(gh|jira|confluence|linear)\b' src/tripll/trackers/base.py | wc -l   # 0
grep -rn 'mcp__' src/tripll src/tripll/skw/agents | wc -l                          # 0
# idempotent — second publish creates nothing:
tripll plan publish docs/plans/ai-layer-compounding.md --tracker github --parent <ref> --dry-run
tripll plan publish docs/plans/ai-layer-compounding.md --tracker github --parent <ref>
tripll plan publish docs/plans/ai-layer-compounding.md --tracker github --parent <ref> | grep -c 'created 0'
grep -rn 'atlassian\|jira' pyproject.toml | wc -l    # 0 — no SDK dependency
```

---

## Wave W7 — Adoption artifacts

**Findings:** ADOPT-01, ADOPT-02 · **Depends:** W6

The pack's best non-technical observation: its "same epic, two lanes" frame sells the idea in one
image, while tripll's README makes a reader learn *how* before it ever says *why*.

- [ ] **W7.1** *(ADOPT-01)* Restructure the README opening: what tripll is, the problem it solves,
      and **why before how**. A reader reaches a first command within 20 lines. The operator
      reference stays — it moves below the narrative rather than in front of it.
- [ ] **W7.2** *(ADOPT-02)* One committed pipeline diagram — plan → RunGraph → lanes → gates →
      integrate, with the compounding loop this plan adds drawn on it. Reuse
      `skw/pipeline_diagram.py`'s self-contained HTML renderer; **no external asset fetch**.
- [ ] **W7.3** `docs/runbooks/rules-runbook.md` — derive, propose, promote, retire, make a rule
      executable, and read a calibration report. Include what to do when a rule turns out wrong,
      which is the case an operator will actually hit.
- [ ] **W7.4** `CLAUDE.md` — `rules` / `calibrate` / `plan publish` in the command table, and R27
      (**only an operator activates a rule**) stated where an agent will read it.
- [ ] **W7.5** `about-tripll/_sources/*.yaml` — same narrative; `make about-site`.
- [ ] **W7.6** Verify **every command named in the new docs exists**. A README describing software
      that did not land is the failure the L1 plan avoided by ordering W13–W15 before W12.
- [ ] **W7.7** **Commit + push** (`docs: adoption narrative, pipeline diagram, rules runbook`).

**Acceptance:**

```bash
make about-site-check                                # green
head -20 README.md | grep -ci 'why\|problem\|instead of'    # >= 1 — narrative, not a command dump
ls docs/*.svg docs/*.html about-tripll/assets/* 2>/dev/null | grep -c pipeline   # >= 1
grep -rEn 'https?://' about-tripll/assets/*pipeline* | wc -l    # 0 — no external fetch
# every documented command exists:
for c in "rules derive" "rules promote" "rules list" "calibrate" "plan publish"; do
  tripll $c --help >/dev/null 2>&1 || echo "MISSING: $c"
done
```

---

## Final wave — gate, commit & push

- [ ] **F.1** test-creator: drop every satisfied xfail; update `docs/test-plans/ai-layer-compounding.md`.
- [ ] **F.2** `make ci-resume` until green, then **run the full suite twice consecutively**.
- [ ] **F.3** **Confirm a green GitHub Actions run on the branch head** — not a local pass.
- [ ] **F.4** Re-run this plan's own spot checks; each must invert (see *Success criteria*).
- [ ] **F.5** Change summary table (Wave | Headline | Provider/model | sha | CI run | Parked).
- [ ] **F.6** Declare every parked wave explicitly. If ≥3 are parked, **stop here**.
- [ ] **F.7** **Commit + push** (`chore: finalize AI-layer compounding`).

**Acceptance:**

```bash
make ci-resume && make ci-resume                     # green twice
gh run list --workflow=CI --branch wave/ai-layer-compounding --limit 1 --json conclusion
grep -rn 'xfail' tests/ | grep -c 'green after W'    # 0
```

---

## Thermos gate

- [ ] **T.1** **Contract-tampering audit — before any code review.** Work only from the contract
      (`docs/plans/ai-layer-compounding.md`), the Re-entry block, and the diff.

      ```bash
      shasum -a 256 docs/plans/ai-layer-compounding.md   # must match the W0.5 value
      git diff <base>...HEAD -- tests/                   # read every deletion and weakening
      grep -rn 'xfail' tests/ | grep 'green after W'     # any left whose wave is [x] is tampering
      git diff <base>...HEAD -- tests/ | grep '^-' | grep -i 'assert'
      ```

- [ ] **T.2** **The rule-integrity audit — specific to this plan.** Two failure modes are unique to
      it and neither is visible in a normal review:

      ```bash
      # (a) a rule that cites nothing — R27/R32 violation, and the whole artifact's value
      for f in .tripll/rules/*.md; do grep -q '^origin:' "$f" || echo "NO ORIGIN: $f"; done
      # (b) an agent-reachable activation path — the R27 failure mode is silent and permanent
      git diff <base>...HEAD | grep -nE '^\+.*(state\s*=\s*.active.|auto_promote|--auto)'
      ```

      A rule activated without an operator is a **finding**, not a judgement call.
- [ ] **T.3** Run the branch review agents on `git diff <base>...HEAD`.
- [ ] **T.4** Fix every finding above `low`; **commit + push each fix pass**; re-run until clean;
      `make ci-resume` after the last pass.
- [ ] **T.5** **Eat the dog food.** Take one finding this review itself produced and run it through
      the loop end to end: `findings sync` → propose → `rules promote` → confirm it packs into the
      next brief. If the loop cannot absorb its own review's output, it does not work.
- [ ] **T.6** **Merge request — always human** (`auto_acceptable = false`). tripll parks; a person
      merges (D15).

---

## Success criteria (acceptance)

Issue numbers from W0.4 — **fill these in; an unrecorded issue is an unfiled one:**
prediction-driven routing `#53` · Jira implementation `#54` · rule conflict resolution `#55`.

- [ ] `tripll rules derive` on a **foreign** repo produces rules that every one cite a resolving
      `file:line`, and a repo with no tests yields an artifact that says so (R32)
- [ ] A dispatched brief carries the active rules plus **only** the context modules whose scope
      intersects the wave's targets, under `pack_budget_tokens`, with rules dropped last
- [ ] A resolved `Finding` proposes a `Rule` carrying its `finding://` origin, and **no
      agent-reachable path** activates it (R27)
- [ ] A rule promoted in run A packs into a brief in run B **after run A is archived** — the single
      criterion that distinguishes this plan from a reporting feature
- [ ] `.mergecraft/learnings.md` still exports rejected findings, behaviour unchanged
- [ ] The wave postmortem names **which side was wrong** — contract or agent — for every terminal wave
- [ ] `make rules-check` fails on a planted `import logging` and passes on a clean tree; absent
      `ast-grep` degrades to prose-only with exit 0
- [ ] A structural violation is reported through `harness/boundary.py`'s existing path
- [ ] Every wave carries a `PREDICTED` Metric at compile and a `REALIZED` Metric after the run;
      `tripll calibrate` reports a Brier score, or **"uncalibrated"** with too little history
- [ ] Predictor on vs off produces **byte-identical** routing, model, attempt budget and gates (R28)
- [ ] No ledger schema change anywhere in the diff
- [ ] `trackers/base.py` contains no provider-specific vocabulary; a fake tracker conforms without
      editing it; `tripll plan publish` run twice creates nothing the second time
- [ ] No MCP tool id appears in `src/` or in any agent prompt
- [ ] No new hard dependency: `ast-grep` and every tracker SDK are optional and degrade
- [ ] README says why before how; the pipeline diagram renders with no network fetch; every command
      the new docs name exists in `tripll --help`
- [ ] `make ci-resume` green twice, and a **green GitHub Actions run on the branch head**

## Traceability

### Idea → wave → finding

| Pack idea | Wave | Findings closed |
|-----------|------|-----------------|
| Bug-to-rule loop | W3 | RULE-01, RULE-02, RULE-03 |
| Derived rules + context modules | W2 | CTX-01, CTX-02, CTX-03 |
| Predicted confidence, calibrated | W5 | CAL-01, CAL-02, CAL-03 |
| Tracker round trip | W6 | PM-01, PM-02 |
| Executable rules | W4 | AST-01, AST-02 |
| Adoption artifacts | W7 | ADOPT-01, ADOPT-02 |

### Pack source → tripll decision

| Pack file | Taken as | Decision |
|-----------|----------|----------|
| `create-rules/SKILL.md:23–79` | origin-cited rules, descending generality, honest testing, gotchas list | R32 |
| `rca/SKILL.md:54` + `system-review/SKILL.md:148` | finding → rule + regression test | R26, R27 |
| `plan-feature/SKILL.md:460` | predicted first-pass confidence | R28 |
| `spec/SKILL.md:89–133` | idempotent round trip, ordered side effects | R30 |
| `ast-grep/SKILL.md` | executable rules | R29 |
| `README.md:80–92` | adoption narrative + diagrams | W7 |
| `merge-worktrees`, `execute`, `validate`, PIV | **rejected** — tripll's engine is ahead | *What this plan is not* |

---

## Baseline notes

- **HEAD when planned:** `a4fbd0d` on `refactor/mergecraft-replace-pullfrog`; `main` at `9a3f19d`,
  **26 commits behind**. W0 re-records both.
- **Source repo as read:** `coleam00/ai-native-starter-pack`, created 2026-05-21, 2 stars, 2 forks,
  no code, no tests, no package — a workshop handout, cloned and read in full on 2026-07-29.
- **Verified at W0 (2026-07-29, `a4fbd0d`):** `Hypothesis` / `Experiment` / `Metric` /
  `PREDICTED` / `REALIZED` at `ontology.yaml:141–172` and **no `src/tripll/**/*.py` writer**;
  `export_learnings` rejected filter at `learnings.py:30`; findings CLI at `cli/__init__.py:1442–1560`;
  no `ast-grep` in `src/`, `scripts/`, or `Makefile`; no `jira`/`confluence` in `src/tripll`;
  `attempts_to_green` / `first_attempt_pass_rate` only as `bench/__init__.py` METRIC_KEYS (no ledger aggregator).
- **Not a factor:** the starter pack contributes **no code** to this plan. Every line here is
  tripll-native; the pack contributed six ideas and four instructions worth copying verbatim.
