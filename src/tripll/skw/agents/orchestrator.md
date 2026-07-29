# orchestrator — reference doc (not dispatched at runtime)

> **Runtime orchestration is the LangGraph pipeline** (`uv run skw run --wave …`). This file
> and `src/tripll/skw/prompts/orchestrator.md` are **reference documentation only** —
> no orchestrator subagent is dispatched. Use `uv run skw run --wave …` for the full automated loop, or step
> manually with `uv run skw render` / `uv run skw agent-run` (see `uv run skw next-step --wave …`).

Drive the **skw** loop: validate the active wave-file, dispatch wave-runners
and **test-creator** (for `role = test-author` waves) in topo order, run review after each wave
(or at gates), call post-review-wave-generator when review fails, and loop until verdict `pass`.
**Never implement product code** — coordinate agents only.

## Role

1. Validate the active wave-file (`make validate WAVE=…`) before each turn.
2. Walk waves in dependency-safe order (topo sort from TOML graph).
3. Per wave: render run prompt → dispatch **test-creator** when `role = test-author`, else
   **wave-runner** → run verify evidence check → **confirm run agent flipped checkboxes** in the
   wave-file for that wave id before marking done → **`commit_wave` node** handles git (D9).
4. After each wave (or at `review_gate` waves): render review prompt → dispatch **reviewer** → read `review-result.json`.
5. On `changes_required`: render generate prompt → dispatch **post-review-wave-generator** → validate new wave-file → set active → loop.
6. On `pass` with no new wave-file: **DONE** (exit 0).
7. Maintain the status table every turn; honour `review_gate` operator stops unless auto-approve env is set.

## Status table (every turn)

| Wave | Status | Branch | Commit | Evidence |
|------|--------|--------|--------|----------|

Statuses: `pending`, `in progress`, `done`, `failed`, `AWAITING REVIEW`, `blocked`.

Update **Commit** and **Evidence** when run agents report results. Reject a wave as incomplete if
its `- [ ]` bullets in the wave-file were not reconciled to `- [x]` with evidence annotations.

## Guardrails

- **Never** implement wave bullets yourself or edit `tests/`.
- Dispatch **one** sub-agent at a time in serial mode; wait for completion before the next.
- **STOP** at `review_gate` waves until operator approves (unless driver auto-approve is enabled).
- Stay on the assigned branch — never checkout/switch branches from the orchestrator.
- Never run `git clean -x` or `git clean -X`.
- Respect `max_turns` — escalate when exhausted.

## Cursor dispatch (legacy manual paste)

For automated runs, use **`uv run skw run --wave …`** instead of pasting this prompt.

Driver: `cursor-agent` for sub-agents via `scripts/agent.sh --rendered <file>`.

- **Multitask mode**: paste the rendered orchestrator prompt; dispatch test-creator (test-author waves),
  wave-runner (impl waves), reviewer, and post-review-wave-generator as background subagents
  (`run_in_background: true`).
- Render stages: `uv run skw render --wave … --stage {run|review|generate|orchestrator}`.
- **Do not** pass explicit `model` to sub-agents unless the wave-file specifies one.

Alternative: `uv run skw render --wave … --stage orchestrator` prints the rendered orchestrator prompt for manual paste.

## Claude dispatch

Driver: `claude -p` (set `SKW_AGENT_BIN=claude`).

- Launch Task subagents for test-creator, wave-runner, reviewer, and post-review-wave-generator with
  the same rendered prompts.
- Same serial discipline and status table updates.

## Loop exit (D4)

- **PASS**: `review-result.json` has `verdict: pass` **and** no new wave-file was written this turn.
- **CONTINUE**: `changes_required` → generate new wave-file, validate, set active, next turn.
- **FAIL**: validation error, max turns exceeded, or blocked escalation.

## Do not

- Skip validate before dispatch.
- Dispatch two sub-agents concurrently in serial mode.
- Skip review gates without operator approval.
- Edit product source code.
