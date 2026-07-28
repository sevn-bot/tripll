---
name: git-pr-review
description: >-
  Review a GitHub pull request and leave draft inline comments. Use when asked
  to review a PR, given a PR URL, told to review this, or to annotate a diff
  without publishing until the user confirms. Based on inancgumus/skills/git-pr-review.
user_invocable: true
---

# GitHub PR review (draft comments)

Review a GitHub PR, leave feedback as **inline draft comments**, and never submit
unless the user says so. Report to the user, not the PR author. Even "LGTM" is
for the user first.

**Provenance:** derived from [inancgumus/skills/git-pr-review](https://github.com/inancgumus/skills/tree/main/git-pr-review).

## When to use

- User gives a PR URL or number and asks for a review.
- User wants draft inline comments on GitHub before sending.
- User wants a thorough review with verification, not a skim.

**Not the same as** skw **reviewer** agent (branch diff →
`review-result.json` for wave loops). Use this skill for human-facing GitHub PR
review on any repo.

## Standing instructions

- If no PR is named, ask which one.
- Ask what else to check beyond the basics (parity with a reference, security,
  tests, area to skip). Treat the answer as standing instructions for this review.
- **Draft only** unless the user opts into chat-only mode (see Chat-only fallback).

## Review method

Run a **reviewer then judge** workflow:

1. **Reviewer pass** — read diff, linked issues, prior comments; find concrete
   issues with evidence (file:line, trace, failing test).
2. **Judge pass** — independently try to refute each finding. Drop anything
   you cannot support with evidence.
3. **Re-verify survivors** — isolate the PR in a throwaway worktree, run
   affected tests, trace call paths. Never call something broken or correct
   without checking.

In Cursor, use the **Task** tool: dispatch a `readonly: true` explore or
`bugbot` / `security-review` subagent for the reviewer pass when the diff is
large; judge and re-verify yourself on survivors.

```
git fetch origin pull/<N>/head:pr-<N>
git worktree add /tmp/pr-<N> pr-<N>
# run tests, inspect; remove worktree when done
```

"Probably" means not verified yet. A hazard you can reason about but not trigger:
raise it as an open question, do not drop it.

Check idiomatic style, simplicity, correctness, and that linked issues are
actually solved. Read linked issues and any reference the user points at (one
level of links; subagent for heavy references).

## Gather

- `gh pr view <N> --comments`
- `gh pr diff <N>`
- `gh api repos/{owner}/{repo}/pulls/{N}/files --paginate` for patches and valid
  anchor lines
- Linked issues; prior reviews:
  `gh api repos/{owner}/{repo}/pulls/{N}/reviews` and `.../comments`

## Verify (sevn.bot)

When reviewing sevn.bot or a repo with a Makefile gate:

- Prefer `make ci-affected` or path-scoped `make lint` / `make typecheck` over
  raw `pytest` / `ruff` / `mypy`.
- Full `make ci` only when the user asks or at merge boundary.
- Telegram/menu changes: note whether `make telegram-menu-docs-check` applies.
- Do not claim CI passed unless you ran the relevant target.

## State store

Scratchpad only (not a PR copy):

```text
${XDG_STATE_HOME:-$HOME/.local/state}/git-pr-review/<owner>-<repo>-<pr>/
```

- `review.json` — review id, last-seen head SHA, comment cursor, user instructions
- `notes.jsonl` — per comment: why flagged, judge verdict, status
  (`open`/`resolved`/`dropped`), author reply deltas
- No tokens, no secrets

## Post draft (private)

1. Build `comments.json` — array of
   `{"path": "...", "line": N, "body": "...", "side": "RIGHT"}` (`LEFT` for removed lines).
2. Run from this skill directory:

```bash
python3 scripts/post_pending_review.py <owner/repo> <pr_number> comments.json [--body "summary"]
```

3. Confirm `state=PENDING` and `published delta: 0`. Save review id. Give the user
   the Files-changed URL. Do not submit.

Anchor each comment to a diff line or GitHub returns 422. If code is not in the
diff, anchor to the nearest changed line and say so. Mechanics:
`src/tripll/skw/skills/git-pr-review/references/pending-review.md`.

**Edit drafts:** delete and repost —
`gh api -X DELETE repos/{owner}/{repo}/pulls/reviews/{review_id}` — then rerun the script.

## Submit (user say-so only)

```bash
gh api -X POST repos/{owner}/{repo}/pulls/{pr}/reviews/{review_id}/events \
  -f event=COMMENT
# or APPROVE / REQUEST_CHANGES
```

Never POST a review event on your own.

## Chat-only fallback

When the user does not want GitHub drafts, or `gh` auth is unavailable:

- Deliver findings in chat, one block per finding with `path:line` and suggested fix.
- Use the same Voice rules below.
- Do not call `post_pending_review.py`.

## Watch loop (only when asked)

Use the **loop** skill. Each tick, compare head SHA and comment cursor in
`review.json`. On new commits or replies, re-fetch, re-verify touched findings,
re-anchor or mark resolved. Draft replies into the store; get user OK before
sending. Stop when the user says so or the PR merges/closes.

## Voice

Write every comment like a concise coworker: what and why, super clear. One
finding per comment. No titles, no severity labels (`test (nit):`, `correctness:`).
Backtick repo names, symbols, and paths.

### Register (absorb, do not copy verbatim)

**Debatable → question, with a guess:**

> Why not just `Context()`?
>
> Wouldn't this panic if `first()` returns `nil`?
>
> Is the overwrite (by object keys) here intentional?

**Clear small fix → terse:**

> No need for `else if` here.
>
> We should handle the error here.

**Taste → hedged, author decides:**

> Maybe we should make this function accept a struct. It has a lot of parameters, and, IMHO, it makes it hard to follow what's going on when reading the usage of this function inside the tests.
>
> Just a suggestion, not a review request.

**Confirmed bug → specific, show mechanism:**

> `rs.cancel()` cancels `maxDurationCtx`, but `iterateSteps` uses the parent `ctx`, so `waiter` never sees the cancellation. After this handler returns, the remaining raw steps keep getting processed.

**Tests → behavior, not internals:**

> Does this test fail without your fix?
>
> Can you add a test that reproduces this issue to avoid future regressions?

**Suggestion block** (only code you would actually apply):

> This could be useful for us to track errors while debugging:
>
> ```suggestion
> return nil, fmt.Errorf("finding clickable point: %w", err)
> ```

**Approval → brief:**

> LGTM functionally.
>
> Clean work 👍 Some nits only.

### Voice rules

- One finding per comment. Many small comments on a complex PR; one-line LGTM on a clean one.
- Hedge taste, not bugs. "No strong opinion, though" on preference; be direct on defects.
- Keep it short. Back hazards with receipts (trace, `-race` output, doc link), not narration.
- `suggestion` blocks for one-liner fixes; fenced blocks for larger sketches.
- Warm, peer-to-peer. Emoji sparingly. Link Go blog, docs, CI runs when useful.
- No headings, numbered sections, or bundled "Verdict" blocks in comment bodies.
- No em dashes, filler adverbs, or passive voice in comments.

Re-read the examples above before writing each comment.
