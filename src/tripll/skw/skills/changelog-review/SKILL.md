---
name: changelog-review
description: >-
  Review CHANGELOG.md `## [Unreleased]` entries: run the deterministic gate, then
  the advisory LLM double-score, and interpret both against thresholds. Use when
  asked to review, grade, or check the changelog, or to decide whether entries are
  release-ready. The LLM score is advisory and on-request, never CI.
user_invocable: true
---

# Changelog review (deterministic gate + LLM double-score)

Review the Unreleased entries in two passes: the **deterministic** structural /
diff gate (blocking, CI-run) first, then the **advisory** LLM double-score
(on-request, live model access). Report both to the user with concrete revision
asks for anything below bar. Never claim a gate passed unless you ran it.

**Standards:** `src/tripll/skw/CHANGELOG-STANDARDS.md`.

## When to use

- The user asks to review, grade, or check the changelog.
- Before finalising a branch or cutting a release.
- After the **changelog-author** skill drafted entries and you want a quality read.

## Workflow

1. **Deterministic gate first** — run `make changelog-check`. It enforces:
   - the six-category structure and `## [Unreleased]` block;
   - row rules (bullet `- `, sentence case, no trailing period, >= 12 chars,
     `(#123)` refs, backticks for code only);
   - the "code change under `src/sevn` / `scripts` ⇒ Unreleased entry" diff gate.

   If it fails, fix structure/rows (or advise a `changelog: skip` trailer for a
   no-user-impact diff) **before** spending model tokens on the LLM score.

2. **LLM double-score** — run `make changelog-eval` (or
   `uv run python -m skw.changelog_eval --repo .. --base origin/main --json` from
   `src/tripll/skw/`). This needs live model access; if none is configured it
   fails loudly — surface that message, do not treat it as a pass.

3. **Interpret the scores** against `changelog-rules.toml` `[eval]` thresholds
   (defaults: `structured_min = 7`, `unstructured_min = 7`):
   - **Structured** — every rubric dimension (`specificity`,
     `user_impact_clarity`, `category_correctness`, `diff_equivalence`) scored
     0–10 with a rationale. Pass = **all** dimensions `>= structured_min`.
   - **Unstructured** — one holistic 0–10 + prose. Pass = `>= unstructured_min`.
   - **Verdict** — PASS only when both pass. Report both scores and rationales.

4. **Give revision guidance** for any entry below bar, tied to the failing
   dimension:
   - low `specificity` → name the exact command / flag / path;
   - low `user_impact_clarity` → lead with the outcome, drop the mechanism;
   - low `category_correctness` → move to the right heading;
   - low `diff_equivalence` → align the wording with what the diff actually did.

## Reporting

- State which gates you actually ran. The deterministic result is blocking; the
  LLM score is **advisory and on-request — it is not a CI gate**. Say so.
- For a clean pass: one line ("both gates pass") plus the two scores.
- For failures: one finding per entry, `category → entry` with the failing
  dimension and a concrete rewrite. Show a suggested revised bullet.

## Voice

Concise, peer-to-peer, like the git-pr-review skill. One finding per entry. Hedge
taste, be direct on rule violations. Backtick commands, flags, and paths. No
severity labels or bundled verdict blocks inside per-entry findings.

## Do not

- Do not edit `CHANGELOG.md` yourself unless the user asks — report and suggest.
- Do not wire the LLM double-score into CI or any blocking gate.
- Do not claim the LLM eval passed when no model was available; report the loud
  failure instead.
