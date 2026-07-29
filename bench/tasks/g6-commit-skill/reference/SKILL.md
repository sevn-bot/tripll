---
name: conventional-commit
description: Draft git commit messages using Conventional Commits 1.0.0.
---

# Conventional commit

Use when the operator asks to commit or record changes in git.

## Procedure

1. Read staged and unstaged diffs.
2. Draft a subject line under 72 characters with the correct type prefix.
3. Validate with `scripts/check_conventional_commit.py` before committing.

## Guardrails

- Never use `--no-verify` unless the operator explicitly allows it.
- Focus the message on why the change exists, not a file list.
