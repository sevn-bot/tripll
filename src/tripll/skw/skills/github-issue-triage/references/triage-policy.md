# sevn.bot — GitHub issue triage policy

Reference for the **github-issue-triage** skill. Read before classifying, commenting, or
mutating issues on `sevn-bot/sevn` (or the host repo detected via `gh repo view`).

## Sources (read first)

| Doc | Purpose |
| --- | --- |
| [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) | Setup, CI, commits, PR policy |
| [`SECURITY.md`](../../../../SECURITY.md) | **No public issues** for vulnerabilities |
| [`CHANGELOG.md`](../../../../CHANGELOG.md) | User-visible changes; link when closing fixed bugs |
| [`about-sevn.bot/ARCHITECTURE.md`](../../../../about-sevn.bot/ARCHITECTURE.md) | Component map for routing |

## Issue types

| Type | Signals | Default action |
| --- | --- | --- |
| **bug** | Repro steps, regression, stack trace, "broken" | Needs reproduction checklist; route to area owner |
| **enhancement** | Improvement to existing behavior | Acknowledge; prioritize by impact |
| **feature** | New capability | Acknowledge; may need spec/wave before impl |
| **question** | How-to, config help | Answer or redirect to docs; do not close as "not planned" without explanation |
| **docs** | Missing/wrong documentation | Label `documentation`; often good-first-issue |
| **security** | Vuln, credential leak, auth bypass | **Stop** — private advisory only (see SECURITY.md) |
| **duplicate** | Same root cause as an open/closed issue | Link canonical issue; close newer with explanation |
| **support** | Environment-specific, not reproducible on main | Ask for version/logs; may close after stale policy |

## Priority (P0–P4)

| Priority | When |
| --- | --- |
| **P0** | Production/data loss, security incident, gateway down for all operators |
| **P1** | Major feature broken, no workaround, broad user impact |
| **P2** | Degraded feature, workaround exists |
| **P3** | Minor inconvenience, cosmetic, edge case |
| **P4** | Nice-to-have, future consideration |

sevn.bot does not require GitHub priority labels today — record priority in triage comments and
wave plans when labels are absent.

## Labels (suggested; create only when maintainer approves mutation)

| Label | Use |
| --- | --- |
| `bug` | Confirmed or likely defect |
| `enhancement` | Improvement |
| `documentation` | Docs-only |
| `good first issue` | Well-scoped, low risk, clear acceptance |
| `help wanted` | Maintainer welcomes external PR |
| `needs-info` | Missing repro, version, or logs |
| `duplicate` | Linked to canonical issue |
| `question` | Support / usage (consider Discussion redirect) |

Component hints (add to triage comment body when no label exists): `gateway`, `telegram`,
`agent`, `tools`, `skills`, `config`, `storage`, `docs`, `ci`.

## Reproduction checklist (bugs)

Before recommending implementation, confirm or request:

1. sevn version or commit (`sevn --version`, `git rev-parse HEAD`)
2. Host vs Docker gateway
3. Minimal steps (channel, config snippet, expected vs actual)
4. Logs (`sevn doctor`, gateway logs) — **redact secrets**
5. Regression window (last known good version)

## Duplicate policy

1. Search open issues and issues closed in the last 90 days.
2. Link the **most specific** canonical issue.
3. Explain what matches and what differs.
4. Close the duplicate only with maintainer approval and a comment pointing to the canonical issue.
5. Never close solely because the report is old or vague.

## Security and privacy

- **Never** quote tokens, API keys, passwords, or private customer data in public comments.
- Ask reporters to rotate leaked credentials and remove secrets from the issue body.
- Suspected vulnerabilities → [GitHub Security Advisories](https://github.com/sevn-bot/sevn/security/advisories/new), not public triage.

## Stale / closure policy

Do **not** close issues only because they are old or unpopular. Close when:

- Duplicate with link to canonical issue
- Fixed in a released version (cite PR/commit)
- Reporter confirmed resolved
- Out of scope with documented rationale and appeal path
- Needs-info with no response after a documented waiting period (**maintainer decision only** —
  automation never auto-closes)

### Needs-info nudge window (github-issue-manager)

| Rule | Value |
| --- | --- |
| Label trigger | `needs-info` |
| Wait before nudge | **14 days** since last activity (last comment or `updatedAt`) |
| Re-nudge cooldown | Same **14 days** after the previous nudge (tracked in `state.json` `nudge_timestamps`) |
| Auto-close? | **Never** — drafts a gentle nudge comment only; closing remains a human maintainer call |

Script: `scripts/find_stale.py --window-days 14`.

### Weekly digest cadence (github-issue-manager)

| Rule | Value |
| --- | --- |
| Cadence | Every **7 days** (UTC calendar date) |
| State field | `last_weekly_digest` (`YYYY-MM-DD`) in `.ignorelocal/waves/github-issues/state.json` |
| Output | Append to that day's `YYYY-MM-DD.md` using the weekly report template in `SKILL.md` |
| First run | Digest is due when `last_weekly_digest` is null |

Check: `scripts/manager_state.py digest-due --dir … --today YYYY-MM-DD`.

## Wave plan routing

Actionable bugs and features with clear scope should produce or extend a wave plan:

| Destination | When |
| --- | --- |
| **Index row** | Default for github-issue-manager — upsert `#N` into `.ignorelocal/waves/github-issues/index.md` |
| **New wave file** | New theme, no existing open plan covers the work (brief → `@wave-plan-author`) |
| **Existing wave file** | Issue fits an open plan's locked decisions and wave graph |
| **Spec-kit only** | Needs product spec before implementation (`make specify`) |

Default wave output directory: `.ignorelocal/waves/` (operator-local). Manager artefacts:
`.ignorelocal/waves/github-issues/` (see `references/manager-file-model.md`). Kit smoke plans
live under `src/tripll/skw/waves/`.

Implementation waves must follow **tests-first** (one `role = test-author` wave before impl).
Use `make validate WAVE=…` before dispatch.

## Maintainer voice

- Respect first-time contributors; thank them for the report.
- Ask for the **smallest** missing evidence, not a questionnaire.
- Never claim roadmap commitments without maintainer approval.
- Draft all label/close/assign actions first; mutate only on explicit operator approval.
