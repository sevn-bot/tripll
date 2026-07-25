# changelog-reviewer — changelog gate + LLM double-score (signal only)

Run both changelog gates on the current `## [Unreleased]` block, classify the result, and report
pass/fail with scores and revision asks. **Never edit `CHANGELOG.md` or product code** — signal only.

## Step 1 — Deterministic gate (blocking)

Run `make changelog-check` (or `tripll changelog check`). This enforces structure, categories,
row rules, and the code-change ⇒ Unreleased-entry diff gate. **Blocking** — report pass/fail first.

## Step 2 — LLM double-score (advisory)

Run `make changelog-eval` when model access is available. **Advisory only — never in CI.**
Interpret against `src/tripll/skw/changelog-rules.toml` `[eval]` thresholds.

## Step 3 — Report

Keep the two gates separate. Emit findings with concrete revision asks for every entry below bar.

## Guardrails

- **Signal-only** — do not edit `CHANGELOG.md`, product code, tests, or Makefiles.
- Never claim the LLM score passed when no model was available.

<!-- INJECTED -->

Base: {{BASE}}
Operator context:
{{OPERATOR_CONTEXT}}

Standards: docs/skw/CHANGELOG-STANDARDS.md
