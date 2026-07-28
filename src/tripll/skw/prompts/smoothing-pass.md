# smoothing-pass — post-gauntlet consistency

Minimal consistency pass after quality gauntlet rounds. Edit **wave targets only**.

## Verdict

Write JSON to `{{VERDICT_PATH}}`:

```json
{"verdict": "no_op", "summary": "artifact already consistent", "files_touched": []}
```

Leave changes staged; do not commit.

<!-- INJECTED -->

Wave: {{WAVE_ID}}
Owned paths: {{OWNED_PATHS}}
Worktree: {{WORKTREE_PATH}}
Quality rounds completed: {{QUALITY_ROUNDS}}
Reference (optional): {{REFERENCE_PATH}}
