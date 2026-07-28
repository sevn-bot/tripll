# quality-critic

> **Dispatch status:** **Engine spine shipped** — inner loop runs in `engine._run_quality_gauntlet`
> with harness orchestration (`harness/quality.py`); isolated `quality-critic` agent dispatch
> and LangGraph sub-graph remain follow-up.

Reference-driven critic for the quality gauntlet inner loop (design §11.17, D27).

| Field | Value |
|-------|-------|
| **class** | reviewing |
| **edits** | nothing |
| **inputs** | captured artifact(s), `[waves.outcome.reference]`, optional rubric; **no implementer transcript** |
| **outputs** | `Verdict` or `Finding` (`kind = quality`) with winner, largest gap, round number, evidence paths |
| **graph** | reads reference path + wave targets; writes `Verdict` linked `GRADED_BY` |
| **guardrails** | D17 isolation (fresh process/worktree); inspect real artifacts only — never builder summaries; **one gap per round**; blind A/B when `comparison = blind_ab` |
| **done** | stop condition from `reference.stop_when` satisfied, or exit fires (max rounds, sub-budget, no-progress) |

## Comparison modes

| `comparison` | Critic behaviour |
|--------------|------------------|
| `blind_ab` | Receive unlabeled A/B; pick better; if reference wins, state single largest gap |
| `side_by_side` | Same with labels |
| `rubric` | Score dimensions; pass when all ≥ threshold |

## Inherited harness

[`src/tripll/skw/agents/_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md)

## Agent definitions

| Surface | Path |
|---------|------|
| Operator docs (this file) | `docs/agents/quality-critic.md` |
| skw brief | [`src/tripll/skw/agents/quality-critic.md`](../../src/tripll/skw/agents/quality-critic.md) |
| Design | [`docs/design/quality-gauntlet.md`](../design/quality-gauntlet.md) |
