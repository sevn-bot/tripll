---
name: conventional-commit
description: >-
  Draft and run git commits using Conventional Commits 1.0.0. Use when the user
  asks to commit, amend, write a commit message, or before `git commit` after
  code changes in sevn.bot or any repo that enforces this hook.
---

# Conventional Commits (sevn.bot)

Follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).
This repo enforces the **subject line** via a `commit-msg` pre-commit hook.

## Before committing

1. Run `git status` and `git diff` (staged + unstaged) to understand the change.
2. Read recent messages: `git log -10 --oneline` for tone and scopes.
3. Pick **one** logical change per commit when possible.

## Subject format (required)

```text
<type>[optional scope][optional !]: <description>
```

- **Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
- **Scope:** optional lowercase noun in parentheses, e.g. `(gateway)`, `(telegram)`
- **Breaking:** append `!` before `:` or add `BREAKING CHANGE:` footer in the body
- **Description:** imperative mood, concise, **no trailing period**, subject ≤ 72 characters

## Type selection

| Type | When |
|------|------|
| `feat` | New capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Tests only |
| `refactor` | Neither feat nor fix |
| `chore` | Tooling/deps without product logic |
| `revert` | Reverting prior work (cite SHAs in body) |

## Full reference

Read `src/sevn/data/standards/conventional-commits.md` or `plan/standards/conventional-commits.md`.

## Validate before `git commit`

```bash
make commit-msg-check MSG='feat(scope): your subject here'
```

## Commit workflow

Use a HEREDOC for the message (body optional):

```bash
git add <paths>
git commit -m "$(cat <<'EOF'
feat(scope): short imperative summary

Optional body with context. Footers after a blank line:
Refs: #123
EOF
)"
```

Do **not** use `git commit --no-verify` unless the operator explicitly requests bypassing hooks.

## Examples (good)

```text
feat(telegram): add restart ack after gateway reload
fix(menu): mark owner kill-switches as Ready
docs: align Telegram Menu.html with live keyboards
test(gateway): cover commit-msg validation
```

## Examples (rejected)

```text
Updated stuff
WIP
fixed bug
feat: missing space after colon
feat: trailing period.
```
