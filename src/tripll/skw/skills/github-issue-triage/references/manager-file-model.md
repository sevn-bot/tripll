# github-issue-manager — file model

Operator-local artefacts under `.ignorelocal/waves/github-issues/` (gitignored via
`.ignorelocal/`). Bounded index + append-only daily logs replace the old single
rolling `github-issues-wave-plan.md`.

## Layout

```text
.ignorelocal/waves/github-issues/
  index.md              # open actionable issues only (upsert by #N)
  state.json            # GitHub-sourced anchor + nudge + weekly digest stamps
  YYYY-MM-DD.md         # append-only daily sweep log
  issue-<N>-brief.md    # optional per-issue brief → @wave-plan-author
```

Full wave plans (when an issue is large enough) still live as siblings under
`.ignorelocal/waves/<slug>-wave-plan.md`; the index row points at that path.

## `index.md`

Canonical list for other agents (wave-runner, wave-plan-executor). One section per
open actionable issue:

```markdown
### #21 — Use group and topic names in session folder paths
- Link: https://github.com/sevn-bot/sevn/issues/21
- Type / Priority / Component: enhancement / P2 / sessions
- Status: open
- Plan: .ignorelocal/waves/issue-21-session-folder-names-wave-plan.md
- [ ] Implement per plan; on completion comment + close #21 via gh.
```

### Merge / concurrency rules

| Operation | Behaviour |
| --- | --- |
| **Upsert `#N`** | Replace only that `### #N` section; leave other sections untouched |
| **Remove `#N`** | Drop the section when the issue closes in a successful sweep |
| **Human edits** | In-flight checkboxes / notes inside a section may be overwritten on upsert of the same `#N` — prefer putting long notes in the daily log or a dedicated wave plan |
| **Parallel runs** | Safe for distinct `#N` upserts; same-`#N` last writer wins |

Script: `scripts/issue_index.py upsert|remove|init-index`.

## `YYYY-MM-DD.md`

Append-only audit trail for one UTC calendar day. Each sweep appends a `## Sweep`
block (never rewrites earlier blocks). Contents typically include:

- Window (`since` → GitHub anchor candidate)
- Closed (with evidence)
- PR reconciliations (`fixed by #PR`)
- Newly triaged
- Duplicates linked
- Stale needs-info nudges
- Weekly digest (when due)
- Index add/remove summary

Script: `scripts/issue_index.py append-daily`.

## `state.json`

```json
{
  "repo": "sevn-bot/sevn",
  "last_checked_at": "2026-07-19T09:00:00Z",
  "last_weekly_digest": "2026-07-13",
  "nudge_timestamps": {
    "42": "2026-07-10T12:00:00Z"
  }
}
```

| Field | Meaning |
| --- | --- |
| `last_checked_at` | Max GitHub `updatedAt`/`createdAt` from the last **successful** fetch — not local wall clock |
| `last_weekly_digest` | `YYYY-MM-DD` of last digest append; cadence = 7 days |
| `nudge_timestamps` | Per-issue last needs-info nudge (skip re-nudge inside the window) |

Script: `scripts/manager_state.py` (atomic write via temp + `os.replace`).

Advance `last_checked_at` **only** after close + triage + index/daily writes succeed.

## First run

Missing `state.json` → `last_checked_at` is null → sweep full open queue (+ recent
closed for closure/PR passes). Create `index.md` via `init-index` if absent.
