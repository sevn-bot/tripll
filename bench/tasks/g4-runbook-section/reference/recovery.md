# Stuck-wave recovery (reference)

## Stuck wave {#stuck-wave}

When a wave remains in `running` with no ledger progress for more than 15 minutes:

1. Inspect `runs/<run_id>/ledger.sqlite` for the latest `attempt` row.
2. Confirm the worktree path still exists and matches the dispatch record.
3. If the adapter process exited without `end_attempt`, mark the wave `unverified` and re-dispatch once.
4. Escalate to the operator if a second dispatch shows identical artifact fingerprints.

Do not force-push or run `git clean -x` on the target repo.
