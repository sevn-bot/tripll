---
name: changelog-author
description: >-
  Draft or refresh CHANGELOG.md `## [Unreleased]` entries from a code diff. Use
  after changes under `src/sevn/` or `scripts/`, when the user asks to update the
  changelog, add a changelog entry, or note what changed for a release. Writes
  impact-first bullets that pass `make changelog-check`.
---

# Changelog authoring (Unreleased entries)

Write changelog entries like a maintainer telling users what changed for them.
Impact first, mechanism never. One change per bullet. Match detail to the change.
Entries land under `## [Unreleased]` and are cut into a version at release time.

**Standards:** `src/tripll/skw/CHANGELOG-STANDARDS.md` ·
**Templates:** `src/tripll/skw/changelog-templates`.

## When to use

- A PR or branch touches user-visible surface under `src/sevn/` or `scripts/`.
- The user says "update the changelog", "add a changelog entry", or "note this
  for the release".
- Before finalising a branch, to make sure `make changelog-check` will pass.

Not for hand-writing dated version sections — those are cut from Unreleased at
release time (see the review skill / standards).

## Workflow

1. **Gather the diff** (run in parallel when possible):
   - `git diff <base>...HEAD --stat` and `git diff <base>...HEAD` for scope.
   - `git log <base>..HEAD --oneline` for commit subjects.
   - Read the current `CHANGELOG.md` `## [Unreleased]` block to avoid duplicates.
2. **Map surfaces to user-visible effects.** For each changed area, ask: what can
   a user now do, see, or no longer hit? Ignore pure internals.
3. **Pick a category** per effect — Added / Changed / Deprecated / Removed /
   Fixed / Security (Keep a Changelog order). One category per bullet; pick the
   single best fit. Breaking changes go under Changed or Removed, flagged as
   breaking in the text.
4. **Draft entries** obeying the row rules:
   - bullet `- `, **leading `[YYYY-MM-DD]` datestamp** (today's date, D10),
     sentence case after the stamp, **no trailing period**, >= 12 chars of content;
   - backticks for code / commands / flags / paths only;
   - issue refs as `(#123)` at the end (bare `#123`, no backticks);
   - impact first, mechanism out.
5. **Place them** under the matching `### Category` in `## [Unreleased]`. Leave
   unused category subheadings empty (that is allowed).
6. **Suggest the quality check:** recommend `make changelog-eval` (the advisory
   LLM double-score) before finalising, and note that `make changelog-check` is
   the deterministic gate CI runs.

If the diff has genuinely no user-visible effect (refactor, test-only, comments),
do not invent an entry — tell the user to add a `changelog: skip` trailer instead.

## Voice (absorb, do not copy)

Describe the outcome for the user, then the trigger if it helps. No function
names, package names, or lock/goroutine jargon in the prose.

**Good:**

> - [2026-07-14] Session toggles now persist across gateway restarts
> - [2026-07-14] New `--retry` flag on `sevn onboard` to resume an interrupted setup (#412)

**Bad:**

> - Refactored `SessionManager.persist()` to fix mutex ordering  (mechanism, jargon, no datestamp)
> - Fixed stuff.  (vague, trailing period, too short, no datestamp)

## Good vs bad, by category

| Category | Good | Bad |
| --- | --- | --- |
| Added | `- [2026-07-14] New \`--json\` output on \`sevn doctor\`` | `- Added json` |
| Changed | `- [2026-07-14] Mission Control defaults to dark theme on first launch` | `- Changed the theme code` |
| Removed | `- [2026-07-14] Dropped the unmaintained IRC channel adapter` | `- removed adapter.` |
| Fixed | `- [2026-07-14] Crash when a workspace path contained a trailing space` | `- bugfix` |
| Security | `- [2026-07-14] Secrets are now redacted from proxy debug logs (#508)` | `- security fix` |

## Handoff

After drafting, show the entries inline and point the user at the review skill
(`src/tripll/skw/skills/changelog-review/SKILL.md`) or agent to run both
gates. Do not commit unless the user asks.
