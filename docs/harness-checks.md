# Harness checks — five failures a bigger model cannot fix

Code factory L1 treats agent failures as **harness** problems first. The design cites
[@nykdotdev — *How to Actually Debug Agent Failures*](https://x.com/nykdotdev/status/2079510947270631538)
and implements the checks in `src/tripll/harness/`.

## The five harness failures

| # | Failure | Symptom | L1 mitigation |
|---|---------|---------|---------------|
| 1 | **Stale handoff** | Agent acts on outdated branch/state | `serve/handoff.py` — 10-field block; `harness/reconcile.py` pre-commit reconciliation |
| 2 | **Wrong environment** | Same prompt, different outcomes | `harness/fingerprint.py` — 13-field `EnvFingerprint` per attempt |
| 3 | **Tool boundary leak** | Agent edits forbidden paths | `harness/boundary.py` — 8-layer scope enforcement |
| 4 | **Self-reported done** | Agent claims success without evidence | `harness/contracts.py` — outcome contracts; `unverified` when graders cannot run |
| 5 | **Duplicate side effects** | Two PRs / double push on retry | `loops/idempotency.py` — decide/commit split, idempotency keys before external actions |

## Four gates (before dispatch)

Every wave dispatch passes:

1. **Handoff reconciliation** — live git state matches the handoff block.
2. **Environment fingerprint** — recorded on the attempt row for L2 telemetry seams.
3. **Tool boundary** — owned vs forbidden paths from the compiled plan.
4. **Outcome contract** — wave declares graders; verifier runs in an **isolated** context (D17).

## Outcome contracts and `unverified`

Wave completion is gated by `harness/contracts.py`, not agent self-report:

- **`passed`** — all required graders green with evidence.
- **`failed`** — at least one grader failed with evidence.
- **`unverified`** — a required grader could not run (missing tool, sandbox unavailable).
  The wave state becomes `unverified` in the ledger; the run does **not** advance to `done`.

The isolated verifier (`wave-verifier`) never receives the implementer transcript.

## Quality gauntlet (D26–D28)

Optional inner loop for reference-driven polish before correctness verify. Declared in plan v3 via
`[waves.outcome.reference]` and `[waves.outcome.quality_gauntlet]`. `quality-critic` uses the same
isolation rules as D17; rounds are recorded as `Verdict`/`Finding` nodes and in
`runs/<run_id>/workbench.html`.

See [`docs/design/quality-gauntlet.md`](design/quality-gauntlet.md).

## Loop exits (§7.10)

Eight targeted exits live in `src/tripll/loops/exits.py`. Three are mandatory caps:

| Exit | Mechanism |
|------|-----------|
| 1 goal met | Outcome satisfied + CI green + `pullfrog-approval` success |
| 2 turn cap | `max_attempts=5` (impl waves), LangGraph `RetryPolicy` |
| 3 budget cap | `TRIPLL_COST_BUDGET_USD` |
| 4 wall clock | Per-wave `wall_clock_limit_s` + run deadline |
| 5 no progress | Three identical graph-delta hashes |
| 6 human interrupt | `pause-requested.md` / operator pause |
| 7 error threshold | Circuit breaker per `(agent, problem_type)` |
| 8 external event | PR merged/closed or source issue closed |

The dashboard **Exits** panel shows caps approaching their limits (§12).

## Ledger vs LangGraph checkpoint (D6)

| Store | Role |
|-------|------|
| **SQLite ledger** (`ledger.db`) | System of record — wave states, attempts, events, costs |
| **Task graph** (layer `task` in `.tripll/graph.db`) | Derived alongside the ledger; replaces `graph.json` over time |
| **LangGraph checkpoint** (`graph` extra) | Optional execution seam — `AsyncSqliteSaver`, `thread_id == run_id` |

Recovery: if a LangGraph checkpoint is lost, replay from the ledger. Checkpoints are derived,
not authoritative.

## Operator commands

```bash
tripll graph extract --repo .          # refresh Code KG
tripll findings sync --pr <n>            # ingest CI + review into Finding nodes
tripll pr shepherd <run-id>              # PR fix loop (stops at merge gate)
make check                               # lint + typecheck + about-site + test
```

See also: [`docs/design-note.md`](design-note.md) (state machine), [`docs/control-plane-design.md`](control-plane-design.md) (LangGraph seam §12).
