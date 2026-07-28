---
name: github-issue-triage
description: >-
  Maintainer-safe GitHub issue triage for sevn.bot: fetch open issues, classify
  and prioritize, detect duplicates, draft comments, apply label/assignee updates
  (dry-run first), and route actionable work into new or existing spec-kit-wave
  wave plans. Use when asked to triage issues, clean the issue queue, respond to
  a new bug report, or turn an issue into a wave plan. Based on JSONbored
  awesome-claude community issue triage agent and mergisi/openclaw Sentry triager.
user_invocable: true
---

# github-issue-triage — community issue queue → clear next actions

Turn a noisy GitHub issue queue into labeled, routed, and optionally wave-planned work
without losing community trust. **Recommend and draft first**; mutate labels, assignments,
milestones, or issue state only when the operator explicitly approves.

**Provenance:** adapted from
[JSONbored/awesome-claude github-community-issue-triage-agent](https://github.com/JSONbored/awesome-claude/blob/main/content/agents/github-community-issue-triage-agent.mdx)
and [mergisi/awesome-openclaw-agents github-issue-triager](https://github.com/mergisi/awesome-openclaw-agents/tree/main/agents/development/github-issue-triager)
(Sentry / OpenClaw patterns).

Canonical home: **`spec-kit-wave/skills/github-issue-triage/`**. Install into IDE hosts:

```bash
make -C spec-kit-wave install-skills
```

## When to use

- Triage all open issues or a filtered subset (unlabeled, stale, needs-info).
- Respond to one new issue with classification, duplicate check, and draft comment.
- Turn an actionable issue into a **new** or **existing** wave plan.
- Produce a weekly queue summary for maintainer rotation.
- Prepare `good first issue` candidates with enough context for contributors.

**Not the same as** `git-pr-review` (PR inline comments) or spec-kit **reviewer** (branch
diff → `review-result.json`). Use this skill for GitHub **Issues** queue management.

## Configuration (portable)

Read repo policy paths from `spec-kit-wave/skw.toml` `[github]` when present:

```bash
python3 spec-kit-wave/scripts/context_paths.py --kit-root spec-kit-wave | rg '^github_'
```

| Key | Default | Purpose |
| --- | --- | --- |
| `github_default_repo` | detect via `gh repo view` | Target repository |
| `github_triage_policy` | `spec-kit-wave/skills/github-issue-triage/references/triage-policy.md` | Classification rules |
| `github_wave_plans_dir` | `.ignorelocal/waves` | Operator wave plans |
| `github_contributing` | `CONTRIBUTING.md` | Contribution policy |
| `github_security` | `SECURITY.md` | Security escalation |

Always read `spec-kit-wave/skills/github-issue-triage/references/triage-policy.md` before triage.

## Standing instructions

1. Use **`gh`** for all GitHub reads and writes. Do not fetch GitHub URLs with a browser.
2. **Draft-only by default** for comments, labels, close, assign — show the plan; apply only
   after explicit approval ("apply", "post", "ship triage", "mutate").
3. Read `CONTRIBUTING.md` and `SECURITY.md` before classifying.
4. Never close issues solely because they are old, vague, or difficult to reproduce.
5. Escalate security reports, credential leaks, and abuse to private channels immediately.

## Workflow

### 1. Confirm policies

Read triage policy, contributing guide, security policy, and any issue templates.
Note label taxonomy, stale policy, and whether the repo uses GitHub Projects/milestones.

### 2. Build triage view

Fetch issues (parallel when useful):

```bash
# All open issues (JSON)
python3 spec-kit-wave/skills/github-issue-triage/scripts/fetch_open_issues.py \
  --limit 100 > /tmp/open-issues.json

# Filtered views
gh issue list --state open --label "" --limit 50          # unlabeled
gh issue list --state open --search "no:assignee" --limit 50
gh issue list --state open --search "sort:updated-asc" --limit 20   # stale candidates
```

### 3. Per-issue analysis

For each issue (or the one the operator named), gather:

```bash
gh issue view <N> --json number,title,body,labels,state,author,comments,assignees,milestone
gh issue list --search "in:title <keywords>" --state all --limit 10   # duplicate candidates
gh pr list --search "<keywords>" --state all --limit 5                  # related PRs
```

Identify: type, priority, component, missing evidence, duplicate links, linked PRs, reporter intent.

### 4. Reproduction check (bugs)

Use the checklist in `references/triage-policy.md`. Missing repro → `needs-info` + focused
follow-up comment (not dismissal).

### 5. Duplicate check

Search open issues and issues closed in the last 90 days. Link the most specific canonical
issue; explain sameness and differences.

### 6. Recommend metadata updates

Produce a patch plan per issue:

| Field | Example |
| --- | --- |
| Labels | `bug`, `needs-info`, `documentation` |
| Priority | P1–P4 in triage comment when no label exists |
| Assignee | maintainer login (only when roster known) |
| Milestone | when project uses milestones |
| Duplicate link | `#123` canonical |
| Close? | only with reason + comment draft |

Save plans as JSON for `post_issue_update.py` (dry-run first):

```bash
python3 spec-kit-wave/skills/github-issue-triage/scripts/post_issue_update.py \
  sevn-bot/sevn 21 /tmp/triage-21.json

# After operator approval:
python3 spec-kit-wave/skills/github-issue-triage/scripts/post_issue_update.py \
  sevn-bot/sevn 21 /tmp/triage-21.json --apply
```

### 7. Draft public comments

Write maintainer-safe replies. Ask for the **smallest** missing information. Redact secrets;
ask reporters to remove tokens from the issue body.

**Triage comment template:**

```markdown
## Issue triage — #<N>

**Type:** bug | enhancement | feature | question | docs
**Priority:** P0–P4 — <one-line reasoning>
**Component:** gateway | telegram | agent | tools | …

**Duplicate check:** none | likely duplicate of #<canonical> — <why>

**Missing evidence:** <bullets or "none">

**Next steps:** <what happens next>
```

### 8. Route to wave plan (actionable work)

When an issue needs implementation:

**A. New wave plan** — issue starts a new theme:

1. Fill `spec-kit-wave/skills/github-issue-triage/assets/issue-wave-brief.template.md` → save as
   `.ignorelocal/waves/issue-<N>-brief.md` (or operator-chosen path).
2. Choose slug/title from issue title (kebab-case slug).
3. Author wave file:

```bash
make -C spec-kit-wave wave-generator-run \
  SLUG=issue-21-session-folder-names \
  TITLE="Use group and topic names in session folder paths" \
  CONTEXT=.ignorelocal/waves/issue-21-brief.md \
  PATHS=src/sevn/,tests/
```

4. Validate: `make -C spec-kit-wave validate WAVE=.ignorelocal/waves/<slug>-wave-plan.md`
5. Comment on the issue with the wave plan path/slug (draft first).

**B. Existing wave plan** — issue fits open work:

1. Read the open plan under `github_wave_plans_dir` (default `.ignorelocal/waves/`).
2. Add a `- [ ]` bullet under the appropriate `## Wave <id>` citing `#<N>` and acceptance criteria.
3. Update locked decisions table if the issue freezes a choice.
4. Re-run `make -C spec-kit-wave validate WAVE=<plan>`.
5. Draft issue comment linking the plan wave.

**C. Needs spec first** — unclear product intent:

```bash
make -C spec-kit-wave specify-run SLUG=<slug> TITLE="<title>" CONTEXT=<brief>
```

Hand off to `wayfinder` when fog is high, then `specify` → `plan` → `tasks` (wave-generator).

### 9. Escalations

Stop public triage and flag the operator when the issue mentions:

- Credentials, tokens, private customer data
- Suspected vulnerabilities (route to Security Advisories)
- Abuse, legal risk, or production incidents

## Output contract

Deliverables depend on scope:

| Scope | Output |
| --- | --- |
| **Queue triage** | Summary table + per-issue recommendations + draft comments |
| **Single issue** | Classification + duplicate analysis + comment draft + optional wave brief |
| **Wave routing** | New or updated wave-file path + validation command |
| **Weekly report** | Counts by type/priority, stale list, attention-needed items |

Always include **verification notes**: `gh` queries used, policy files read, actions left unperformed.

## Weekly report template

```markdown
# GitHub issue triage — week of <date>
Repository: <owner/repo>

## Summary
- Open: <N> (+/- <delta> since last report)
- New this week: <N>
- Closed this week: <N>

## By priority (triage assessment)
P0: … | P1: … | P2: … | P3: … | P4: …

## Attention needed
1. #<N> — <reason>
2. …

## Duplicates detected
- …

## Wave candidates
- #<N> → <slug> (new plan | append to <plan>)
```

## Additional capabilities

Beyond fetch / triage / comment / wave routing, this skill also supports:

| Capability | How |
| --- | --- |
| **Duplicate detection** | `scripts/find_duplicates.py` (Jaccard) + title/body search across open + 90-day closed |
| **Good-first-issue prep** | Flag well-scoped issues with clear acceptance + test hints |
| **Stale queue review** | `scripts/find_stale.py` (needs-info nudges, 14-day window, never auto-close) |
| **Support vs bug separation** | Redirect questions to docs; keep bugs actionable |
| **PR cross-link** | `scripts/reconcile_prs.py` — merged PR → "fixed by #PR" + staged close |
| **Closure detection** | `scripts/detect_closure.py` — maintainer-gated close decisions |
| **Changelog linkage** | Note `CHANGELOG.md` entry needed when closing fixed bugs |
| **Batch dry-run** | Multiple `post_issue_update.py` plans before one approval |
| **Spec-kit handoff** | `specify` / `wayfinder` when issue needs design before code |
| **Contributor welcome** | First-time contributor detection via `gh issue view` author |
| **Lifecycle sweep** | `@github-issue-manager` — state/index/daily files; see `references/manager-file-model.md` |

## Headless dispatch

```bash
make -C spec-kit-wave github-issue-triage ISSUE=21
make -C spec-kit-wave github-issue-triage-run ISSUE=21 CONTEXT=brief.md
make -C spec-kit-wave github-issue-triage-run QUEUE=1   # full open queue
```

## Cursor / Claude invocation

| Host | How |
| --- | --- |
| **Cursor** | `@github-issue-triage` agent, or `/github-issue-triage` skill |
| **Claude Code** | `/github-issue-triage` after `make -C spec-kit-wave install-skills` |

## Guardrails

- Do **not** apply `post_issue_update.py --apply` without explicit approval.
- Do **not** commit wave plans unless the operator asks.
- Do **not** run `git clean -x` / `git clean -X`.
- Wave plans: `verify` entries must be Makefile targets; tests-first graph mandatory for impl work.
