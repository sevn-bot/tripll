# wave-orchestrator

Multitask-style **coordinator** for tripll orchestrator-mode runs. Counterpart to **wave-runner** (implementer).

## Path convention

In-repo file references in wave plans, orchestrator prompts, and agent briefs must be
**repo-root-relative** (worktree root = repo root):

- Use `specs/…`, `prd/…`, `src/…`, `plan/…`, `wave-orchestrator/…`, `.cursor/agents/…`.
- **Never** use `../`, `./`, or a leading `/` for in-repo paths.
- External files outside the repo may keep **absolute** paths; tripll exposes their parent
  via `--add-dir` / workspace scope.
- Validate before dispatch: `tripll validate-plan <plan.md>`.

## Canonical invocation

```bash
make resume-run RUN=<id> PROVIDER=cursor_local MODEL=auto
make run-set SET=<set> PROVIDER=cursor_local MODEL=auto
```

`run`/`resume` honor `--provider` + `--model` end-to-end. Cursor-auto = `cursor_local` +
`--model auto`.

## Role-dispatch toggle

When effective (`--role-dispatch`, `TRIPLL_ROLE_DISPATCH=1`, plan
`OrchestratorConfig.role_dispatch`, or orchestrator mode implied): `role:test-author` →
`test-creator`, `role:impl` → `wave-runner`. Precedence: CLI > env > plan config >
orchestrator-implied.

## When to use

| Context | Trigger |
|---------|---------|
| **Cursor Multitask** | Paste `*-orchestrator-prompt.md` into an orchestrator session |
| **Headless review gate** | Engine sets `TRIPLL_ORCHESTRATOR_AGENT=1` after a `review_gate` wave (W4) |
| **Manual resume** | Operator pastes resume block from orchestrator prompt after approving a gate |

## Role split

| Agent | Responsibility |
|-------|----------------|
| **wave-orchestrator** | Serial wave order, status table, review gates, dispatch one sub-agent per wave, commit hygiene |
| **[test-creator](test-creator.md)** | Owns `tests/`; authors the full suite in **W1** (`role: test-author`), RED, against W0-locked contracts |
| **wave-runner** | Implement one wave's plan bullets (code, **not tests**), run verify, commit when policy requires; 5 attempts then escalate |

### Tests-first dispatch (design-note §9)

`W0 (gate) → W1 test-creator (RED suite) → impl waves (green) → Final`. The orchestrator dispatches
the `role: test-author` node to `OrchestratorConfig.agent_test` (default `test-creator`) and impl
nodes to `agent_wave`. `tests/` is forbidden to every non-test-author wave (engine `TEST_PATHS`
overlay). Impl waves get **5 attempts** then escalate; the orchestrator re-dispatches a **fresh
coding agent**, and only re-dispatches test-creator when a test itself is wrong.

The Python engine owns **deterministic** status formatting in detached runs (`orchestrator-status.md`, terminal `orchestrator:` log lines, dashboard panel). The LLM orchestrator agent is **not** required for every turn — only Multitask sessions and optional gate dispatch (D2).

## Agent definitions

| Surface | Path |
|---------|------|
| Cursor subagent | [`.cursor/agents/wave-orchestrator.md`](.cursor/agents/wave-orchestrator.md) |
| Operator docs (this file) | `wave-orchestrator/docs/agents/wave-orchestrator.md` |
| Prompt skeleton | [`wave-orchestrator/docs/prompts/orchestrator-prompt-template.md`](wave-orchestrator/docs/prompts/orchestrator-prompt-template.md) |

> **Duplication note:** Cursor subagent defs (`.cursor/agents/`) and operator docs
> (`wave-orchestrator/docs/agents/`) are intentionally mirrored — keep both in sync until a
> single-source consolidation lands.

## Read first

1. Input `*-orchestrator-prompt.md` — HARD RULES, wave order, verify/commit table, REPORTING FORMAT
2. Target `*-wave-plan.md` — locked decisions, execution graph, per-wave bullets
3. [`wave-orchestrator/docs/design-note.md`](wave-orchestrator/docs/design-note.md) §8 — OrchestratorConfig, `orchestrator-status.md` schema, turn types
4. [`.cursor/agents/wave-runner.md`](.cursor/agents/wave-runner.md) — subagent contract

## Orchestrator mode activation (D1)

Orchestrator mode is **opt-in**:

- Input dir contains `*-orchestrator-prompt.md`
- Wave plan or prompt declares `orchestrator_mode: serial` (default serial when prompt present)

Runs **without** the prompt behave as standard parallel/serial tripll (D14).

## Serial loop (Cursor Multitask)

```text
Bootstrap branch → W0 → [review gate] → W1 → … → Final
```

1. Create single integration branch from base (e.g. `test-pre`)
2. Dispatch **one** wave-runner per wave; wait for verify + commit + push
3. **STOP** at review gates (e.g. W0.8) until operator approves
4. Emit REPORTING FORMAT every turn (see below)

## REPORTING FORMAT

Every orchestrator turn outputs:

1. **Current wave** — just completed or next to dispatch
2. **Status table** — `Wave | Status | Branch | Commit | Evidence / blockers`
3. **Dispatched** — wave-runner task + branch (if dispatching)
4. **STOP / REVIEW gates** — only when active
5. **Next action** — one wave id or wait for approval

Golden reference: [`plan/tripll-dashboard-ui-orchestrator-prompt.md`](plan/tripll-dashboard-ui-orchestrator-prompt.md).

## Headless gate invocation (W4)

When the engine pauses at a review gate and `TRIPLL_ORCHESTRATOR_AGENT=1`:

```bash
# Engine calls dispatch_orchestrator_gate() — adapter invokes wave-orchestrator with condensed brief
# Example context: "W0.8 complete — present summary, STOP"
```

The gate agent:

- Summarises completed wave evidence
- Sets status **AWAITING REVIEW**
- Lists operator sign-off items
- Does **not** dispatch the next wave

Default in CI: `TRIPLL_ORCHESTRATOR_AGENT=0` (operator approves via CLI/dashboard).

## Per-wave policy (typical)

| Step | Command |
|------|---------|
| Verify (repo root) | `SEVN_CI_BASE=origin/test-pre make partial-ci` |
| Tripll gate | `make -C wave-orchestrator check` |
| Commit check | `make commit-msg-check MSG='…'` |
| Push | `git push -u origin <feature-branch>` |

Orchestrator prompt may override verify targets and commit subjects per wave.

## MODEL POLICY (D11)

Do **not** pass explicit `model` to wave-runner unless the orchestrator prompt table specifies one. Use Cursor **Auto** (omit `model` parameter). Headless `cursor_local` uses `MODEL=auto` when policy says auto.

## What orchestrator does NOT do

- Implement wave plan bullets (delegate to wave-runner)
- Run parallel wave-runners in serial orchestrator mode (D8)
- Replace the engine's deterministic `orchestrator-status.md` writer in headless runs
- Run full `make ci` per wave (use `partial-ci` unless operator overrides)

## Related docs

- Design: [`wave-orchestrator/docs/design-note.md`](wave-orchestrator/docs/design-note.md) §8
- Dashboard IA: [`wave-orchestrator/docs/control-plane-design.md`](wave-orchestrator/docs/control-plane-design.md) §11
- Plan: `plan/tripll-orchestrator-mode-wave-plan.md`
