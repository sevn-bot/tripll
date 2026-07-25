# Frozen benchmark metrics (§9.4) — DO NOT EDIT during improvement runs (D24/P19).

This file defines the nine L2 metrics for the code-factory L1 benchmark suite.
`bench/tasks/` and this document are **frozen artifacts** once committed in W10.

## Metrics

| # | Metric | Unit | Definition |
|---|--------|------|------------|
| 1 | `first_attempt_pass_rate` | ratio | Share of sealed tasks whose outcome contract passes on attempt 1 |
| 2 | `attempts_to_green` | count | Mean attempts before outcome contract + verify green |
| 3 | `tokens_to_green` | tokens | Prompt tokens consumed before green (graph-packed brief path) |
| 4 | `wall_clock_to_green_s` | seconds | Wall clock from dispatch to green |
| 5 | `escalation_rate` | ratio | Runs ending in blocked/escalated state |
| 6 | `finding_density_per_kloc` | findings/KLOC | Open findings per thousand lines changed |
| 7 | `stale_finding_rate` | ratio | Findings whose `ABOUT` target has `valid_to_sha` set |
| 8 | `scope_breach_rate` | ratio | Attempts touching paths outside owned scope |
| 9 | `graph_brief_win_rate` | ratio | Share of tasks where graph-brief beats grep-brief on tokens-to-green (D23) |

## D23 primary comparison

Graph-packed briefs must beat grep briefs on **first-attempt pass rate** and
**tokens-to-green** on this frozen suite. The verdict is recorded in
`docs/graph-serving.md` after `tripll bench run`.

## Goodhart gate (D24)

L2/L3 runs may not modify this file or `bench/tasks/` in the same run that
claims an improvement. Changes require a human gate.
