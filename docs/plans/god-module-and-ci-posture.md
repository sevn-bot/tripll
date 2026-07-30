# tripll god-module extraction and mergeCraft CI posture — wave plan

**Status:** W1 complete — W2 (wave-runner) next
**Date:** 2026-07-30
**Source:** GitHub issue sweep of [`sevn-bot/tripll`](https://github.com/sevn-bot/tripll) open queue
(2026-07-30). Two actionable issues: [#16](https://github.com/sevn-bot/tripll/issues/16)
(god-module extraction, R11) and [#59](https://github.com/sevn-bot/tripll/issues/59)
(mergeCraft `pull_request` posture + pin-parity gate).
**Target repo:** [`sevn-bot/tripll`](https://github.com/sevn-bot/tripll) — this checkout
**Audit baseline:** `2e4a8f2` on `wave/god-module-and-ci-posture` (based on `main`); sibling branch
`alexhawat-readme-and-oss-audit` at `ee4e247` (2 commits ahead of `main`, **not merged**) —
every anchor below line-checked at `2e4a8f2`
**Owner agents:** `wave-runner` (W0, W2–W8, Final, Thermos) · `test-creator` (W1 `role: test-author`)
**Contract copy:** `docs/plans/god-module-and-ci-posture.md` (tracked; W0.5 copies this file there
and records its sha256)

---

## Re-entry

> **The crash-test rule.** A fresh session in any tool must read this block and continue without
> re-explanation. Whoever finishes a wave updates it **in the same commit** as the wave's work.
> If this block is stale, the run is not resumable — treat that as a defect, not an inconvenience.

| Field | Value |
|-------|-------|
| **Current wave** | W2 (not started) |
| **Stage** | W1 complete; mergeCraft CI posture next (`wave-runner`) |
| **Next action** | Dispatch W2 — mergecraft trigger comment, topology-proof pin gate, runbook bump order |
| **Blocked on** | Nothing |
| **Last pushed sha** | `33aaad4` |
| **Last CI run id** | [30560683682](https://github.com/sevn-bot/tripll/actions/runs/30560683682) green on `33aaad4` |
| **Draft PR** | [#61](https://github.com/sevn-bot/tripll/pull/61) (draft) |
| **Status comment — #16** | [5118338652](https://github.com/sevn-bot/tripll/issues/16#issuecomment-5118338652) |
| **Status comment — #59** | [5133336437](https://github.com/sevn-bot/tripll/issues/59#issuecomment-5133336437) |
| **Parked waves** | **0 of 3** |
| **Integration target** | `main` (`2e4a8f2`); working branch `alexhawat-readme-and-oss-audit` at `ee4e247` is 2 commits **ahead** of `main`, **not merged** |
| **Plan sha256** | `05ce25bf3f2bba61a92185c5b17bb675ebb3cfd3c029a67b83ccb4674222e233` |
| **Contract sha256 (W0 pin)** | `7a87e1fea472bc82f2a51152d69f1052ee2672bbaf7e9d54528272ea476bd52c` (initial W0.5 pin); current `05ce25bf…` after W0.10 re-entry |

---

## What this plan is, and what it is not

Two issues, one plan, because they share nothing except the branch — and that is deliberate. #59 is
four hours of CI-posture work that has been sitting behind a decision nobody wrote down. #16 is the
program that #47 and #51 already started and that nothing is currently driving to completion. Both
are cheap to lose track of and neither is going to be picked up by a wave plan aimed at anything
else.

**#16 is a refactor with no behaviour change.** That is the whole discipline here. Every wave from
W3 onward moves code and changes nothing a caller can observe. The mechanism is the one PR #47 and
PR #51 already proved in this repo:

```
god_module.py  →  god_module.py (façade: imports + __all__)  +  god_module_<seam>.py (the code)
                            ↑
              characterization test asserts `facade.name is submodule.name`
```

**Two extractions have already landed. This plan finishes the other five.**

| PR | Landed | Seam | Effect |
|----|--------|------|--------|
| [#47](https://github.com/sevn-bot/tripll/pull/47) | 2026-07-29 | `engine_scheduling.py` (177 lines) | `engine.py` 3694 → 3492 |
| [#51](https://github.com/sevn-bot/tripll/pull/51) | 2026-07-29 | `cli/_run.py` (490) + `cli/_shared.py` (349) | `cli.py` → `cli/` package, −460 lines |

**Explicitly rejected as approaches** (recorded so nobody re-proposes them):

- **Moving call sites instead of keeping a façade.** `ledger.py` alone has ~30 import sites across
  `engine`, `inject`, `api/app`, `api/ui/router`, `cli`, `loops/*`, `report`, `calibrate`,
  `pipeline`, `rules/postmortem` and `tests/`. A refactor that also rewrites every importer is two
  changes in one diff, and the second one is the one that breaks.
- **Splitting `Engine._execute_node_body` (642 lines) first** because it is the biggest single
  target. It reads and writes 15+ `self` fields and holds `self._ledger_lock` across ledger
  sequences. It goes **last**, after every leaf seam is gone (W5), and it moves as one unit rather
  than being carved into phases.
- **Rewriting the FastAPI routes as a fresh router tree.** All 28 JSON handlers are nested inside
  `create_app` (`api/app.py:330-1460`) and close over the inner `app`. W7 converts them to
  `APIRouter` + `request.app.state`; it does not redesign the API.
- **Moving to `pull_request_target`** for mergeCraft (#59 option (b)). It is only worth its secret
  exposure once the review is a *required* check, and it is not. See R35.
- **Hand-rolling a `wait-for-ci` job.** #59 notes a hardened reference workflow is being proposed
  upstream in `alexhawat/mergeCraft`. A second local copy is the thing to avoid. See R37.

**Not in scope, and why** — two files in this repo are over 1,000 lines and are **not** named in
#16, so they are not in this plan: `src/tripll/inject.py` (1,284) and `src/tripll/skw/render.py`
(1,161). Final's module-size gate lands with both on an explicit, commented allowlist so the gate
can be true today rather than after a scope expansion nobody asked for.

---

## The gap — what is oversized and what is unenforced

`find src/tripll -name '*.py' | xargs wc -l | sort -rn` at `2e4a8f2`:

| Finding | Evidence | Wave |
|---------|----------|------|
| **GOD-01** — `engine.py` is **3,603 lines**. The `Engine` class alone is `engine.py:713-3589` (**2,877 lines**); `_execute_node_body` is `engine.py:2739-3381` (**643 lines**) with a nested `_on_stream_event` closure at `2914-2954`. Nine cohesive seams are identifiable and only one has been cut | `engine.py`; precedent `engine_scheduling.py` (177) | **W4, W5** |
| **GOD-02** — `cli/__init__.py` is **2,095 lines** carrying **49 user-facing commands** across **12 sub-app groups**, of which only `run` / `run-inject` / `run-reconcile-graph` have been extracted | `cli/__init__.py`; precedent `cli/_run.py:481-486` | **W6** |
| **GOD-03** — `api/app.py` is **1,626 lines**: **28 JSON routes** (`391-1458`), 15 Pydantic models (`130-322`) and 9 module helpers (`1468-1626`), with **every route handler nested inside `create_app`** so none of them is independently importable or testable | `api/app.py:330-1460` | **W7** |
| **GOD-04** — `api/ui/router.py` is **1,470 lines** with **22 dashboard routes** (`162-832`), and it imports three private helpers back out of `api.app` (`_read_config`, `_slug_profile_id`, `_tripll_argv`) at `api/ui/router.py:79` — so W7 and W8 are ordered, not parallel | `api/ui/router.py` | **W8** |
| **GOD-05** — `ledger.py` is **1,394 lines** and has **no `__all__`**. Its public surface is a prose `Exports:` list in the docstring (`ledger.py:17-40`) that is already **wrong**: `RunRow`, `WaveRow`, `AttemptRow`, `reset_wave_attempts` and `void_infra_attempt_count` are imported by real callers and appear nowhere in it | `ledger.py:17-40`; importers in `api/_l1_panels.py`, `api/_artefacts.py`, `rules/postmortem.py`, `cli/_shared.py:317` | **W3** |
| **GOD-06** — **nothing enforces the 1k rule.** `oversized_file` exists only as a *review problem type* — a thing a reviewer may notice, not a thing a gate catches. So every line this plan removes can come back silently | `docs/skw/problem-types.md:11`; `grep -rn 'oversized' Makefile scripts/` → empty | **Final** |
| **CI-01** — `.github/workflows/mergecraft.yml:9-11` triggers on `pull_request`, which **GitHub does not run when `refs/pull/N/merge` cannot be built** — i.e. on any merge-conflicted PR. Harmless while the review is advisory; the moment it becomes a required check, a conflicted PR carries a permanently missing check and does not re-fire after the conflict is fixed, because the `synchronize` that would have re-fired it was the one that got skipped | `mergecraft.yml:9-11` | **W2** |
| **CI-02** — `scripts/check_mergecraft_ref_parity.py` compares the **working-tree** workflow pin against `Makefile`'s `MERGECRAFT_REF`. Correct today only because `main` is both trunk and default branch. It silently stops being correct if the workflow ever moves to `pull_request_target` (definitions resolve from the default branch under GitHub's Nov-2025 policy, effective 2025-12-08) or if trunk stops being the default branch | `check_mergecraft_ref_parity.py:18-26` (`REPO_ROOT`-relative paths), `:36-46` (`path.read_text`); `Makefile:14` | **W2** |
| **CI-03** — `branches: [main]` means only PRs targeting `main` are reviewed. Long-lived `wave/*` branches and stacked `feat/*` PRs that target each other get **no review at all**, and nothing in the workflow says whether that is intentional | `mergecraft.yml:10` | **W2** |
| **CI-04** — the review fires immediately on `synchronize`, so mergeCraft has **no lint / typecheck / test signal** for the head commit and no `check_suite_id`, which it cannot discover on its own. It therefore speculates about mechanical failures the gates would have caught | `mergecraft.yml:11`, `:51-64` | **W2** (decision only — R37) |

**Already present — do not rebuild.**

- `engine_scheduling.py` + `tests/test_engine_scheduling.py:34-41` — the façade pattern and its
  identity assertion. Every extraction in W3–W8 copies this, exactly.
- `cli/_run.py:481-486` (`register_run_commands`) + `cli/_shared.py` — the CLI registrar pattern.
  W6 adds `register_*_commands` functions; it does not invent a second registration mechanism.
- `api/_runs.py`, `_inject.py`, `_auth.py`, `_csrf.py`, `_artefacts.py`, `_worktree_status.py`,
  `_l1_panels.py`, `_orchestrator_ui.py`, `_pr_panel.py` — nine modules already carved out of the
  API. W7 and W8 extract what is **left**, and re-extract none of these.
- `Makefile:307-308` `mergecraft-ref-check` and `scripts/ci_lib.py:60-67`'s `PATH_RULES` entry —
  the gate and its path mapping both exist. W2 hardens the script behind them; it adds no new gate.
- `Makefile:346` `CI_STEPS` and `scripts/ci_lib.py:44` `PATH_RULES` — Final's module-size gate is a
  new entry in both, not a new CI mechanism.

---

## The extraction contract — what "no behaviour change" means here

Three properties, in priority order. A wave that trades any of them for a smaller diff has not
landed.

**1. The import surface is byte-stable.** After every wave, every name that resolved from
`tripll.engine`, `tripll.ledger`, `tripll.cli` or `tripll.api.app` before the wave still resolves
from it, **to the same object**:

```python
assert tripll.engine.ready_nodes is tripll.engine_scheduling.ready_nodes
```

`is`, not `==`. Identity is what proves a re-export rather than a re-implementation, and it is the
assertion `tests/test_engine_scheduling.py:34-41` already makes.

**2. Private names count.** The façade must re-export what `tests/` reaches for, not just what
`__all__` advertises. These are the ones a naive extraction breaks, all line-checked at `2e4a8f2`:

| Private name | Reached from |
|--------------|--------------|
| `engine._resolve_grep_brief` | `tests/test_brief_graph_pack.py:17` |
| `engine._MAX_NO_PROGRESS_DISPATCHES` | `tests/test_w2_controls.py:16` |
| `engine.__doc__` (the `Exports:` inventory) | `tests/test_provider_pools.py:35-39` |
| `cli._run_integration` | `tests/test_delivery_live_fixture.py:99` |
| `cli._orchestrator_watch_lines` | `tests/test_orchestrator_mode_smoke.py:116` |
| `cli._rewrite_run_inject_argv` | `tests/test_inject.py`, `tests/test_reconcile.py` |
| `api.app._resolve_runs_root` | `tests/test_api.py:844`, `:864` |
| `api.app._read_config`, `_slug_profile_id`, `_tripll_argv` | **production code**: `api/ui/router.py:79` |

`tests/test_provider_pools.py:35-39` is the trap worth naming: it asserts on `engine.__doc__`. The
module docstring's `Exports:` block (`engine.py:44-59`) is **part of the tested surface**, so each
wave updates it in place rather than letting it rot.

**3. Lazy imports stay lazy.** `ledger.py` reaches `graphstore.task_sync.TaskGraphWriter` from
inside `_maybe_sync_wave_transition` (`ledger.py:621`) and `insert_attempt` (`ledger.py:707`)
specifically to avoid an import cycle. Same in `engine.py` for `inject.reconcile_run_graph` and
`loops.l1_outer.compile_l1_outer_graph`. **Hoisting a lazy import to module scope while moving it is
the single most likely way to break this plan**, and it fails as an `ImportError` at CLI startup —
after the diff looks clean.

### Direction of dependency, which must not gain a cycle

```
ledger_schema  →  ledger_store / ledger_query  →  ledger (façade)  →  engine_*  →  engine (façade)
                                                                            ↓
                                                     cli/*  ·  api/routes/*  ·  api/ui/router
```

No `ledger_*` submodule may import `engine`. No `engine_*` submodule may import `cli` or `api`.
W3's and W4's acceptance blocks grep for exactly this.

---

## The CI posture — what #59 actually asks for

#59 is explicit that it is a "write down the decision" issue, and it recommends option (a). This
plan takes that recommendation, and the reason it is worth a wave anyway is CI-02: the pin-parity
gate's blind spot is cheap to close now and expensive to discover later.

| # | #59 acceptance box | This plan |
|---|--------------------|-----------|
| 1 | Decide (a) advisory-only or (b) `pull_request_target`, record it in a workflow comment | **(a)** — R35, ADR 018, comment at `mergecraft.yml:8` |
| 2 | If (b): same-repo secret guard + PR-number `concurrency` | **N/A** under (a). ADR 018 records the exact change (a) would need if (b) is ever taken, including that `github.ref` resolves to the default branch under `pull_request_target` and would collapse `mergecraft.yml:27-29`'s `concurrency` group across every open PR |
| 3 | Parity gate reads the default-branch ref, skips offline, fails under `CI` | **W2.3** — R36 |
| 4 | Base-branch coverage confirmed or widened | **W2.4** — decide and comment |
| 5 | Decide whether to adopt the upstream hardened workflow once available | **R37** — adopt when it lands, do not hand-roll |

**The bump-order consequence, recorded because it is a footgun and not a design note.** Once the
gate reads the default-branch ref, `MERGECRAFT_REF` in the `Makefile` can no longer be bumped in the
same commit as the workflow pin and pass. Order becomes: **merge the workflow bump to the default
branch first, then bump `MERGECRAFT_REF`.** W2.6 puts this in the operator runbook, because the
person who hits it will be mid-bump and confused.

---

## Reporting to the issues — the status surface is GitHub, not this file

**The problem this solves.** This plan runs for ten waves on one branch behind one PR that a human
merges at the end (D15). For most of that time #16 and #59 look untouched to anyone reading GitHub,
while the actual state lives in a gitignored file in one operator's checkout. #16's own history is
the argument: the maintainer hand-wrote partial-progress comments after #47 and after #51, because
a tracker that goes silent for a multi-PR program is a tracker nobody trusts.

**The mechanism (R40).** Each issue gets **one rolling status comment**, created at W0 and **edited
in place** at every wave close-out:

```bash
gh issue comment 16 --repo sevn-bot/tripll --edit-last --create-if-none --body-file status-16.md
```

`--edit-last --create-if-none` is idempotent: the first call creates, every later call rewrites the
same comment. So the issue always shows current state and never accumulates ten near-identical
updates. A **new** comment is posted exactly twice per issue — once when the PR opens, once as the
final evidence comment at Thermos — because those two are events, not state.

### The status comment shape

Follows the format the maintainer already used on #16 for #47 and #51, so the issue reads
consistently:

```markdown
## Status — wave plan `god-module-and-ci-posture` (in progress, not merged)

| | |
| --- | --- |
| **Branch** | `wave/god-module-and-ci-posture` |
| **PR** | #NN (draft) |
| **Base** | `main` @ `2e4a8f2` |
| **Last wave** | W4 — engine.py leaf seams |
| **Last sha** | `abc1234` |
| **CI** | [run 30xxxxxxx](https://github.com/sevn-bot/tripll/actions/runs/30xxxxxxx) green |

### Delivered so far
- **W3** `ledger.py` 1394 → 118 lines behind a façade; `ledger_{schema,store,query}.py`, zero caller edits (`sha`)
- **W4** `engine.py` 3603 → 2418; worktrees, human gates, verify, brief extracted (`sha`)

### Remaining before close
- W5 `engine.py` core seams · W6 `cli/` · W7 `api/app.py` · W8 `api/ui/router.py` · Final module-size gate

Nothing is merged. This issue closes only after a human merges the PR (D15).
```

**Two rules that keep it honest.** Every "Delivered" line carries **a real number and a real sha** —
"extracted the worktree seam" is a claim, "3603 → 2418" is evidence. And the comment states
**"not merged"** until it is, because a status update that reads like completion on an unmerged
branch is the same failure as closing the issue early.

**Which wave reports to which issue:**

| Issue | Reports at | Content |
|-------|-----------|---------|
| [#59](https://github.com/sevn-bot/tripll/issues/59) | W0 (kickoff), **W2** (the only wave that touches it), Final, Thermos | the recorded decision, the ADR link, the four acceptance boxes ticked |
| [#16](https://github.com/sevn-bot/tripll/issues/16) | W0 (kickoff), **W1**, **W3–W8** (one edit each), Final, Thermos | per-module before/after line counts and the wave sha |

W1 is on that list deliberately. #16's body gives "its own characterization-test prerequisite" as the
*reason the split was deferred*, so "the prerequisite you named is now met, green at baseline" is the
single most informative update the issue can receive — and it is the one a wave plan would normally
skip, because W1 moves no source.

---

## Machine block (`waveorch_format = 3`)

> **Why this exists.** Prose "Acceptance:" lines are self-reported. `[waves.outcome]` contracts are
> graded (D16 — *graders decide completion; agents do not self-report done*).
>
> **W0.6 must compile this block at HEAD** via `tripll validate-plan` and
> `plan.shape_checks.compile_plan`: **10 waves** (Thermos is a prose gate, not a wave), serial
> chain, no wave targeting more than 5 modules, one writer per file per antichain.
>
> **Verified 2026-07-30:** this block parses as TOML — 10 waves, every `targets` list ≤ 5, every
> `depends_on` naming a wave that exists earlier in the chain. W0.6 re-runs the real compiler at
> HEAD; if it does not compile, **fix this plan**, not the compiler.

```toml
waveorch_format = 3
title = "tripll god-module extraction and mergeCraft CI posture"
slug = "god-module-and-ci-posture"
base = "main"
branch = "wave/god-module-and-ci-posture"
target_repo = "sevn-bot/tripll"

[pipeline]
max_turns = 3
deadline = "72h"
budget_usd = 55.0
human_gates = "prompt"
max_parked_waves = 3
max_parallel = 10
default_provider = "cursor_local"
extras = ["graph", "kg"]
creates = [
  "src/tripll/ledger_schema.py",
  "src/tripll/ledger_store.py",
  "src/tripll/ledger_query.py",
  "src/tripll/engine_worktrees.py",
  "src/tripll/engine_human_gates.py",
  "src/tripll/engine_verify.py",
  "src/tripll/engine_brief.py",
  "src/tripll/engine_exits.py",
  "src/tripll/engine_orchestrator.py",
  "src/tripll/engine_batch_drive.py",
  "src/tripll/engine_node_dispatch.py",
  "src/tripll/cli/_onboard.py",
  "src/tripll/cli/_status.py",
  "src/tripll/cli/_run_ops.py",
  "src/tripll/cli/_wave.py",
  "src/tripll/cli/_plan.py",
  "src/tripll/cli/_graph.py",
  "src/tripll/cli/_findings.py",
  "src/tripll/cli/_rules.py",
  "src/tripll/cli/_review.py",
  "src/tripll/cli/_pr.py",
  "src/tripll/cli/_docs.py",
  "src/tripll/api/models.py",
  "src/tripll/api/deps.py",
  "src/tripll/api/routes/__init__.py",
  "src/tripll/api/routes/agents.py",
  "src/tripll/api/routes/runs.py",
  "src/tripll/api/routes/waves.py",
  "src/tripll/api/routes/events.py",
  "src/tripll/api/routes/config.py",
  "src/tripll/api/ui/_routes_runs.py",
  "src/tripll/api/ui/_routes_agents.py",
  "src/tripll/api/ui/_routes_fragments.py",
  "scripts/check_module_size.py",
  "tests/test_module_facades.py",
  "tests/test_module_size.py",
  "tests/test_mergecraft_ref_parity.py",
  "docs/decisions/013-god-module-extraction.md",
  "docs/decisions/018-mergecraft-ci-trigger-posture.md",
  "docs/test-plans/god-module-and-ci-posture.md",
  "docs/plans/god-module-and-ci-posture.md",
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
title = "Baseline, anchor re-grep, ADRs 013 + 018, contract pinning"
role = "impl"
effort = "S"
provider = "cursor_local"
model = "claude-opus-5"
targets = ["docs/decisions/013-god-module-extraction.md", "docs/decisions/018-mergecraft-ci-trigger-posture.md", "docs/plans/god-module-and-ci-posture.md"]
verify = ["make lint"]

  [waves.outcome]
  required = [
    "ADR 013 and ADR 018 exist and each states its rejected alternative",
    "every line anchor in the gap table and the extraction contract re-checked at HEAD and corrected in place",
    "the private-name table is verified by grep: every listed importer still imports that name",
    "docs/plans/god-module-and-ci-posture.md exists and its sha256 is recorded in Re-entry",
    "tripll validate-plan on this plan exits 0",
    "a draft PR exists for the branch and its number is recorded in Re-entry",
    "issues 16 and 59 each carry a kickoff status comment naming the branch, the draft PR and the wave map",
    "both status comment ids are recorded in Re-entry so later waves edit rather than duplicate",
  ]
  forbidden = [
    "any change under src/",
    "any change under .github/",
    "reusing ADR number 013 for anything else",
    "closing issue 16 or issue 59",
    "a status comment that omits the branch or the PR",
  ]
  evidence = ["command_output", "final_diff"]

[[waves]]
id = "W1"
title = "Characterization suite — lock the surface before moving anything"
role = "test-author"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["tests", "docs/test-plans/god-module-and-ci-posture.md"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W0"
  reason = "gate"
  detail = "contracts locked before the suite that grades them is authored"

  [waves.outcome]
  required = [
    "tests/test_module_facades.py passes GREEN at baseline, before any extraction",
    "every name in the private-name table has an assertion that it resolves from its facade",
    "tests/test_module_size.py xfails at baseline with per-file line counts in the failure message",
    "tests/test_mergecraft_ref_parity.py covers the offline-skip and CI-hard-fail paths",
    "docs/test-plans/god-module-and-ci-posture.md maps finding to test to wave to tier",
    "issue 16's status comment is edited in place to record that the characterization prerequisite is met and green at baseline",
  ]
  forbidden = [
    "strict=True on any cross-wave xfail",
    "any change under src/",
    "a characterization test that xfails at baseline (it must pass before and after)",
  ]
  evidence = ["test_output"]

[[waves]]
id = "W2"
title = "mergeCraft CI posture and a topology-proof pin-parity gate"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = [".github/workflows/mergecraft.yml", "scripts/check_mergecraft_ref_parity.py", "Makefile", "scripts/ci_lib.py", "docs/runbooks/operator-runbook.md"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W1"
  reason = "gate"
  detail = "the parity-gate tests define acceptance"

  [waves.outcome]
  required = [
    "the workflow carries a comment stating the trigger decision and that mergeCraft review must stay non-required",
    "check_mergecraft_ref_parity.py reads the workflow pin from the default-branch ref via git show, not the working tree",
    "the ref is overridable by env var and defaults to origin/main",
    "a missing ref triggers one shallow fetch attempt, then skips with a warning and exit 0 when CI is unset",
    "a missing or unreachable ref exits non-zero when CI is set",
    "base-branch coverage is decided and the decision is a comment in the workflow",
    "the operator runbook states the new bump order: default branch first, then MERGECRAFT_REF",
    "issue 59's status comment is edited in place to record the decision, the ADR link and each acceptance box, with the wave sha",
  ]
  forbidden = [
    "switching the trigger to pull_request_target",
    "a hand-rolled wait-for-ci job",
    "a parity gate that exits 0 on an unreachable ref while CI is set",
    "any change under src/tripll/",
    "closing issue 59 before a human merges the PR",
    "a second status comment on issue 59 alongside the rolling one",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W3"
title = "ledger.py to a facade over schema, store and query"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/ledger.py", "src/tripll/ledger_schema.py", "src/tripll/ledger_store.py", "src/tripll/ledger_query.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W2"
  reason = "gate"
  detail = "serialized by choice: per-wave commit, push and green CI is this plan's acceptance mechanism"

  [waves.outcome]
  required = [
    "ledger.py is under 200 lines and is imports plus __all__ only",
    "ledger.py gains an __all__ that matches the full set of externally imported names, including RunRow, WaveRow, AttemptRow, reset_wave_attempts and void_infra_attempt_count",
    "every ledger submodule is under 1000 lines",
    "the TaskGraphWriter imports in insert_attempt and _maybe_sync_wave_transition are still function-local",
    "no ledger submodule imports tripll.engine",
    "tests/test_module_facades.py ledger identity assertions pass",
    "make test is green with zero changes to any ledger caller",
    "issue 16's status comment is edited in place with this wave's before and after line counts and the wave sha",
  ]
  forbidden = [
    "editing any caller of tripll.ledger",
    "hoisting a lazy graphstore import to module scope",
    "a schema, DDL or migration behaviour change",
    "dropping a name from the documented Exports inventory",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W4"
title = "engine.py leaf seams: worktrees, human gates, verify, brief"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/engine.py", "src/tripll/engine_worktrees.py", "src/tripll/engine_human_gates.py", "src/tripll/engine_verify.py", "src/tripll/engine_brief.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W3"
  reason = "artifact"
  detail = "engine imports 12 names from ledger at module scope; the ledger facade must be proven stable before engine moves too"

  [waves.outcome]
  required = [
    "the five worktree and verifier types move out of engine.py and remain importable from it by identity",
    "complete_human_gate_waves and _resolve_grep_brief move and remain importable from engine.py",
    "the three verify methods and the brief helpers move; the Engine class delegates",
    "engine.py Exports inventory in the module docstring is updated in the same commit",
    "engine.py is under 2600 lines",
    "no engine submodule imports tripll.cli or tripll.api",
    "make test green with zero changes to any engine caller",
    "issue 16's status comment is edited in place with this wave's before and after line counts and the wave sha",
  ]
  forbidden = [
    "editing any caller of tripll.engine",
    "changing Engine's public method signatures",
    "touching _execute_node_body",
    "a second WorktreeManager protocol",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W5"
title = "engine.py core seams: exits, orchestrator, batch drive, node dispatch"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/engine.py", "src/tripll/engine_exits.py", "src/tripll/engine_orchestrator.py", "src/tripll/engine_batch_drive.py", "src/tripll/engine_node_dispatch.py"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W4"
  reason = "artifact"
  detail = "same file: engine.py is a serialized writer, and the leaf seams must be gone before the coupled ones move"

  [waves.outcome]
  required = [
    "engine.py is under 1000 lines",
    "every engine submodule is under 1000 lines",
    "_execute_node_body moved as one unit, not carved into phases",
    "the _on_stream_event closure still captures the same ledger connection and lock",
    "the reconcile_run_graph and compile_l1_outer_graph imports are still function-local",
    "loops.l1_outer, loops.dispatch_bridge and loops.outer_post_wave still import Engine from tripll.engine unchanged",
    "make test green with zero changes to any engine caller",
    "issue 16's status comment is edited in place with this wave's before and after line counts and the wave sha",
  ]
  forbidden = [
    "editing any caller of tripll.engine",
    "splitting _execute_node_body into phase functions",
    "hoisting a lazy import to module scope",
    "moving self-field ownership out of the Engine class",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W6"
title = "cli/__init__.py to registrars over per-group command modules"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/cli"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W5"
  reason = "artifact"
  detail = "cli imports Engine and RunResult from tripll.engine; the engine facade must be final first"

  [waves.outcome]
  required = [
    "cli/__init__.py is under 300 lines and contains the root app, the root callback, register_* calls and main",
    "every cli submodule is under 1000 lines",
    "tripll --help lists the same commands and groups in the same order as at baseline",
    "every one of the 49 commands still resolves and still exposes the same options",
    "rewrite_run_inject_argv still runs in main before app is invoked",
    "the plan callback keeps allow_interspersed_args",
    "run-inject and run-reconcile-graph stay registered and hidden",
    "_run_integration and _orchestrator_watch_lines still resolve from tripll.cli",
    "issue 16's status comment is edited in place with this wave's before and after line counts and the wave sha",
  ]
  forbidden = [
    "a second registration mechanism alongside register_*_commands",
    "changing any command name, group name or option name",
    "duplicating any skw command into cli/",
    "moving argv preprocessing into a Typer callback",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W7"
title = "api/app.py to a factory over routers, models and deps"
role = "impl"
effort = "L"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/api/app.py", "src/tripll/api/models.py", "src/tripll/api/deps.py", "src/tripll/api/routes"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W6"
  reason = "artifact"
  detail = "cli and api both construct Engines; serialize the two facade rewrites"

  [waves.outcome]
  required = [
    "api/app.py is under 300 lines: imports, create_app, middleware, mounts and include_router calls",
    "every api route module is under 1000 lines",
    "all 28 JSON routes keep their exact method, path and response shape",
    "route handlers read runs_root from request.app.state, not from a create_app closure",
    "middleware, static mount, UI router include and exception handler order are unchanged",
    "require_auth still guards every /api/ route and the SSE token query param still works",
    "_resolve_runs_root, _read_config, _slug_profile_id and _tripll_argv still resolve from tripll.api.app",
    "api/ui/router.py is not edited in this wave",
    "issue 16's status comment is edited in place with this wave's before and after line counts and the wave sha",
  ]
  forbidden = [
    "a module-level app singleton",
    "changing any route path, method or status code",
    "changing the launch_run placeholder run_id contract",
    "editing src/tripll/api/ui/",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "W8"
title = "api/ui/router.py split into dashboard route modules"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "auto"
fallback = ["claude_code"]
targets = ["src/tripll/api/ui"]
verify = ["make lint", "make typecheck", "make test"]

  [[waves.depends_on]]
  wave = "W7"
  reason = "artifact"
  detail = "ui/router.py imports _read_config, _slug_profile_id and _tripll_argv from api.app; those must have settled first"

  [waves.outcome]
  required = [
    "api/ui/router.py is under 1000 lines",
    "every new api/ui module is under 1000 lines",
    "make_ui_router still returns one APIRouter with include_in_schema False",
    "all 22 dashboard routes keep their exact method and path",
    "every route still reads request.app.state.runs_root",
    "the htmx fragment routes still return the same template names",
    "issue 16's status comment is edited in place with this wave's before and after line counts and the wave sha",
  ]
  forbidden = [
    "a second APIRouter returned to create_app",
    "changing any dashboard URL",
    "moving templates or static assets",
    "editing src/tripll/api/app.py",
  ]
  evidence = ["test_output", "command_output", "final_diff"]

[[waves]]
id = "Final"
title = "Module-size gate, xfail sweep, full gate, change summary"
role = "impl"
effort = "M"
provider = "cursor_local"
model = "claude-opus-5"
targets = ["scripts/check_module_size.py", "scripts/ci_lib.py", "Makefile", "tests", "CHANGELOG.md"]
verify = ["make ci-resume"]

  [[waves.depends_on]]
  wave = "W8"
  reason = "gate"
  detail = "the gate is only landable once the tree it guards is already under the limit"

  [waves.outcome]
  required = [
    "make module-size-check exits non-zero when any non-allowlisted src/tripll module exceeds 1000 lines",
    "the allowlist contains exactly inject.py and skw/render.py, each with a comment naming why",
    "module-size-check is wired into CI_STEPS and into ci_lib PATH_RULES",
    "tests/test_module_size.py passes with the xfail removed",
    "make ci-resume green twice consecutively",
    "a green GitHub Actions run on the branch head",
    "zero stale xfails referencing a wave that is done",
    "the PR is marked ready for review and its body links this plan and both issues with closing keywords",
    "both status comments are edited to final state: every wave sha, every before and after line count, the CI run id",
    "both status comments still say the work is not merged",
  ]
  forbidden = [
    "a gate that always exits 0",
    "adding a file to the allowlist to make the gate pass",
    "a weakened acceptance criterion anywhere in the diff",
    "closing issue 16 or issue 59",
    "merging the PR",
  ]
  evidence = ["test_output", "command_output", "ci_run_id"]
```

---

## Worktree & branch

```bash
cd /Users/alex/Documents/code/sevn.bot/tripll
git worktree add ../tripll-god-modules wave/god-module-and-ci-posture main
cd ../tripll-god-modules
make setup
```

- **Branch:** `wave/god-module-and-ci-posture`. **Worktree root:** `../tripll-god-modules`.
- **Base — the rule, decided now.** Base on **`main`** (`2e4a8f2`), which already contains the
  ai-layer compounding work merged via PR #58. The current working branch
  `alexhawat-readme-and-oss-audit` (`ee4e247`) is 2 commits **ahead** and 0 behind; those two
  commits are README and OSS-governance docs and are **not** a prerequisite for anything here. W0
  re-records both shas. **If that branch merges to `main` before dispatch, rebase and re-record.**
- **Git safety:** never `git clean -x` / `-X` (`CLAUDE.md`, `.cursor/rules/no-destructive-git-clean.mdc`).

## Docs touched

- **new** `docs/decisions/013-god-module-extraction.md` — R33, R34. **013 has been free since the
  L1 plan's onboarding ADR never landed**; this plan claims it rather than opening a gap at 013 and
  starting at 019.
- **new** `docs/decisions/018-mergecraft-ci-trigger-posture.md` — R35, R36, R37
- **new** `docs/test-plans/god-module-and-ci-posture.md`, `docs/plans/god-module-and-ci-posture.md`
- `docs/runbooks/operator-runbook.md` — the mergeCraft bump order (W2.6)
- `docs/design-note.md` — the module map in §0.1 names `engine.py` and `ledger.py`; update the
  paths it lists
- `CLAUDE.md` — `make module-size-check` in the command table (Final)
- `CHANGELOG.md` — `## [Unreleased]` bullet per wave that touches `src/`

## Goal

Close [#59](https://github.com/sevn-bot/tripll/issues/59) and
[#16](https://github.com/sevn-bot/tripll/issues/16). End state: the mergeCraft trigger posture is a
written decision rather than a default nobody chose, and the pin-parity gate is correct under both
branch topologies; every module named in #16 is under 1,000 lines; every caller of every one of them
is **unchanged**; and `make module-size-check` fails the build the next time one of them grows back.

## Files in scope

| Area | Paths |
|------|-------|
| CI posture (W2) | `.github/workflows/mergecraft.yml`, `scripts/check_mergecraft_ref_parity.py`, `Makefile`, `scripts/ci_lib.py` |
| Ledger (W3) | `src/tripll/ledger.py` → **new** `ledger_{schema,store,query}.py` |
| Engine leaves (W4) | `src/tripll/engine.py` → **new** `engine_{worktrees,human_gates,verify,brief}.py` |
| Engine core (W5) | `src/tripll/engine.py` → **new** `engine_{exits,orchestrator,batch_drive,node_dispatch}.py` |
| CLI (W6) | `src/tripll/cli/__init__.py` → **new** `cli/_{onboard,status,run_ops,wave,plan,graph,findings,rules,review,pr,docs}.py` |
| API (W7) | `src/tripll/api/app.py` → **new** `api/{models,deps}.py`, `api/routes/{agents,runs,waves,events,config}.py` |
| Dashboard (W8) | `src/tripll/api/ui/router.py` → **new** `api/ui/_routes_*.py` |
| Gate (Final) | **new** `scripts/check_module_size.py`, `Makefile`, `scripts/ci_lib.py` |
| Tests (W1) | **new** `tests/test_module_facades.py`, `test_module_size.py`, `test_mergecraft_ref_parity.py` |
| Issue reporting (W0–Thermos) | **untracked**, staged under `ignorelocal/github-issues/`: `status-{16,59}.md` (rewritten each wave), `final-{16,59}.md` (Thermos). Gitignored by design — the comment on GitHub is the artifact, the file is just its body |

## Global conventions

1. **Worktree only** on `wave/god-module-and-ci-posture`. Never `git clean -x` / `-X`.
2. **Characterization-first.** W1 authors the suite that locks the surface, and — unlike a RED
   suite — **`tests/test_module_facades.py` must be GREEN at baseline**. A characterization test
   that fails before the refactor is not characterizing anything. Only
   `tests/test_module_size.py` xfails, and only until the wave that shrinks the file it names.
3. **Impl waves are forbidden from editing `tests/`** except via `test-creator` re-dispatch.
   Cross-wave reds use `@pytest.mark.xfail(reason="green after W<N>: …", strict=False)`.
4. **Make/uv only.** Per wave: `make lint`, `make typecheck`, `make test`; mid-wave scoped gate
   `make ci-affected`. Full gate at Final via `make ci-resume`. Never raw `pytest` / `ruff` / `mypy`.
5. **Every wave ends with commit + push.** Conventional commit; CHANGELOG bullet in the **same**
   commit when `src/` changes; **Re-entry block updated in the same commit**.
6. **Conventional Commits** — validate with `python scripts/check_conventional_commit.py --message …`.
   No `--no-verify`. Refactor waves use `refactor(<area>): …`, not `feat`.
7. **`git mv`-shaped diffs where possible.** A moved function should appear as a deletion and an
   identical insertion. If a moved body also changed, **say so in the commit body and name the
   line** — an unannounced edit inside a move is the failure mode a reviewer cannot see.
8. **New modules carry the house docstring**: module docstring with an `Exports:` inventory, full
   docstrings on public callables (`Args:` / `Returns:` / `Examples:`), `from __future__ import
   annotations`, `|` unions, lowercase generics, line length 100, **loguru only**.
9. **Path convention:** repo-root-relative.
10. **Re-grep before editing.** Every anchor here is a `2e4a8f2` line number and *will* drift —
    W3's extraction moves the very lines W4 and W5 cite.
11. **Observable acceptance.** Every `**Acceptance:**` block is a runnable command with an expected
    value.
12. **PARKED is a legal outcome; a weakened criterion is not.** In particular: a file that will not
    come under 1,000 lines honestly gets parked with an issue, not an allowlist entry.
13. **Every wave reports to its issue** (R40). Wave close-out edits the rolling status comment on
    #16 (W1, W3–W8) or #59 (W2) **in place** via `gh issue comment --edit-last --create-if-none`, with
    the wave's sha, its CI run and a real before/after number. **Never close an issue** — that
    happens after the human merge, at Thermos T.6. A parked wave reports the park and its reason to
    the issue too; silence is how a tracker goes stale.

### Test tiers

| Tier | Covers | Runs | Blocks? |
|------|--------|------|---------|
| **1 — offline** | façade identity, `__all__` completeness, module line counts, Typer command inventory, parity-gate logic against a temp git repo | every `make test` | yes |
| **2 — live, gated** | parity gate against a real `origin/main` fetch — behind `RUN_LIVE=1` | wave close-out + Final | yes when run |
| **3 — e2e smoke** | `tripll --help` inventory; `create_app()` route-table inventory; one real dashboard request | every `make test` | yes |
| **4 — canary** | GitHub API reachability for the parity gate's fetch path | never blocks; reported | **no** |

| Test | Tier | Why |
|------|------|-----|
| `test_module_facades.py` identity + `__all__` | 1 | pure import assertions, no I/O |
| `test_module_size.py` | 1 | `wc -l` over `src/tripll` |
| `test_mergecraft_ref_parity.py` offline-skip / CI-fail | 1 | temp git repo, no network |
| `test_mergecraft_ref_parity.py` real fetch | **2** | needs `origin/main` reachable |
| `tripll --help` command inventory | **3** | the only check that catches a lost Typer registration |
| `create_app()` route-table inventory | **3** | the only check that catches a lost route |
| GitHub reachability for the fetch path | **4** | tests the world; never blocks |

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
8. **Report to the issue** (R40, convention 13) — **after** step 7, so the comment carries a real
   CI verdict rather than a hope:

```bash
gh issue comment <16|59> --repo sevn-bot/tripll --edit-last --create-if-none \
  --body-file ignorelocal/github-issues/status-<N>.md
```

Regenerate `status-<N>.md` from the shape in *Reporting to the issues*, then verify the edit landed
on the **existing** comment rather than creating a second one:

```bash
gh issue view <16|59> --repo sevn-bot/tripll --json comments \
  --jq '[.comments[] | select(.body | startswith("## Status — wave plan"))] | length'   # 1
```

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| R33 | Façade re-export, never a public-API break | Each god module becomes a thin module of imports plus `__all__`; the code moves to siblings. Callers are **not edited** — `ledger.py` alone has ~30 import sites, and a diff that both moves code and rewrites every importer hides the second change inside the first. Identity (`facade.name is submodule.name`) is the assertion, not equality, because equality passes for a re-implementation. Rejected: moving call sites (two changes in one diff); rejected: `from x import *` in the façade (mypy strict cannot see through it and `__all__` stops being the contract). ADR 013. |
| R34 | Characterization tests precede every extraction, and pass at baseline | The suite that locks a surface must be **green before** the refactor — that is what makes it evidence. This is exactly the "characterization-test prerequisite" #16 names as the reason the split was deferred in the first place. The private-name table is part of the suite, because `tests/` reaches into `engine._resolve_grep_brief`, `cli._orchestrator_watch_lines` and `api.app._resolve_runs_root`, and production code reaches into `api.app._read_config`. Rejected: trusting the existing suite — it passes today and would still pass with a name silently dropped from a façade, because nothing asserts the façade. ADR 013. |
| R35 | mergeCraft stays `pull_request` and stays non-required | Option (a) from #59, which is what #59 itself recommends. `pull_request_target` buys re-firing on conflicted PRs and costs repository secrets in scope on every PR, which then requires a same-repo guard the current job does not have. That trade is only worth making once the review is a **required** check, and it is not. The workflow carries a comment saying so, because the next person to add it to a branch ruleset needs to read the consequence at the point of change. Rejected: `pull_request_target` now (secret exposure with no benefit, plus `github.ref` resolves to the default branch under it, collapsing `mergecraft.yml:27-29`'s concurrency group across every open PR — one conflicted PR would cancel the rest). ADR 018. |
| R36 | The pin-parity gate checks the ref GitHub actually resolves | `check_mergecraft_ref_parity.py` reads the workflow pin from `git show <ref>:.github/workflows/mergecraft.yml`, defaulting to `origin/main` and overridable by env var. **Skip with a warning and exit 0 when the ref is unreachable and `CI` is unset**, so an offline `make check` is not blocked; **hard-fail when `CI` is set**, because a network hiccup that silently turns a gate into a no-op is worse than no gate — the operator believes it ran. Consequence, recorded: bump the default branch **first**, then `MERGECRAFT_REF`. Rejected: keeping the working-tree read (correct only while trunk is the default branch, and fails silently when it stops being); rejected: always hard-failing (breaks offline `make check` for everyone to guard against a topology change that has not happened). ADR 018. |
| R37 | Adopt the upstream hardened workflow; do not hand-roll one | CI-04 is real — the review fires on `synchronize` with no CI signal and no `check_suite_id`, so it speculates about mechanical failures the gates would have caught. The fix is a fail-open `wait-for-ci` job, and #59 records that exactly this is being proposed upstream in `alexhawat/mergeCraft`. tripll adopts it when it lands. Rejected: writing a second local copy now — a fail-open poller is easy to write and easy to get subtly wrong, and two copies diverge. ADR 018. |
| R38 | `_execute_node_body` moves whole, and moves last | The 643-line method at `engine.py:2739-3381` reads and writes 15+ `self` fields, holds `self._ledger_lock` across ledger sequences, and owns a closure (`_on_stream_event`, `engine.py:2914-2954`) that captures the ledger connection. It moves as **one unit** in W5, after every leaf seam is gone. Rejected: splitting it into dispatch / scope / verify / retry phases in the same wave as the move — that is a behaviour change wearing a refactor's clothes, and the resulting diff is unreviewable. A later plan may phase it, against a suite that by then exists. |
| R39 | The 1k rule becomes executable, with an honest allowlist | Today `oversized_file` is a *review problem type* (`docs/skw/problem-types.md:11`) — a thing a reviewer may notice. A prose limit is enforced by attention; a gate is enforced by the gate (R29's reasoning, already active in this repo). Final ships `make module-size-check` wired into `CI_STEPS` and `PATH_RULES`, with `inject.py` and `skw/render.py` allowlisted **and commented**, because they are over the limit and are **not named in #16**. Rejected: shipping the gate first (it would be red for eight waves and get disabled); rejected: silently expanding scope to the two unnamed files; rejected: no gate (every line this plan removes could return without anyone noticing). |
| R40 | One rolling status comment per issue, edited in place; closed only after merge | Each issue gets **one** status comment created at W0 and rewritten at every wave close-out via `gh issue comment --edit-last --create-if-none`, so GitHub always shows current state. A **new** comment appears exactly twice more: when the PR opens, and as the final evidence comment at Thermos — those are events, not state. Every "Delivered" line carries a real number and a real sha, and the comment says **"not merged"** until it is. Rejected: one comment per wave — #16 would collect seven near-identical updates, and the signal-to-noise of a tracker is the reason anyone reads it. Rejected: commenting only at the end — that is the status quo this plan is fixing, and #16's own history shows the maintainer hand-writing partial-progress comments after #47 and #51 precisely because a silent multi-PR program is unreadable. Rejected: `--edit-last` without `--create-if-none` — it fails on the first call, so the first wave to run would either crash or fall back to creating a duplicate. Rejected: closing on the wave that satisfies the issue — nothing is merged until a human merges (D15), and a closed issue on an unmerged branch is a lie. |

## Out of scope

- **`src/tripll/inject.py` (1,284 lines) and `src/tripll/skw/render.py` (1,161 lines)** — over the
  1k limit, **not named in #16**. Allowlisted in Final's gate with a comment each. File a follow-up
  issue in Final; do not expand this plan.
- **Phasing `_execute_node_body`** into dispatch / scope / verify / retry (R38) — it moves whole.
- **Any behaviour change, anywhere.** New commands, new routes, new options, changed defaults,
  changed error messages, changed log lines. If a caller can observe it, it is not in this plan.
- **Renaming anything public** — no command, group, option, route, path, node kind or config key
  changes name. A rename is a caller-visible change dressed as tidying.
- **Re-extracting the nine `api/_*.py` modules** that already exist, or `cli/_run.py` /
  `cli/_shared.py`, or `engine_scheduling.py`. They are precedent, not backlog.
- **Adding `wait-for-ci` to the mergeCraft workflow** (R37) — adopt upstream when it lands.
- **`pull_request_target`** (R35) — reconsider only if mergeCraft review becomes required.
- **Any `tests/` reorganisation.** The test tree mirrors `src/`, and after this plan it will mirror
  it less well. That is a known, accepted debt: moving tests in the same program that moves source
  destroys the one fixed reference point a reviewer has.
- **Splitting `Engine` into multiple classes.** The façade keeps one `Engine`;
  `loops/l1_outer.py:38`, `loops/dispatch_bridge.py:30,345` and `loops/outer_post_wave.py:26` all
  take an `Engine` instance.

## Wave checklist

| Wave | Provider / model | Scope | Findings | Status |
|------|------------------|-------|----------|--------|
| W0 | `cursor_local` claude-opus-5 | Baseline, anchor re-grep, ADRs 013 + 018, contract pin, compile the machine block, **draft PR + kickoff issue comments** | — | [x] (2026-07-30 ✅: b00a019 — CI [30560055121](https://github.com/sevn-bot/tripll/actions/runs/30560055121) green, PR #61, ADRs 013+018) |
| W1 | `cursor_local` auto | Characterization suite + test plan — `role: test-author` | all | [x] (2026-07-30 ✅: 33aaad4 — CI [30560683682](https://github.com/sevn-bot/tripll/actions/runs/30560683682) green) |
| W2 | `cursor_local` auto | **#59**: trigger decision, topology-proof parity gate, base coverage, runbook | CI-01…CI-04 | [ ] |
| W3 | `cursor_local` auto | **`ledger.py`** → façade + schema / store / query | GOD-05 | [ ] |
| W4 | `cursor_local` auto | **`engine.py` leaves**: worktrees, human gates, verify, brief | GOD-01 | [ ] |
| W5 | `cursor_local` auto | **`engine.py` core**: exits, orchestrator, batch drive, node dispatch | GOD-01 | [ ] |
| W6 | `cursor_local` auto | **`cli/__init__.py`** → registrars over 11 command modules | GOD-02 | [ ] |
| W7 | `cursor_local` auto | **`api/app.py`** → factory over routers, models, deps | GOD-03 | [ ] |
| W8 | `cursor_local` auto | **`api/ui/router.py`** → dashboard route modules | GOD-04 | [ ] |
| Final | `cursor_local` claude-opus-5 | `make module-size-check`, xfail sweep, `ci-resume` green, change summary, **PR ready + final status edits** | GOD-06 | [ ] |
| Thermos | `cursor_local` claude-opus-5, **fresh session** | Branch review, tamper audit, merge request | — | [ ] |

Every `auto` wave carries `fallback = ["claude_code"]`. Failover changes the **provider only**.

## Execution order & parallelism

**Dispatched order (serial — by choice):**

```text
W0 → W1 → W2 → W3 → W4 → W5 → W6 → W7 → W8 → Final → Thermos
```

| Hard dependency | Reason |
|-----------------|--------|
| W0 before everything | anchors and contracts precede work |
| W1 before W2–W8 | the characterization suite defines acceptance, and it must be green *before* the first move |
| **W3 before W4** | `engine.py:106-121` imports 12 names from `ledger` at module scope. Prove the ledger façade holds under the largest consumer before that consumer also starts moving |
| **W4 before W5** | same file. `engine.py` is a serialized writer, and the leaf seams must be gone before the coupled ones move (R38) |
| W5 before W6 | `cli/__init__.py:887` and `cli/_shared.py:28,103` import `Engine` and `RunResult`; the engine façade settles first |
| W6 before W7 | serialized by choice — see below |
| **W7 before W8** | `api/ui/router.py:79` imports `_read_config`, `_slug_profile_id` and `_tripll_argv` **out of `api.app`**. This is a real edge, not a scheduling preference: W8 against a moving `api.app` is a broken dashboard |
| Final last | the gate is only landable once the tree it guards is already under the limit |

**Why serial.** W2 is the one wave that shares no file with any other — it touches
`.github/workflows/`, `scripts/` and the `Makefile`, and nothing under `src/tripll/`. It *could* run
beside W3. It does not, for the same reason the ai-layer plan ran serial: per-wave
*commit → push → green CI on that sha* is this plan's acceptance mechanism, and two waves committing
to one branch defeats it. The honest parallel width here is ~1.1 waves.

### Merge hotspots

| File | Waves | Note |
|------|-------|------|
| `src/tripll/engine.py` | W4, W5 | two waves, one file — **serialize**; W4 owns the docstring `Exports:` block and W5 updates it again |
| `src/tripll/api/app.py` | W7 (writer), W8 (reader) | W8 **must not edit it** — its contract forbids it |
| `Makefile` | W2 (`mergecraft-ref-check`), Final (`module-size-check`) | far apart in the chain; two different targets |
| `scripts/ci_lib.py` | W2, Final | `PATH_RULES` gains one entry in each |
| `tests/` | W1 only | impl waves are forbidden from editing it (convention 3) |
| `CHANGELOG.md` | all | one bullet stream |
| `docs/design-note.md` | W5, W8 | module-map paths; W5 is the author |

---

## Wave W0 — Baseline, anchors, ADRs, contract pinning

**Blocks:** everything

- [x] **W0.1** Record baseline: `git rev-parse HEAD`, `git rev-parse main`, the base actually used,
      and whether `alexhawat-readme-and-oss-audit` has merged to `main`. (2026-07-30 ✅: b00a019 — HEAD/main `2e4a8f2`; `ee4e247` not merged)
- [x] **W0.2** **Re-grep every anchor** in the gap table and the extraction contract at HEAD, and
      correct it in place. The six that matter most, because whole waves rest on them:
      `engine.py` `Engine` class range and `_execute_node_body` range; `ledger.py`'s lazy
      `TaskGraphWriter` call sites; `cli/__init__.py`'s `register_run_commands(app)` line and the
      `main()` range; `api/app.py`'s `create_app` range; **`api/ui/router.py:79`'s import from
      `api.app`** — if that import has moved or gone, the W7→W8 edge changes. (2026-07-30 ✅: b00a019 — Engine 713-3589, _execute_node_body 2739-3381)
- [x] **W0.3** **Verify the private-name table by grep, name by name.** Any entry whose importer no
      longer imports it is deleted from the table; any *new* private import found is added. This
      table is what W1 tests, so a stale row becomes a missing assertion. (2026-07-30 ✅: b00a019 — all 9 rows verified at HEAD)
- [x] **W0.4** Write ADR **013** (god-module extraction — R33, R34, R38) and **018** (mergeCraft CI
      trigger posture — R35, R36, R37). Each states its **rejected alternative** — an ADR without
      one is a description, not a decision. **Confirm 013 is still unclaimed** before using it. (2026-07-30 ✅: b00a019 — docs/decisions/013-*, 018-*)
- [x] **W0.5** Copy this file to `docs/plans/god-module-and-ci-posture.md`; record both sha256
      values in Re-entry. (2026-07-30 ✅: b00a019 — sha256 `7a87e1fe…`)
- [x] **W0.6** **Compile the machine block at HEAD** — `tripll validate-plan` and
      `plan.shape_checks.compile_plan`. If it does not compile, **fix this plan**, not the compiler. (2026-07-30 ✅: b00a019 — validate-plan exit 0)
- [x] **W0.7** **Commit + push** (`docs(plan): baseline and ADRs for god-module extraction and CI posture`). (2026-07-30 ✅: b00a019)
- [x] **W0.8** *(R40)* **Open the draft PR** — after the first push, so every subsequent status
      update has a stable link and so CI has a PR to run against. Body links this plan, both issues
      and the wave map. **Draft**, not ready: nine waves are still outstanding, and a
      ready-for-review PR that is nine waves from done wastes a reviewer's time.

      ```bash
      gh pr create --repo sevn-bot/tripll --draft --base main \
        --head wave/god-module-and-ci-posture \
        --title "refactor: god-module extraction and mergeCraft CI posture" \
        --body "$(cat <<'EOF'
      Wave plan: `docs/plans/god-module-and-ci-posture.md`

      Closes #16
      Closes #59

      Ten waves; see the plan's Wave checklist for per-wave status. Draft until Final.
      EOF
      )"
      ```

      Record the number in Re-entry. `Closes #16` / `Closes #59` in the **PR** body is what makes
      the human merge close both issues — which is the only path by which they should close (D15).
      (2026-07-30 ✅: b00a019 — draft PR #61)
- [x] **W0.9** *(R40)* **Create the two rolling status comments** — one on #16, one on #59, in the
      shape from *Reporting to the issues*, naming the branch, the draft PR, the base sha and the
      wave map, with **no waves delivered yet**. Use `--edit-last --create-if-none` from the first
      call so every later wave rewrites the same comment. **Record both comment ids in Re-entry** —
      a later wave that cannot find the comment will create a duplicate, which is the failure mode
      R40 exists to prevent. (2026-07-30 ✅: b00a019 — #16 comment 5118338652, #59 comment 5133336437)
- [x] **W0.10** **Commit + push** the Re-entry update (PR number + comment ids) — the plan is not
      resumable without them. (2026-07-30 ✅: c210ca3 — re-entry + contract updated)

**Acceptance:**

```bash
ls docs/decisions/013-*.md docs/decisions/018-*.md | wc -l     # 2
grep -c 'Rejected' docs/decisions/013-*.md                     # >= 1, and same for 018
tripll validate-plan docs/plans/god-module-and-ci-posture.md   # exit 0
shasum -a 256 docs/plans/god-module-and-ci-posture.md          # recorded in Re-entry
# the baseline this plan asserts:
find src/tripll -name '*.py' -exec wc -l {} + | sort -rn | awk '$1 > 1000 && $2 != "total"'
# expect exactly 7 rows: engine 3603, cli/__init__ 2095, api/app 1626,
#                        api/ui/router 1470, ledger 1394, inject 1284, skw/render 1161
# the W7 -> W8 edge is real:
grep -n 'from tripll.api.app import' src/tripll/api/ui/router.py     # names _read_config etc.
# every private-name row still holds:
grep -n '_resolve_grep_brief' tests/test_brief_graph_pack.py
grep -n '_MAX_NO_PROGRESS_DISPATCHES' tests/test_w2_controls.py
grep -n '_run_integration' tests/test_delivery_live_fixture.py
grep -n '_orchestrator_watch_lines' tests/test_orchestrator_mode_smoke.py
grep -n '_resolve_runs_root' tests/test_api.py
# the draft PR exists and closes both issues on merge (W0.8):
gh pr view --repo sevn-bot/tripll --json number,isDraft,baseRefName,body \
  --jq '{n:.number, draft:.isDraft, base:.baseRefName,
         closes:(.body|[scan("[Cc]loses #[0-9]+")])}'   # draft:true, base:main, closes both
# exactly one status comment per issue, and neither issue is closed (W0.9, R40):
for n in 16 59; do
  gh issue view $n --repo sevn-bot/tripll --json state,comments \
    --jq "\"#$n \(.state) rolling=\([.comments[] | select(.body|startswith(\"## Status — wave plan\"))]|length)\""
done                                                    # each: OPEN rolling=1
# the status comments are honest about not being merged:
gh issue view 16 --repo sevn-bot/tripll --json comments \
  --jq '[.comments[] | select(.body | test("not merged"))] | length'   # >= 1
```

---

## Wave W1 — Characterization suite — `role: test-author`, agent: test-creator

**Depends:** W0 · **Blocks:** W2–W8

**This suite is green before the refactor and green after it.** That is what separates it from a RED
suite, and it is the whole reason #16 called a characterization suite a *prerequisite*. The only
test allowed to fail at baseline is the module-size one.

- [x] **W1.1** `tests/test_module_facades.py` — for each of `engine`, `ledger`, `cli`, `api.app`:
      assert every name in the façade's public surface resolves, and for every already-extracted
      submodule assert **identity** (`facade.name is submodule.name`), following
      `tests/test_engine_scheduling.py:34-41`. At baseline the submodule half covers
      `engine_scheduling`, `cli._run` and `cli._shared`; later waves extend it. (2026-07-30 ✅: W1 — engine/__all__, ledger imports, cli._run identity)
- [x] **W1.2** `tests/test_module_facades.py` — **the private-name table**, one assertion per row
      (W0.3's verified version). These are the names a plausible extraction silently drops. (2026-07-30 ✅: W1 — 10 parametrized rows)
- [x] **W1.3** `tests/test_module_facades.py` — `ledger.__all__` **completeness**: every name any
      module under `src/` or `tests/` imports from `tripll.ledger` is in `__all__`. `ledger.py` has
      no `__all__` today and its prose `Exports:` list (`ledger.py:17-40`) is already missing
      `RunRow`, `WaveRow`, `AttemptRow`, `reset_wave_attempts` and `void_infra_attempt_count`, so
      this test **xfails until W3** and is the thing that makes W3's façade provably complete. (2026-07-30 ✅: W1 — xfail strict=False)
- [x] **W1.4** *(tier 3)* `tripll --help` **command inventory** — snapshot all 49 commands, all 12
      groups, and **the order they appear in**. `register_run_commands(app)` runs at
      `cli/__init__.py:76`, *before* the root callback at `:84`; registration order is observable in
      `--help` and W6 will reorder it if nothing asserts otherwise. (2026-07-30 ✅: W1 — 55 commands, 12 groups)
- [x] **W1.5** *(tier 3)* `create_app()` **route-table inventory** — snapshot every
      `(method, path)` pair for all 28 JSON routes and all 22 dashboard routes, plus the
      `include_in_schema=False` flag on the UI router. This is the only check that catches a route
      lost in W7 or W8. (2026-07-30 ✅: W1 — 31 JSON + 22 UI routes)
- [x] **W1.6** `tests/test_module_size.py` — assert every `src/tripll/**/*.py` outside the
      allowlist is ≤ 1000 lines, with **the offending path and its line count in the failure
      message**. `xfail(strict=False, reason="green after Final: …")` at baseline. (2026-07-30 ✅: W1 — xfail names 5 oversized modules)
- [x] **W1.7** `tests/test_mergecraft_ref_parity.py` — against a **temp git repo**: matching pins
      pass; drifted pins fail; an unreachable ref with `CI` unset **skips with a warning and exit
      0**; the same unreachable ref with `CI=1` **exits non-zero**. Tier-2 real-fetch case behind
      `RUN_LIVE=1`. (2026-07-30 ✅: W1 — match/drift green; unreachable xfail until W2)
- [x] **W1.8** `docs/test-plans/god-module-and-ci-posture.md` — finding → test → wave → tier matrix. (2026-07-30 ✅: W1)
- [x] **W1.9** **Commit + push** (`test: characterization suite for god-module extraction`). (2026-07-30 ✅: W1)
- [x] **W1.10** *(R40)* **Report to #16** — the prerequisite the issue itself names as the reason the
      split was deferred is now met. Record: the suite is **green at baseline**, what it locks (façade
      identity, the nine private names, the `--help` and route inventories), and that
      `test_module_size.py` xfails on purpose until Final. Carry the wave sha and CI run. (2026-07-30 ✅: W1)

**Acceptance:**

```bash
make test                                        # green; only test_module_size + __all__ xfail
# the suite characterizes the tree as it is now, not as it will be:
make test -- -k "module_facades" -q              # 0 failures, 0 xfails
make test -- -k "module_size" -q                 # xfailed, and the message names each oversized file
grep -rn 'strict=True' tests/test_module_size.py tests/test_module_facades.py | wc -l   # 0
grep -c ' is ' tests/test_module_facades.py      # >= 1 — identity, not equality
# the inventories are snapshots, not smoke tests:
grep -c 'run-inject\|run-reconcile-graph' tests/test_module_facades.py   # >= 1 (hidden cmds counted)
```

---

## Wave W2 — mergeCraft CI posture and a topology-proof pin-parity gate

**Findings:** CI-01, CI-02, CI-03, CI-04 · **Decisions:** R35, R36, R37 · **Depends:** W1

The only wave in this plan that changes behaviour, and it changes only CI's.

- [ ] **W2.1** *(CI-01, R35)* Keep `pull_request`. Add a comment above `mergecraft.yml:8`'s `on:`
      recording the decision **and its consequence**: `pull_request` does not run when
      `refs/pull/N/merge` cannot be built, so **`mergeCraft review` must stay non-required** in
      every branch ruleset. A conflicted PR would otherwise carry a permanently missing check that
      does not re-fire once the conflict is resolved.
- [ ] **W2.2** *(R35)* Record in ADR 018 the **exact** shape option (b) would need, so a future
      switch is a lookup rather than a rediscovery: a same-repo guard on the secret-bearing step
      (`pull_request` gets that for free and `pull_request_target` does not), and `concurrency`
      re-keyed on the **PR number** — under `pull_request_target`, `github.ref` resolves to the
      default branch, so `mergecraft.yml:27-29`'s current group collapses every open PR into one
      and they cancel each other.
- [ ] **W2.3** *(CI-02, R36)* Harden `scripts/check_mergecraft_ref_parity.py`: read the workflow
      pin from `git show <ref>:.github/workflows/mergecraft.yml` rather than
      `WORKFLOW.read_text()` (`check_mergecraft_ref_parity.py:36-46`). `ref` defaults to
      `origin/main`, overridable by env var. On a missing ref, attempt **one**
      `git fetch --depth=1`, then: **warn and exit 0 when `CI` is unset**, **exit non-zero when
      `CI` is set**. Keep the two existing regexes (`:22-26`) and the drift message (`:52-59`)
      unchanged — the failure text is what an operator reads.
- [ ] **W2.4** *(CI-03)* Decide base-branch coverage and **write the decision into the workflow as
      a comment** beside `branches:` (`mergecraft.yml:10`). Either confirm `main`-only is intended
      (stacked `wave/*` and `feat/*` PRs get no review, by choice) or widen the glob. A comment
      either way — the current file states nothing.
- [ ] **W2.5** *(CI-04, R37)* Record in ADR 018 that the `wait-for-ci` fix is **adopted from
      upstream when it lands**, not hand-rolled. Name what it must do: poll check-runs for the head
      SHA, feed the outcome **and the `check_suite_id`** into the prompt, and **fail open on every
      path** so a slow or absent CI run never blocks a review.
- [ ] **W2.6** *(R36)* `docs/runbooks/operator-runbook.md` — the **bump order** the new gate
      implies: merge the workflow pin to the default branch **first**, then bump `Makefile:14`'s
      `MERGECRAFT_REF`. The reverse order now fails the gate, and it fails for a reason that is not
      obvious mid-bump.
- [ ] **W2.7** Confirm `scripts/ci_lib.py:60-67`'s `PATH_RULES` entry still maps
      `mergecraft.yml`, `Makefile` and the script to `mergecraft-ref-check`. Extend it only if W2.3
      adds a file.
- [ ] **W2.8** **Commit + push** (`ci(mergecraft): record trigger posture and make the pin gate topology-proof`).
- [ ] **W2.9** *(R40)* **Report to #59** — the only wave that touches it, so this edit takes its
      rolling comment from "not started" to "all four parts landed". Tick each of the issue's own
      four acceptance boxes, quote the recorded decision (option (a)), link ADR 018, and carry the
      wave sha and CI run. **Do not close it** — the `Closes #59` in the PR body does that on merge.

**Acceptance:**

```bash
make test -- -k mergecraft                             # green
make mergecraft-ref-check                              # exit 0 on a clean tree
# reads the ref, not the working tree:
grep -n 'git' scripts/check_mergecraft_ref_parity.py | grep -c 'show'      # >= 1
grep -c 'read_text' scripts/check_mergecraft_ref_parity.py                 # Makefile only
# a working-tree-only edit no longer fools the gate into passing:
sed -i.bak 's/@b8e83a82e97ed537706d9a712e59af9ef031588f/@0000000000000000000000000000000000000000/' \
  .github/workflows/mergecraft.yml
make mergecraft-ref-check; echo "working-tree drift => exit $?"   # still compares against origin/main
mv .github/workflows/mergecraft.yml.bak .github/workflows/mergecraft.yml
# offline is a warning, CI is a failure:
TRIPLL_MERGECRAFT_PARITY_REF=refs/does/not/exist make mergecraft-ref-check; echo "offline => $?"  # 0
CI=1 TRIPLL_MERGECRAFT_PARITY_REF=refs/does/not/exist make mergecraft-ref-check; echo "ci => $?"  # non-zero
# the decisions are written down where they are read:
grep -c 'non-required\|not required' .github/workflows/mergecraft.yml      # >= 1
grep -A2 -n 'branches:' .github/workflows/mergecraft.yml | grep -c '#'     # >= 1
grep -ci 'pull_request_target' docs/decisions/018-*.md                     # >= 1
grep -ci 'wait-for-ci\|check_suite_id' docs/decisions/018-*.md             # >= 1
grep -ci 'MERGECRAFT_REF' docs/runbooks/operator-runbook.md                # >= 1
# still on pull_request (R35):
grep -c 'pull_request_target' .github/workflows/mergecraft.yml             # 0
# #59 reported, still open, still one comment (W2.9, R40):
gh issue view 59 --repo sevn-bot/tripll --json state,comments \
  --jq '{state, rolling:([.comments[] | select(.body|startswith("## Status — wave plan"))]|length)}'
                                                                           # OPEN, rolling=1
gh issue view 59 --repo sevn-bot/tripll --json comments \
  --jq '.comments[-1].body' | grep -c '018-mergecraft-ci-trigger-posture'   # >= 1 — ADR linked
```

---

## Wave W3 — `ledger.py` → façade over schema, store, query

**Findings:** GOD-05 · **Decisions:** R33, R34 · **Depends:** W2

First extraction, and deliberately the easiest: `ledger.py` has **no god class**, no module-level
mutable state, and clean functional seams. It is also the module with the most importers, which is
why it goes first — if the façade pattern is going to fail, it fails here, cheaply.

- [ ] **W3.1** `src/tripll/ledger_schema.py` — the state literals and terminal frozensets
      (`ledger.py:57-77`), the four row dataclasses (`:84-216`), `_DDL` (`:223-286`),
      `LedgerConnection` (`:294-323`) and all seven `_migrate_*` functions (`:364-498`).
      **Migrations keep their current order**; `open_ledger` is the only thing that sequences them.
- [ ] **W3.2** `src/tripll/ledger_store.py` — `open_ledger` (`:331-361`) and every write:
      `insert_run`, `insert_wave`, `insert_attempt`, `void_infra_attempt_count`, `transition_run`,
      `transition_wave`, `delete_attempts_for_node`, `reset_wave_attempts`, `end_attempt`,
      `append_event` (`:534-981`), plus the helpers `_now_iso`, `_sum_attempt_costs`,
      `_sync_run_cost_from_attempts` and `_maybe_sync_wave_transition` (`:506-526`, `:614-630`).
- [ ] **W3.3** **The lazy imports stay lazy.** `TaskGraphWriter` is imported *inside*
      `_maybe_sync_wave_transition` (`ledger.py:621`) and *inside* `insert_attempt`
      (`ledger.py:707`) to break a cycle with `graphstore.task_sync`. Both stay function-local.
      Hoisting either one produces an `ImportError` at CLI startup, after the diff looks clean.
- [ ] **W3.4** `src/tripll/ledger_query.py` — every read: `list_events`, `list_fired_exit_ids`,
      `latest_events_by_node`, `get_run_cost`, `get_run_cost_by_provider`, `get_run`, `get_wave`,
      `list_waves`, `list_attempts` (`:984-1394`).
- [ ] **W3.5** `ledger.py` becomes a façade **with a real `__all__`** — the first one it has ever
      had. It must list the **full external name set**, which is larger than the docstring's
      `Exports:` block (`:17-40`): add `RunRow`, `WaveRow`, `AttemptRow`, `reset_wave_attempts` and
      `void_infra_attempt_count`. W1.3's completeness test is what proves this, and it stops
      xfailing here.
- [ ] **W3.6** **Zero caller edits.** `engine.py:106-121`, `inject.py:42-50`, `api/app.py:76-84`,
      `api/ui/router.py:81-93`, `cli/_shared.py:317`, `loops/*`, `report.py`, `calibrate/`,
      `pipeline.py`, `rules/postmortem.py` and every test are **untouched**. If any of them needs
      an edit, the façade is incomplete — fix the façade.
- [ ] **W3.7** Keep the docstring `Exports:` inventory accurate in the same commit, and correct the
      five names it was already missing.
- [ ] **W3.8** **Commit + push** (`refactor(ledger): split schema, store and query behind a facade`).

**Acceptance:**

```bash
make test                                              # green
wc -l src/tripll/ledger.py                             # < 200
wc -l src/tripll/ledger_schema.py src/tripll/ledger_store.py src/tripll/ledger_query.py  # each < 1000
# zero caller edits (R33) — the criterion this wave lives or dies on:
git diff main...HEAD --name-only -- src/tripll | grep -v '^src/tripll/ledger' | wc -l    # 0
git diff main...HEAD --name-only -- tests | wc -l                                        # 0
# the facade is complete:
make test -- -k "module_facades" -q                    # green, __all__ xfail now xpasses
python -c "import tripll.ledger as l; print(len(l.__all__))"      # >= 29
python -c "
import tripll.ledger as f, tripll.ledger_store as s
assert f.insert_attempt is s.insert_attempt, 'not a re-export'
print('identity holds')"
# the lazy imports are still lazy:
grep -c 'from tripll.graphstore' src/tripll/ledger_store.py       # 0 at module scope
awk '/^from|^import/{if (/graphstore/) print NR": "$0}' src/tripll/ledger_store.py | wc -l   # 0
# no cycle:
grep -c 'tripll.engine' src/tripll/ledger*.py                     # 0
python -c "import tripll.ledger_schema, tripll.ledger_store, tripll.ledger_query; print('ok')"
```

---

## Wave W4 — `engine.py` leaf seams

**Findings:** GOD-01 · **Decisions:** R33, R38 · **Depends:** W3

`Engine` is 2,875 of `engine.py`'s 3,603 lines. This wave does not touch it — it removes everything
around it, plus the three method groups that read the fewest `self` fields.

- [ ] **W4.1** `src/tripll/engine_worktrees.py` — `WorktreeManager` (`engine.py:282-390`),
      `Verifier` (`:393-410`), `GitWorktreeManager` (`:413-471`), `MakeVerifier` (`:474-606`),
      `SingleBranchWorktreeManager` (`:609-646`). ~357 lines, and the cleanest seam in the file:
      all five are injected into `Engine.__init__` (`:761-762`) and hold no back-reference to it.
      All five are in `__all__` (`:147-153`) — re-export them.
- [ ] **W4.2** `src/tripll/engine_human_gates.py` — `complete_human_gate_waves` (`:181-229`) and
      `_resolve_grep_brief` (`:172-179`). The second one is **private and tested**
      (`tests/test_brief_graph_pack.py:17`); it must still resolve from `tripll.engine`.
- [ ] **W4.3** `src/tripll/engine_verify.py` — `_verify_with_retries`, `_run_isolated_verify`,
      `_run_quality_gauntlet` (`:1523-1641`) and the `_VERIFY_ONLY_RETRIES` constant (`:665`).
      These read `self.verifier`, `self.runs_root`, `self.repo_root`, `self.adapter` and
      `self._last_checkpoint_sha` — pass them explicitly or take a small context object. **Do not**
      move a `self` field's ownership out of `Engine`.
- [ ] **W4.4** `src/tripll/engine_brief.py` — `_brief_for` (`:3504-3587`),
      `_append_external_upload_dirs` (`:3461-3502`, already a `@staticmethod`) and `_safe`
      (`:3590-3603`). `_brief_for` is the heaviest `self` reader in this wave (`_grep_brief`,
      `_role_dispatch_effective`, `_wave_commit_shas`, `_pools`, `_default_provider`,
      `_last_checkpoint_sha`, `runs_root`, `repo_root`) and has exactly **one** call site
      (`:2824-2826`), which is what makes it safe to move.
- [ ] **W4.5** **Update the module docstring `Exports:` inventory** (`engine.py:44-59`) in the same
      commit. `tests/test_provider_pools.py:35-39` asserts on `engine.__doc__` — the docstring is
      part of the tested surface, not commentary.
- [ ] **W4.6** Keep `_MAX_NO_PROGRESS_DISPATCHES` (`:690`) resolvable from `tripll.engine`
      (`tests/test_w2_controls.py:16`).
- [ ] **W4.7** **Zero caller edits.** `cli/__init__.py:887`, `cli/_shared.py:28,103`,
      `api/app.py:831`, `loops/l1_outer.py:38`, `loops/dispatch_bridge.py:30,345`,
      `loops/outer_post_wave.py:26`, `report.py:22,311`, `inject.py:301,312,399` — untouched.
- [ ] **W4.8** **Commit + push** (`refactor(engine): extract worktrees, human gates, verify and brief`).

**Acceptance:**

```bash
make test                                              # green
wc -l src/tripll/engine.py                             # < 2600
wc -l src/tripll/engine_worktrees.py src/tripll/engine_human_gates.py \
      src/tripll/engine_verify.py src/tripll/engine_brief.py     # each < 1000
# zero caller edits:
git diff main...HEAD --name-only -- src/tripll | grep -v '^src/tripll/engine' | wc -l    # 0
git diff main...HEAD --name-only -- tests | wc -l                                        # 0
# identity, including the private names:
python -c "
import tripll.engine as e, tripll.engine_worktrees as w, tripll.engine_human_gates as h
assert e.GitWorktreeManager is w.GitWorktreeManager
assert e.complete_human_gate_waves is h.complete_human_gate_waves
assert e._resolve_grep_brief is h._resolve_grep_brief
assert e._MAX_NO_PROGRESS_DISPATCHES is not None
print('identity holds')"
# the docstring is part of the surface:
make test -- -k provider_pools -q                      # green
# _execute_node_body did not move (R38):
grep -n '_execute_node_body' src/tripll/engine.py      # still here
# no cycle back up the stack:
grep -c 'tripll.cli\|tripll.api' src/tripll/engine_*.py    # 0
```

---

## Wave W5 — `engine.py` core seams

**Findings:** GOD-01 · **Decisions:** R33, R38 · **Depends:** W4

The wave that gets `engine.py` under the limit. Highest risk in the plan, which is why it is fifth
and not first.

- [ ] **W5.1** `src/tripll/engine_exits.py` — the nine exit-evaluation methods (`:1354-1521`) and
      the pause/marker constants they share (`:659-665`, `_pause_requested` `:981-994`).
      Call sites: `_drain_batch` (`:2471`) and `_execute_node_body`.
- [ ] **W5.2** `src/tripll/engine_orchestrator.py` — `_initial_orchestrator_rows` (`:649-652`),
      `_orchestrator_agent_enabled` (`:668-682`), the six orchestrator methods (`:1174-1352`),
      `_handle_review_gate` (`:2098-2217`) and `_drive_orchestrator_serial` (`:2219-2400`).
      **The hazard:** `_configure_orchestrator` (`:1174-1221`) mutates `self.adapter`, `self.wtm`,
      `self._max_parallel` and `self._pools`. Those fields keep living on `Engine`; the extracted
      function receives the instance and mutates it, exactly as the method does today. Do not
      relocate ownership.
- [ ] **W5.3** `src/tripll/engine_batch_drive.py` — `drive_wave_batches` (`:1700-1792`, **public**),
      `_prepare_run_ledger` (`:1794-1858`), `_drain_batch` (`:2402-2569`), `_run_concurrent_set`
      (`:2571-2626`), `_shielded_finalize_wave_ledger` (`:2628-2670`) and the five pause-artefact
      writers (`:1015-1085`). The nested `_guarded` (`:2597-2598`) and `_do` (`:2645-2668`)
      closures move with their enclosing functions, unchanged.
- [ ] **W5.4** *(R38)* `src/tripll/engine_node_dispatch.py` — `_execute_node` (`:2672-2696`),
      `_COMPOUNDING_TERMINAL_OUTCOMES` (`:2698-2700`), `_finalize_wave_compounding`
      (`:2702-2737`), **`_execute_node_body` (`:2739-3380`) as one unit**,
      `_owned_changed_paths` (`:3382-3423`), `_recover_worktree` (`:3425-3434`),
      `_checkpoint_attempt` (`:3436-3459`) and `_end_attempt_with_usage` (`:1643-1661`).
      The `_on_stream_event` closure (`:2914-2954`) moves inside its parent and **must still
      capture the same ledger connection, `run_id` and `self._ledger_lock`** — it is the only place
      streamed events reach the ledger, and it is a closure precisely so the lock is the same object.
- [ ] **W5.5** `engine.py` retains `Engine` (`__init__`, `start`, `approve`, `resume`, `_drive`,
      `_drive_via_outer_loop`, `_scaffold_w0_worktrees`, the config/provider fabric, and thin
      delegating wrappers), `NodeResult`, `RunResult`, `__all__` and the façade imports.
      **Target: under 1,000 lines.**
- [ ] **W5.6** **The lazy imports stay lazy** — `inject.reconcile_run_graph` (in `resume`) and
      `loops.l1_outer.compile_l1_outer_graph`. `loops/l1_outer.py`, `loops/dispatch_bridge.py` and
      `loops/outer_post_wave.py` all take an `Engine` **instance**; `Engine` stays one class in
      `engine.py` and nothing in `loops/` is edited.
- [ ] **W5.7** Update `engine.py`'s `Exports:` inventory again, and `docs/design-note.md` §0.1's
      module map.
- [ ] **W5.8** **Commit + push** (`refactor(engine): extract exits, orchestrator, batch drive and node dispatch`).

**Acceptance:**

```bash
make test                                              # green
wc -l src/tripll/engine.py                             # < 1000  <- the wave's whole point
for f in src/tripll/engine_*.py; do wc -l "$f"; done   # each < 1000
# zero caller edits:
git diff main...HEAD --name-only -- src/tripll | grep -v '^src/tripll/engine' | wc -l    # 0
git diff main...HEAD --name-only -- tests | wc -l                                        # 0
# _execute_node_body moved whole (R38) — one body, not four phase functions:
grep -c 'def _execute_node_body' src/tripll/engine_node_dispatch.py       # 1
grep -c 'def _execute_node_body' src/tripll/engine.py                     # 0
grep -n '_on_stream_event' src/tripll/engine_node_dispatch.py             # still nested
# the lock is still one object shared with the ledger path:
grep -c '_ledger_lock' src/tripll/engine_node_dispatch.py                 # >= 1
# lazy imports still lazy:
awk '/^from|^import/{if (/tripll.inject|l1_outer/) print NR}' src/tripll/engine.py | wc -l   # 0
# Engine is still one class, and loops still get an instance:
python -c "import tripll.engine as e; print(type(e.Engine).__name__)"     # type
git diff main...HEAD --name-only -- src/tripll/loops | wc -l              # 0
make test -- -k "engine or concurrency or orchestrator or human_gate" -q  # green
```

---

## Wave W6 — `cli/__init__.py` → registrars over command modules

**Findings:** GOD-02 · **Decisions:** R33 · **Depends:** W5

Eleven new modules, one pattern, copied from `cli/_run.py:481-486`. The risk here is not breakage —
it is a **silently reordered `--help`**, which W1.4 exists to catch.

- [ ] **W6.1** One `register_<group>_commands(app)` per module, following `_run.py:481-486`
      exactly. No second registration mechanism.
      | Module | Moves | ~Lines |
      |--------|-------|-------:|
      | `_onboard.py` | `setup`, `doctor`, `init`, `new` (`:106-232`) | 116 |
      | `_status.py` | `status`, `list-runs` + `_find_ledger_path`…`_status_run` (`:240-568`) | 329 |
      | `_run_ops.py` | `pause`, `resume`, `approve`, `delete-run`, `reset-run`, `pre0-interview` (`:734-968`) | 215 |
      | `_wave.py` | `wave_app` + `wave add` (`:571-731`) | 161 |
      | `_plan.py` | `validate`, `validate-plan`, `_print_graph_summary`, `plan_app`, `plan`, `plan publish` (`:976-1214`) | 239 |
      | `_graph.py` | `graph_app` + extract / fuse / gate / query, `calibrate` (`:1226-1231`, `:1390-1510`, `:1757-1799`) | 164 |
      | `_findings.py` | `findings_app` + 4 commands (`:1233-1238`, `:1513-1635`) | 129 |
      | `_rules.py` | `rules_app` + derive / list / promote / retire (`:1240-1245`, `:1638-1754`) | 123 |
      | `_review.py` | `review_app` + 4 commands, `bench_app` + `bench run` (`:1247-1259`, `:1262-1387`) | 136 |
      | `_pr.py` | `pr_app` + shepherd / status / approve-merge (`:1919-1924`, `:1927-1986`) | 74 |
      | `_docs.py` | `spec`, `prd`, `changelog` apps, `_skw_kit_root`…`_run_docs`, `doc-score`, `serve` (`:1807-1913`, `:1989-2070`) | 259 |
- [ ] **W6.2** **Registration order is observable.** `register_run_commands(app)` runs at
      `:76`, before the root callback at `:84-98`; every `add_typer` sits at a specific line
      (`wave` `:576`, `plan` `:1104`, graph/findings/rules/review/bench `:1231-1259`, `skw` `:1872`,
      spec/prd/changelog/pr `:1911-1924`). `tripll --help` lists groups in registration order.
      Preserve that order exactly; W1.4 asserts it.
- [ ] **W6.3** **`rewrite_run_inject_argv` stays in `main()`** (`:2073-2091`, called at `:2090`),
      **before** `app()` — it is argv preprocessing, not a Typer callback, which is the only reason
      `tripll run inject` works at all. Keep the `_rewrite_run_inject_argv` alias at `:58` resolving
      from `tripll.cli` (`tests/test_inject.py`, `tests/test_reconcile.py`).
- [ ] **W6.4** Keep `plan_app`'s callback `context_settings={"allow_interspersed_args": True}`
      (`:1107`) — `tripll plan <path> --write-manifest` depends on it.
- [ ] **W6.5** Keep `run-inject` and `run-reconcile-graph` registered **and hidden**
      (`_run.py:485-486`).
- [ ] **W6.6** Keep `_run_integration` (re-exported from `_shared` at `:46-48`, used by
      `tests/test_delivery_live_fixture.py:99`) and `_orchestrator_watch_lines` (`:296-316`, used by
      `tests/test_orchestrator_mode_smoke.py:116`) resolving from `tripll.cli`.
- [ ] **W6.7** **Mount `skw_legacy_app` only** (`:53`, `:1872`). It is a foreign Typer from
      `tripll/skw/cli.py`; do not copy any of its eight commands into `cli/`.
- [ ] **W6.8** `cli/__init__.py` retains the root `app` (`:64-74`), the root callback (`:84-98`),
      the `register_*` calls, the `skw` mount, the back-compat aliases and `main()`.
      **Target: under 300 lines.**
- [ ] **W6.9** **Commit + push** (`refactor(cli): split command groups behind registrars`).

**Acceptance:**

```bash
make test                                              # green
wc -l src/tripll/cli/__init__.py                       # < 300
for f in src/tripll/cli/*.py; do wc -l "$f"; done       # each < 1000
git diff main...HEAD --name-only -- src/tripll | grep -v '^src/tripll/cli/' | wc -l   # 0
git diff main...HEAD --name-only -- tests | wc -l                                     # 0
# the inventory and the ORDER are unchanged (W1.4):
make test -- -k "module_facades or cli" -q             # green
tripll --help                                          # same groups, same order as baseline
# every command still resolves, hidden ones included:
for c in setup doctor init new status list-runs pause resume approve delete-run reset-run \
         pre0-interview validate validate-plan calibrate serve doc-score; do
  tripll $c --help >/dev/null 2>&1 || echo "MISSING: $c"; done
for g in wave plan graph findings rules review bench pr spec prd changelog skw; do
  tripll $g --help >/dev/null 2>&1 || echo "MISSING GROUP: $g"; done
tripll run-inject --help >/dev/null 2>&1 || echo "MISSING: run-inject (hidden)"
# argv preprocessing still in main, not in a callback:
grep -n 'rewrite_run_inject_argv' src/tripll/cli/__init__.py    # inside main()
python -c "
import tripll.cli as c
assert c.main.__module__ == 'tripll.cli'
assert c._rewrite_run_inject_argv and c._run_integration and c._orchestrator_watch_lines
print('cli surface intact')"
grep -c 'allow_interspersed_args' src/tripll/cli/_plan.py       # >= 1
# no skw duplication:
grep -c 'pipeline-diagram\|agent-run' src/tripll/cli/*.py       # 0
```

---

## Wave W7 — `api/app.py` → factory over routers, models, deps

**Findings:** GOD-03 · **Decisions:** R33 · **Depends:** W6

The one structural change in the plan: 28 handlers currently nested inside `create_app`
(`api/app.py:330-1460`) become `APIRouter` handlers that read state off the request. Nine `api/_*.py`
modules already exist — extract what is left, re-extract none of them.

- [ ] **W7.1** `src/tripll/api/models.py` — the 15 Pydantic models (`:130-322`) and
      `_slug_profile_id` (`:103-122`). `RunDetail` / `RunSummary` already live in `api/_runs.py` —
      leave them there.
- [ ] **W7.2** `src/tripll/api/deps.py` — the nine module helpers (`:1468-1626`):
      `_resolve_runs_root`, `_tripll_argv`, `_spawn_tripll`, `_assert_run_exists`, `_read_pid`,
      `_infer_task_id`, `_event_payload`, `_event_out`, `_read_config`.
- [ ] **W7.3** **`api/ui/router.py:79` imports `_read_config`, `_slug_profile_id` and
      `_tripll_argv` out of `api.app`, and `tests/test_api.py:844,864` imports
      `_resolve_runs_root`.** All four must still resolve from `tripll.api.app` after this wave.
      This is production coupling, not a test convenience — W8 is blocked on it.
- [ ] **W7.4** `src/tripll/api/routes/` — one `APIRouter` per group:
      `agents.py` (`:391-564`, 5 routes), `runs.py` (`:570-1078`, run CRUD + HITL + pause + inject
      + reconcile + the 3 PR routes), `waves.py` (`:1084-1275`, 4 routes),
      `events.py` (`:1281-1385`, poll + SSE), `config.py` (`/health` `:391-394`, config `:1391-1424`,
      backends `:1430-1458`).
- [ ] **W7.5** **Handlers read `request.app.state.runs_root`**, set at `:359-361`. They currently
      close over the inner `app`; that closure is the reason none of them is importable today.
- [ ] **W7.6** **Wiring order is behaviour.** Preserve: `app.mount("/static", …)` and
      `app.include_router(make_ui_router())` (`:370-371`), then
      `register_html_exception_handlers(app)` (`:373-375`), then the `csrf_cookie_middleware`
      HTTP middleware (`:379-385`, `apply_csrf_cookie` + `apply_auth_cookie`).
- [ ] **W7.7** **Auth is unchanged.** `Depends(require_auth)` on every `/api/*` route, and
      `stream_events` (`:1307-1385`) keeps accepting `?token=` because browser `EventSource`
      cannot set headers. Keep the `TRIPLL_SSE_POLL` env read and `Last-Event-ID` handling.
- [ ] **W7.8** **No module-level `app` singleton.** Tests call `create_app()`
      (`tests/test_api.py`, `test_ui.py`, `test_ui_auth.py`). Keep `put_config`'s in-process
      `os.environ` mutation (`:1418-1423`) and `launch_run`'s placeholder-`run_id` contract
      (`:646-656`) exactly as they are — both are documented behaviour clients depend on.
- [ ] **W7.9** **Do not edit `src/tripll/api/ui/`.** That is W8.
- [ ] **W7.10** **Commit + push** (`refactor(api): split routers, models and deps behind the app factory`).

**Acceptance:**

```bash
make test                                              # green
wc -l src/tripll/api/app.py                            # < 300
for f in src/tripll/api/*.py src/tripll/api/routes/*.py; do wc -l "$f"; done   # each < 1000
git diff main...HEAD --name-only | grep '^src/tripll/api/ui/' | wc -l          # 0 — W8's file
git diff main...HEAD --name-only -- tests | wc -l                              # 0
# every route survived, method and path identical (W1.5):
make test -- -k "api or ui" -q                         # green
python -c "
from tripll.api.app import create_app
r = sorted((sorted(x.methods)[0], x.path) for x in create_app().routes if hasattr(x, 'methods'))
print(len(r))                                          # matches the W1.5 snapshot
assert sum(1 for m, p in r if p.startswith('/api/')) == 28, r"
# the names ui/router.py and tests reach for still resolve:
python -c "
from tripll.api.app import _read_config, _slug_profile_id, _tripll_argv, _resolve_runs_root
print('api.app surface intact')"
# no singleton; state, not closure:
grep -cE '^app\s*=' src/tripll/api/app.py              # 0
grep -c 'request.app.state' src/tripll/api/routes/*.py # >= 1 per module
# wiring order preserved:
grep -n 'mount\|include_router\|register_html_exception_handlers\|middleware' src/tripll/api/app.py
# auth unchanged:
grep -c 'require_auth' src/tripll/api/routes/*.py      # >= 1 per module
grep -c 'token' src/tripll/api/routes/events.py        # >= 1 — EventSource path
```

---

## Wave W8 — `api/ui/router.py` → dashboard route modules

**Findings:** GOD-04 · **Decisions:** R33 · **Depends:** W7

- [ ] **W8.1** `src/tripll/api/ui/_routes_runs.py` — `dashboard_home` (`router.py:162`),
      `launch_run_form` (`:224`), `run_detail` (`:453`), `pr_approve_merge_form` (`:490`),
      `inject_run_form` (`:517`).
- [ ] **W8.2** `src/tripll/api/ui/_routes_agents.py` — the five agent pages (`:286-392`) and the
      two settings routes (`:420-430`).
- [ ] **W8.3** `src/tripll/api/ui/_routes_fragments.py` — the htmx fragments: timeline (`:568`),
      wave log (`:587`), log append (`:673`), log full page (`:711`), waves table (`:754`),
      worktree (`:771`), tasks (`:785`), batch timeline (`:799`), report (`:812`), orchestrator
      (`:832`).
- [ ] **W8.4** **`make_ui_router()` still returns exactly one `APIRouter`** with
      `include_in_schema=False` (`router.py:139-154`), because `create_app` calls
      `app.include_router(make_ui_router())` once (`api/app.py:371`) and W7's contract forbids
      editing that line. Sub-modules contribute routers that `make_ui_router` includes; they are not
      returned separately.
- [ ] **W8.5** **Every dashboard URL is unchanged** — these are bookmarked and htmx-referenced from
      templates. A changed path is a broken dashboard with a green test suite.
- [ ] **W8.6** Handlers keep reading `request.app.state.runs_root`, and the fragment routes keep
      returning the **same template names**. Do not move `api/ui/templates/` or
      `api/ui/static/`.
- [ ] **W8.7** `router.py` retains `make_ui_router`, the shared imports and the
      `include_router` calls. **Target: under 1,000 lines** — the limit, since this file is
      1,470 today and three modules take it comfortably under.
- [ ] **W8.8** Update `docs/design-note.md`'s module map. **Commit + push**
      (`refactor(api): split dashboard routes out of the ui router`).

**Acceptance:**

```bash
make test                                              # green
wc -l src/tripll/api/ui/router.py                      # < 1000
for f in src/tripll/api/ui/*.py; do wc -l "$f"; done    # each < 1000
git diff main...HEAD --name-only | grep '^src/tripll/api/app.py' | wc -l    # 0 — W7's file
git diff main...HEAD --name-only -- tests | wc -l                           # 0
# one router, still hidden from the schema:
python -c "
from tripll.api.ui.router import make_ui_router
from fastapi import APIRouter
r = make_ui_router()
assert isinstance(r, APIRouter)
assert all(getattr(x, 'include_in_schema', False) is False for x in r.routes)
print(len(r.routes), 'ui routes')"                     # matches the W1.5 snapshot
# every dashboard URL survived (W1.5):
make test -- -k "ui or api_ui or ui_auth" -q           # green
python -c "
from tripll.api.app import create_app
paths = {x.path for x in create_app().routes if hasattr(x, 'methods')}
for p in ('/', '/agents', '/settings', '/runs/{run_id}'):
    assert p in paths, p
print('dashboard paths intact')"
# assets did not move:
git diff main...HEAD --name-only | grep -c 'api/ui/templates\|api/ui/static'   # 0
```

---

## Final wave — the module-size gate, sweep, full gate

- [ ] **F.1** *(GOD-06, R39)* `scripts/check_module_size.py` — fail when any `src/tripll/**/*.py`
      outside the allowlist exceeds **1,000 lines**, printing **path and line count** per
      violation. Allowlist: **exactly** `src/tripll/inject.py` and `src/tripll/skw/render.py`, each
      with a comment naming why (over the limit, **not named in #16**, tracked separately).
- [ ] **F.2** `make module-size-check`, wired into `Makefile:346`'s `CI_STEPS` and into
      `scripts/ci_lib.py:44`'s `PATH_RULES` keyed on `src/tripll/**`. A gate that is not in
      `CI_STEPS` is a script.
- [ ] **F.3** **Prove the gate bites.** Append 1,100 lines of comment to a small module and confirm
      `make module-size-check` exits non-zero; restore. A gate that always exits 0 is decoration
      (the `doctor` lesson).
- [ ] **F.4** test-creator: drop the `xfail` from `tests/test_module_size.py` and the `__all__`
      completeness test; update `docs/test-plans/god-module-and-ci-posture.md`.
- [ ] **F.5** File the follow-up issue for `inject.py` and `skw/render.py`, reference it in the
      allowlist comments, and record the number in *Success criteria*. An unrecorded issue is an
      unfiled one.
- [ ] **F.6** `make ci-resume` until green, then **run the full suite twice consecutively**.
- [ ] **F.7** **Confirm a green GitHub Actions run on the branch head** — not a local pass.
- [ ] **F.8** Re-run this plan's own spot checks; each must invert (see *Success criteria*).
- [ ] **F.9** Change summary table (Wave | Headline | Provider/model | sha | CI run | Parked), and
      declare every parked wave explicitly. If ≥3 are parked, **stop here**.
- [ ] **F.10** `CLAUDE.md` command table gains `make module-size-check`. **Commit + push**
      (`chore: enforce the 1k module rule and finalize the extraction program`).
- [ ] **F.11** *(R40)* **Mark the PR ready for review** (`gh pr ready`) and refresh its body: the
      per-wave sha table, the CI run id, and the `Closes #16` / `Closes #59` keywords intact. Nine
      waves are done, so the draft state has stopped being true.
- [ ] **F.12** *(R40)* **Final edit of both rolling status comments** — every wave sha, every
      before/after line count, the CI run id, and the PR now ready. Both still say **not merged**,
      because they are not. Both issues stay **open**.

**Acceptance:**

```bash
make module-size-check                                 # exit 0
make ci-resume && make ci-resume                       # green twice
# the gate bites:
python - <<'PY'
import pathlib
p = pathlib.Path('src/tripll/repo_root.py')
p.write_text(p.read_text() + '\n'.join('# pad' for _ in range(1100)) + '\n')
PY
! make module-size-check; echo "caught=$?"
git restore src/tripll/repo_root.py
# the gate is wired, not just present:
grep -c 'module-size-check' Makefile                   # >= 2 (target + CI_STEPS)
grep -c 'module_size\|module-size' scripts/ci_lib.py   # >= 1
# the allowlist is exactly two entries, each explained:
grep -c 'inject.py\|render.py' scripts/check_module_size.py       # 2
grep -c '#' scripts/check_module_size.py                          # comments present
# the plan's central claim, inverted:
find src/tripll -name '*.py' -exec wc -l {} + | sort -rn | awk '$1 > 1000 && $2 != "total"'
# expect exactly 2 rows: inject.py and skw/render.py
grep -rn 'xfail' tests/ | grep -c 'green after W\|green after Final'   # 0
gh run list --workflow=CI --branch wave/god-module-and-ci-posture --limit 1 --json conclusion
# the PR is ready and still closes both issues (F.11):
gh pr view --repo sevn-bot/tripll --json isDraft,body \
  --jq '{draft:.isDraft, closes:(.body|[scan("[Cc]loses #[0-9]+")])}'  # draft:false, both listed
# both issues reported, both still OPEN, one rolling comment each (F.12, R40):
for n in 16 59; do
  gh issue view $n --repo sevn-bot/tripll --json state,comments \
    --jq "\"#$n \(.state) rolling=\([.comments[] | select(.body|startswith(\"## Status — wave plan\"))]|length)\""
done                                                    # each: OPEN rolling=1
gh issue view 16 --repo sevn-bot/tripll --json comments \
  --jq '.comments[] | select(.body|startswith("## Status — wave plan")) | .body' \
  | grep -c 'not merged'                                # >= 1 — still honest
```

### Change summary

| Wave | Headline | Provider / model | sha | CI run | Parked |
|------|----------|------------------|-----|--------|--------|
| W0 | Baseline, ADRs 013 + 018, contract pin | `cursor_local` claude-opus-5 | — | — | — |
| W1 | Characterization suite + test plan | `cursor_local` auto | — | — | — |
| W2 | mergeCraft posture + topology-proof pin gate | `cursor_local` auto | — | — | — |
| W3 | `ledger.py` façade + schema / store / query | `cursor_local` auto | — | — | — |
| W4 | `engine.py` leaf seams | `cursor_local` auto | — | — | — |
| W5 | `engine.py` core seams, under 1k | `cursor_local` auto | — | — | — |
| W6 | `cli/` registrars, 11 modules | `cursor_local` auto | — | — | — |
| W7 | `api/` routers, models, deps | `cursor_local` auto | — | — | — |
| W8 | dashboard route modules | `cursor_local` auto | — | — | — |
| Final | `make module-size-check`, sweep, ci-resume×2 | `cursor_local` claude-opus-5 | — | — | — |

---

## Thermos gate

- [ ] **T.1** **Contract-tampering audit — before any code review.** Work only from the contract
      (`docs/plans/god-module-and-ci-posture.md`), the Re-entry block, and the diff.

      ```bash
      shasum -a 256 docs/plans/god-module-and-ci-posture.md   # must match the W0.5 value
      git diff main...HEAD -- tests/                          # read every deletion and weakening
      grep -rn 'xfail' tests/ | grep 'green after'             # any left whose wave is [x] is tampering
      git diff main...HEAD -- tests/ | grep '^-' | grep -i 'assert'
      ```

- [ ] **T.2** **The refactor-integrity audit — specific to this plan.** Four failure modes are
      unique to it, and **none of them is visible in a normal review** because the diff is mostly
      moved lines:

      ```bash
      # (a) a caller was edited to accommodate an incomplete facade — R33's failure mode
      git diff main...HEAD --name-only -- src/tripll \
        | grep -vE '^src/tripll/(engine|ledger)' \
        | grep -vE '^src/tripll/(cli|api)/' \
        | grep -vE '^src/tripll/api/routes/'          # expect empty
      # (b) a lazy import got hoisted — fails as an ImportError at CLI startup, not in review
      git diff main...HEAD | grep -nE '^\+(from|import) .*(graphstore|tripll\.inject|l1_outer)'
      python -c "import tripll.cli, tripll.api.app, tripll.engine, tripll.ledger; print('imports ok')"
      # (c) a "moved" body was quietly edited — the change nobody sees inside a move
      git diff main...HEAD -M -C --stat -- src/tripll
      git diff main...HEAD -M -C -- src/tripll | grep -cE '^\+' # compare against the deletion count
      # (d) _execute_node_body was phased instead of moved (R38)
      grep -rc 'def _execute_node_body' src/tripll/                # exactly 1, in engine_node_dispatch
      ```

      An edited caller or a hoisted import is a **finding**, not a judgement call.

- [ ] **T.3** **Behaviour-parity spot check, against `main` and not against the suite.** Boot the
      dashboard on both revisions and diff the surfaces the tests only sample:

      ```bash
      python -c "
      from tripll.api.app import create_app
      for r in sorted((sorted(x.methods)[0], x.path) for x in create_app().routes if hasattr(x,'methods')):
          print(*r)" > /tmp/routes-head.txt
      git stash list >/dev/null; git worktree add /tmp/tripll-main main >/dev/null
      (cd /tmp/tripll-main && make setup >/dev/null && python -c "
      from tripll.api.app import create_app
      for r in sorted((sorted(x.methods)[0], x.path) for x in create_app().routes if hasattr(x,'methods')):
          print(*r)") > /tmp/routes-main.txt
      diff /tmp/routes-main.txt /tmp/routes-head.txt && echo "routes identical"
      (cd /tmp/tripll-main && tripll --help) > /tmp/help-main.txt
      tripll --help > /tmp/help-head.txt
      diff /tmp/help-main.txt /tmp/help-head.txt && echo "cli surface identical"
      git worktree remove /tmp/tripll-main
      ```

      **`diff` empty is the acceptance.** This is the check that catches a lost route or a reordered
      `--help`, and it is the only one that does not depend on W1 having thought of the case.

- [ ] **T.4** Run the branch review agents on `git diff main...HEAD`. Note for the reviewer: the
      diff is **large and mostly moves**. Use `git diff -M -C` and review the **non-move residue**
      first — that is where any real change is hiding.

- [ ] **T.5** Fix every finding above `low`; **commit + push each fix pass**; re-run until clean;
      `make ci-resume` after the last pass.

- [ ] **T.6** *(R40)* **The final evidence comment — a new comment, not an edit.** The rolling
      status comment records *state*; this one records the *audit*, so it is the second and last
      new comment on each issue. On [#16](https://github.com/sevn-bot/tripll/issues/16): the
      per-module before/after table and every wave sha, in the same shape the maintainer used for
      #47 and #51 so the issue reads as one continuous history. On
      [#59](https://github.com/sevn-bot/tripll/issues/59): the recorded decision, the ADR 018 link,
      and each of its four acceptance boxes with the evidence that ticks it.

      ```bash
      gh issue comment 16 --repo sevn-bot/tripll --body-file ignorelocal/github-issues/final-16.md
      gh issue comment 59 --repo sevn-bot/tripll --body-file ignorelocal/github-issues/final-59.md
      ```

      **Do not close either issue here, and do not close them by hand afterwards.** The `Closes #16`
      / `Closes #59` keywords in the PR body (W0.8) close them when the human merges — one event,
      one actor, and the close is linked to the merge commit rather than floating free. A closed
      issue on an unmerged branch is a lie, and a hand-close after the merge loses the link.

- [ ] **T.7** **Merge request — always human** (`auto_acceptable = false`). tripll parks; a person
      merges (D15). State plainly in the request that merging will auto-close #16 and #59, so the
      merger knows what the button does.

- [ ] **T.8** **After the merge — verify, do not act.** Confirm both issues closed *via the merge*
      and that each shows the merge as the closing event. If either is still open, the PR body lost
      its keyword: say so and let the operator close it. Do not close it yourself — that would hide
      a defect in the W0.8 wiring that will recur on the next plan.

      ```bash
      for n in 16 59; do
        gh issue view $n --repo sevn-bot/tripll --json state,stateReason,closedByPullRequestsReferences \
          --jq "\"#$n \(.state) \(.stateReason) by=\([.closedByPullRequestsReferences[]?.number])\""
      done                                        # each: CLOSED COMPLETED by=[<PR>]
      ```

---

## Success criteria (acceptance)

Issue number from F.5 — **fill this in; an unrecorded issue is an unfiled one:**
`inject.py` + `skw/render.py` module size `#___`.

- [ ] **Every module named in #16 is under 1,000 lines**: `engine.py`, `cli/__init__.py`,
      `api/app.py`, `api/ui/router.py`, `ledger.py` — and so is every module extracted from them
- [ ] `find src/tripll -name '*.py' | xargs wc -l | awk '$1>1000'` returns **exactly two** rows:
      `inject.py` and `skw/render.py`, both allowlisted with a comment and a tracking issue
- [ ] **No caller of any extracted module was edited.** `git diff main...HEAD --name-only -- src/tripll`
      contains only the extracted modules and their new siblings
- [ ] **`tests/` was edited only by W1 and F.4.** No impl wave touched it
- [ ] Every name that resolved from `tripll.engine`, `tripll.ledger`, `tripll.cli` or
      `tripll.api.app` still resolves **to the same object** (`is`, not `==`), including every
      private name in the table: `_resolve_grep_brief`, `_MAX_NO_PROGRESS_DISPATCHES`,
      `_run_integration`, `_orchestrator_watch_lines`, `_rewrite_run_inject_argv`,
      `_resolve_runs_root`, `_read_config`, `_slug_profile_id`, `_tripll_argv`
- [ ] `ledger.py` has an `__all__` covering the **full** external name set — the five names its
      prose `Exports:` list was missing are in it
- [ ] `tripll --help` is **byte-identical** to `main`: same commands, same groups, **same order**
- [ ] `create_app()`'s route table is **byte-identical** to `main`: 28 JSON routes, 22 dashboard
      routes, same methods, same paths, `include_in_schema=False` still on the UI router
- [ ] Every lazy import is still function-local — `graphstore.task_sync` in the ledger writes,
      `inject.reconcile_run_graph` and `loops.l1_outer` in `engine`
- [ ] `_execute_node_body` exists exactly once, in `engine_node_dispatch.py`, **not** split into
      phase functions (R38)
- [ ] No `ledger_*` module imports `engine`; no `engine_*` module imports `cli` or `api`
- [ ] `.github/workflows/mergecraft.yml` still triggers on `pull_request` and carries a comment
      stating the decision and that the review **must stay non-required** (R35)
- [ ] `check_mergecraft_ref_parity.py` reads the pin from the **default-branch ref**; a working-tree
      edit alone no longer changes its verdict; an unreachable ref **warns and exits 0** offline and
      **fails** under `CI` (R36)
- [ ] Base-branch coverage and the upstream-`wait-for-ci` deferral are both written down (CI-03, R37)
- [ ] The operator runbook states the bump order: default branch first, then `MERGECRAFT_REF`
- [ ] `make module-size-check` fails on a planted oversized module and passes on a clean tree, and
      is wired into both `CI_STEPS` and `PATH_RULES` (R39)
- [ ] `make ci-resume` green twice, and a **green GitHub Actions run on the branch head**
- [ ] **Each issue carries exactly one rolling status comment**, edited in place at every wave
      close-out, naming the branch, the PR, the last wave, the last sha and its CI run (R40)
- [ ] Every "Delivered" line in a status comment carries a **real before/after number and a real
      sha** — no claim without evidence
- [ ] The PR opened **draft** at W0 with `Closes #16` / `Closes #59` in its body, and flipped to
      **ready** at Final
- [ ] #16 and #59 each carry a final evidence comment, and both are **closed by the merge** — not by
      a wave, not by hand, and never while the branch is unmerged

## Traceability

### Issue → wave → finding

| Issue | Wave | Findings closed |
|-------|------|-----------------|
| [#59](https://github.com/sevn-bot/tripll/issues/59) mergeCraft CI posture | W2 | CI-01, CI-02, CI-03, CI-04 |
| [#16](https://github.com/sevn-bot/tripll/issues/16) `ledger.py` | W3 | GOD-05 |
| [#16](https://github.com/sevn-bot/tripll/issues/16) `engine.py` | W4, W5 | GOD-01 |
| [#16](https://github.com/sevn-bot/tripll/issues/16) `cli/__init__.py` | W6 | GOD-02 |
| [#16](https://github.com/sevn-bot/tripll/issues/16) `api/app.py` | W7 | GOD-03 |
| [#16](https://github.com/sevn-bot/tripll/issues/16) `api/ui/router.py` | W8 | GOD-04 |
| The 1k rule itself | Final | GOD-06 |

### Precedent → decision

| Source | Taken as | Decision |
|--------|----------|----------|
| `engine_scheduling.py` + `tests/test_engine_scheduling.py:34-41` (PR #47) | façade re-export proven by identity assertion | R33 |
| `cli/_run.py:481-486` + `cli/_shared.py` (PR #51) | `register_*_commands` registrar pattern | R33 |
| #16's own "characterization-test prerequisite" | the suite is green **before** the refactor | R34 |
| #59 §1 (recommends option (a)) | keep `pull_request`, keep the review non-required | R35 |
| #59 §2 (`git show {ref}:…` sketch) | read the pin from the default-branch ref | R36 |
| #59 §4 (upstream hardened workflow) | adopt when it lands; do not hand-roll | R37 |
| `docs/skw/problem-types.md:11` (`oversized_file`) | a prose limit becomes a gate | R39 |
| ai-layer plan R29 (executable beats prose) | same reasoning, applied to module size | R39 |
| #16's own `## Partial progress` comments on #47 and #51 | the status-comment shape, and the evidence that a silent multi-PR tracker is unreadable | R40 |
| D15 (tripll never auto-merges) | the issues close on the human merge, via PR keywords | R40 |

---

## Baseline notes

- **HEAD at W0 dispatch:** `2e4a8f2` on `wave/god-module-and-ci-posture` (based on `main`).
  `alexhawat-readme-and-oss-audit` at `ee4e247` is **2 commits ahead of `main`, not merged**.
- **Oversized modules at `2e4a8f2`** (`src/tripll`, `*.py`, > 1000 lines): `engine.py` 3603 ·
  `cli/__init__.py` 2095 · `api/app.py` 1626 · `api/ui/router.py` 1470 · `ledger.py` 1394 ·
  `inject.py` 1284 · `skw/render.py` 1161. **Five are in scope; the last two are not** (not named
  in #16).
- **Extraction precedent, both merged 2026-07-29:** PR #47 (`engine_scheduling.py`, 177 lines,
  `engine.py` 3694 → 3492) and PR #51 (`cli/_run.py` 490 + `cli/_shared.py` 349, `cli.py` → `cli/`).
- **Open issues deliberately *not* in this plan:** [#53](https://github.com/sevn-bot/tripll/issues/53)
  (prediction-driven routing), [#54](https://github.com/sevn-bot/tripll/issues/54) (Jira/Confluence
  tracker), [#55](https://github.com/sevn-bot/tripll/issues/55) (rule inheritance and conflict
  resolution). All three are **out-of-scope trackers filed by W0.4 of the ai-layer compounding
  plan**, and two are locked by ADRs: #53 by ADR 015 / R28 (calibration is advisory, permanently),
  #54 by `CLAUDE.md`'s standalone rule and ADR 016 / R30 (the protocol only, never a vendor SDK).
  **Implementing them would reverse a decision, not close a defect.** They stay open as backlog.
- **ADR numbering:** `013` has been free since the L1 plan's onboarding ADR never landed; this plan
  claims `013` and `018` rather than opening a permanent gap at 013.
