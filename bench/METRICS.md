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

L2/L3 runs may not modify this file, `bench/tasks/`, or `bench/review/` in the
same run that claims an improvement. Changes require a human gate.

---

## Review track metrics (#64 W4)

The Harbor review benchmark uses a **sibling metric set** in
`src/tripll/bench/review_metrics.py` — separate from the frozen nine
`METRIC_KEYS` above (D23). Baseline snapshots live in
`bench/baselines/review-v1.json`. Report **deltas** against that baseline;
absolute scores are expected to stay low (~30% coverage is strong).

| # | Metric | Unit | Definition |
|---|--------|------|------------|
| 1 | `review_coverage` | ratio | Share of baseline issues matched by submitted findings (same fingerprint / code path) |
| 2 | `review_precision` | ratio | Share of submitted findings that match a baseline issue |
| 3 | `review_f1` | ratio | Harmonic mean of coverage and precision (headline) |
| 4 | `review_coverage_context_dependent` | ratio | Coverage restricted to baseline issues with `requires_context_outside_diff: true` |
| 5 | `review_noise_rate` | ratio | Share of findings that miss the baseline or exceed the inline budget |
| 6 | `review_cost_per_task` | USD | Mean spend (tokens or USD) attributed per Harbor task attempt |

### D24 review corpus gate

`bench/review/baseline.jsonl`, emitted Harbor tasks under
`bench/review/<repo>-pr<N>/`, and `bench/baselines/review-v1.json` are frozen
once committed. A run may not edit the review corpus or baseline snapshot in
the same change that claims a review-track improvement. The nightly
`bench-review` runner (W11) surfaces F1 deltas; per-PR execution is forbidden.
