# Golden fixture — W0 wave-task parser (excerpt from tripll-dashboard-ui-wave-plan.md)

## Wave W0 — UI/UX lock + data helper schema (review gate)

- [ ] **W0.1** Document dashboard information architecture in
  `docs/control-plane-design.md` §10: page map (`/`, `/runs/{id}`, `/agents`,
  `/agents/new`, `/agents/{id}/edit`, `/settings`), panel layout on run detail
  (header → batch timeline → wave table → timeline sidebar → expandable log/worktree
  per wave), and LAP observability parity checklist (D11).
- [ ] **W0.2** Lock `latest_events_by_node` ledger API shape (D2): returns
  `dict[node_id, EventRow]` with latest phase, last_action, cumulative
  input/output tokens, cost_usd; add unit-test stub in `tests/test_ledger.py`.
- [ ] **W0.3** Lock safe log path resolver spec (D4): regex + run-dir containment
  tests listed in W0 doc; document max tail bytes (200 KiB).
- [x] **W0.4** Lock worktree status response schema (D5): `{branch, changed_count,
  changed_paths[], diff_stat_lines[], head_sha}`; poll interval 5 s; document stop
  conditions.
