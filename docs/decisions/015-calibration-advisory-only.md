# ADR 015 — Calibration is advisory only (R28)

**Status:** Accepted (2026-07-29, Wave W0)
**Decisions:** R28 (predictions never steer routing)

## Context

External review surfaced predicted first-pass confidence as a useful operator signal. tripll's
ledger already records per-attempt outcomes (`attempt_n`, `outcome`, cost, env fingerprint), and
the ontology defines `Hypothesis`, `Experiment`, `Metric`, `PREDICTED`, and `REALIZED` — but
nothing in `src/` writes them (CAL-02).

The temptation is to feed predictions back into routing, model selection, or attempt budgets.
That closes a feedback loop that cannot be scored: a predictor steering the run it predicts has
no counterfactual, and a miscalibrated one would starve the waves that need the most attempts.

## Decision

1. **Emit predicted first-pass probability at compile time** as a `PREDICTED` Metric per wave,
   grouped under an `Experiment` per run, using existing ontology kinds — no new node types.

2. **Score predictions after the run** via `tripll calibrate`: read `ledger.attempts`, compute
   `attempts_to_green` and `first_attempt_pass_rate`, write `REALIZED` Metrics, and report a
   Brier score per predictor version.

3. **Advisory only, permanently.** Predicted probability may be displayed, logged, and scored.
   It may **never** change routing, model selection, attempt budget, or gate behaviour. W1 and W5
   assert byte-identical dispatch decisions with the predictor on and off.

4. **Uncalibrated is honest.** With fewer than N prior runs, report `"uncalibrated"` rather than
   a meaningless Brier score.

## Rejected

- **Prediction-driven routing** — cannot score a predictor against a counterfactual; miscalibration
  silently starves hard waves. Tracked as an out-of-scope issue for a separate program with its
  own evidence bar.
- **New ledger columns or schema migration** — `attempt_n` and `outcome` already exist per attempt.
- **Self-reported confidence without ledger scoring** — noise without the scoring loop tripll can
  close; the pack's `Confidence Score: #/10` alone is insufficient.

## Consequences

- W5 implements `src/tripll/calibrate/{predict,score}.py` and the `tripll calibrate` command.
- `grep -rn 'predict' src/tripll/engine.py src/tripll/adapters/` must stay empty on decision paths.
- `report.py` surfaces predicted vs actual per wave and the run's Brier score (or uncalibrated).
