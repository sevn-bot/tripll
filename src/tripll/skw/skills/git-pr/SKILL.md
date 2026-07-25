---
name: git-pr
description: >-
  Draft or revise GitHub pull request titles and descriptions. Use when the
  user asks to open a PR, write a PR body, update PR text, or polish a title
  before posting. Based on inancgumus/skills/git-pr, adapted for sevn.bot.
---

# PR description writing

Write PR descriptions like an experienced engineer talking to another engineer.
Concise, human, scoped to the change. Omit empty sections. Match description
length to PR scope. Never put diffstat numbers, line counts, or file counts in
the description.

**Provenance:** derived from [inancgumus/skills/git-pr](https://github.com/inancgumus/skills/tree/main/git-pr).

## When to use

- User asks to create, draft, or update a PR title or body.
- User says "open a PR", "write the description", or "ship it" (draft first;
  post only after explicit confirmation).
- Before `gh pr create` when the default template would be too thin or too noisy.

## Workflow

1. **Gather context** (run in parallel when possible):
   - `git status`
   - `git diff` (staged + unstaged) and `git diff <base>...HEAD` for branch scope
   - `git log <base>..HEAD --oneline` for commit subjects
   - `gh pr list` / linked issues when relevant
   - Use `gh` for all GitHub reads. Do not fetch GitHub URLs with a browser or
     generic fetch tool.
2. **Summarize** for the user in a few sentences: what changed, how big, what
   areas it touches.
3. **Ask** what to emphasize, tone, and anything to call out or omit. Skip only
   when the user explicitly says to write without asking.
4. **Draft** title and body inline, formatted exactly as they will appear on
   GitHub. Do not create or update the PR yet.
5. **Wait** for "post", "ship it", "lgtm", or similar before touching git. On
   feedback, revise and show the updated draft inline.
6. **Post** with `gh pr create` or `gh pr edit` (see Posting).

For branch commits before the PR, load the **conventional-commit** skill when
subjects need to match repo hooks.

## Posting

Only after the user confirms.

**Create:**

```bash
git push -u origin HEAD
# Write body with the Write tool or:
printf '%s' "$BODY" > /tmp/pr-body.md
gh pr create --title 'short title here' --body-file /tmp/pr-body.md
```

**Update an existing PR:**

```bash
printf '%s' "$BODY" > /tmp/pr-body.md
gh pr edit <number> --title 'revised title' --body-file /tmp/pr-body.md
```

Always pass PR bodies via `--body-file`. Never inline with `--body "..."` or a
shell heredoc on the `gh` command line. Agent runners often wrap commands in
`bash -c "..."`; outer double quotes expand backticks before `gh` runs, so
commands inside backticks execute and corrupt the body.

Single-quoted titles are safe: `gh pr create --title 'Add format flag' --body-file /tmp/pr-body.md`.
If the title contains a single quote, write it to a file too.

Do **not** push unless the user asks.

## Structure

Use only sections that help the reviewer.

```markdown
## What?

<Standalone summary sentence. What the PR does in plain terms.>

## Why?

<Broad impact first. How does this improve things for the user?>

<Optional narrowing. The specific symptom or trigger that made this visible.>

## Note

<Optional. Dependencies, migration steps, or reviewer heads-up.>

## Test plan

<Optional. Only when the user or repo convention asks. Checklist of manual or
automated checks. For sevn.bot Python changes, name make targets actually run
(e.g. make ci-affected, make lint), not raw pytest/ruff.>

## Related PR(s)/Issue(s)

Depends on #NNN
Closes #NNN
```

**Never copy example sentences below.** Absorb tone and structure, then write
original text from the actual diff.

### What section

- First sentence = standalone summary of **impact or outcome**, not mechanism.
  Bad: "Defers response reads until after lifecycle events complete." Good:
  "Fixes frame navigation to return responses reliably."
- Wrong level if it names packages, functions, or internal components. Describe
  what the consumer gets.
- No function names, package names, method names, or API calls in What/Why prose.
- Larger PRs: bullet list of user-visible behavior changes after the summary.
- Keep "why" out of What. That belongs in Why.

### Why section

- Scenario-driven. What the user does, what happens, why it matters. Readable by
  a PM; the diff shows the how.
- Lead broad (end-user impact), then narrow to the trigger if helpful.
- Larger PRs: bullets in "X without Y" form.
- No locks, mutexes, goroutines, signal names, or error codes. Describe observable
  effects.
- Do not badmouth the old approach. Do not pad with obvious statements.

### Separation

- **What** = problem solved + behavior change.
- **Why** = why now / what prompted this.

## PR titles

- Under 60 characters ideal; never exceed 72.
- `area: change in plain terms` (e.g. `gateway: fix session toggle persistence`).
- For fixes: root cause level, not symptom or mechanism.
  - Good: `browser: fix frame document ordering`
  - Bad: `browser: fix nil response on navigation` (symptom)
  - Bad: `browser: fix navigation request-document ordering` (mechanism)
- For features: capability added, not implementation.
- sevn.bot branches often use Conventional Commits scopes; align title scope with
  commit subjects when they share one theme.

## Tone and prose rules

- Engineer-to-engineer, active voice, direct sentences.
- Never refer to the PR itself ("this PR", "this change", "it adds").
- No em dashes as connectors. Use periods or commas.
- No marketing slogans or template filler.
- **Backticks in What/Why:** avoid. Plain `#1234` for issues (no backticks on
  issue refs or GitHub won't auto-link).
- **Backticks in Note / Test plan:** OK for commands, paths, and flags.
- Do not hard-wrap paragraphs. One physical line per paragraph; GitHub soft-wraps.
  Verify: `gh pr view <n> --json body -q .body | cat -A`
- Mermaid only when words genuinely fail (multi-party protocols, state machines).

## Public repos

Title, body, branch name, commits, and references are world-visible. Omit internal
service names, run IDs, and architecture-only jargon. When unsure, treat as internal.

Cross-repo refs: `org/repo#123`. Check visibility before referencing private repos
from a public repo: `gh repo view org/repo --json visibility`.

## Examples (scale to your PR)

**Small**

Title: `config: move validation out of experimental`

```markdown
## What?

Moves config validation into the stable package.

## Why?

Keeps the canonical source in the stable module location rather than leaving it behind.
```

**Bug fix**

Title: `worker: unblock concurrent job creation`

```markdown
## What?

Concurrent job creation no longer blocks behind a slow download on the same node.

## Why?

When a job uses a custom binary (e.g., with plugins), the worker downloads it during setup. That download can take minutes. While it runs, every other job on the same node waits, even though the downloads are independent.
```

**Large**

Title: `docs: always-current documentation, smaller binary`

```markdown
## What?

Adds on-demand documentation loading with auto-refresh and preloading.

- Lazy-loads documentation files on demand, with multi-version support.
- Automatically refreshes docs when they change.
- Adds a preload flag to download all versions at startup.

## Why?

Stale docs mean wrong code suggestions, outdated API usage, missing features.

- Docs stay fresh without rebuilding or redeploying.
- Smaller binary without embedding every version at build time.
- Loads only the requested version instead of all sections at startup.
```

### Key patterns

- Scale description to PR size.
- Show with code examples or before/after when that clarifies behavior.
- Tables when comparing old vs new across multiple cases.
- Extra sections only when reviewers need them.
