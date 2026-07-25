# reviewer — branch review turn

Run the configured review pipeline on the branch diff and write a structured verdict file.
This turn is **review-only** — do not edit code, tests, or wave-files; do not run verify targets.

## Step 1 — Run the review plugin

Invoke the plugin named below (default pipeline: **thermo** — the thermo-nuclear code-quality
review subagent). Scope:

- Repository workspace root (parent of this kit directory).
- Diff: `git diff <base>...<branch>` using **Base** and **Branch** from the injected block below.

Audit maintainability and structure: oversized files, god-objects, spaghetti, duplication,
leaky abstractions, weak typing, dead/noise code, missed code-judo. Return an overall verdict
plus findings sorted by severity.

Wait for the complete plugin report before continuing.

## Step 2 — Gate on verdict

- **Clean pass** — plugin verdict is `ship`, `pass`, `proceed`, or `approve` with no required
  changes: set `verdict: pass`, `findings: []`. **Do not** write a wave-file.
- **Changes required** — any other verdict or findings that require work: set
  `verdict: changes_required` and populate `findings[]`.

## Step 3 — Write review-result.json

Write JSON to **Verdict path** below:

```json
{
  "verdict": "pass",
  "findings": [
    {
      "id": "finding-1",
      "severity": "high",
      "file": "src/example/module.py",
      "summary": "One-line description",
      "evidence": "module.py:120-145 or SymbolName"
    }
  ]
}
```

Rules:

- Every finding must include `id`, `severity`, `file`, `summary`, and `evidence`.
- Evidence must come from the plugin report — do not fabricate.
- In-repo paths are repo-root-relative. Never parent-directory refs, dot-slash refs, or a leading slash.

## Self-check

- [ ] Review plugin ran on the branch diff.
- [ ] `review-result.json` written to the verdict path with valid JSON.
- [ ] `verdict: pass` only when no required changes remain.
- [ ] No code edited, no tests edited, no wave-file written, nothing committed.

<!-- INJECTED -->

Plan: {{PLAN_PATH}}
Title: {{TITLE}} (slug: {{SLUG}})
Base: {{BASE}} | Branch: {{BRANCH}}
Output: {{OUTPUT_DIR}}
Verdict path: {{VERDICT_PATH}}
Max turns: {{MAX_TURNS}}

Review agent: {{REVIEW_AGENT}}
Review prompt: {{REVIEW_PROMPT}}
Plugin: {{REVIEW_INPUT_PLUGIN}}

Wave context: {{WAVE_ID}} — {{WAVE_TITLE}}
Verify (informational): {{WAVE_VERIFY}}
