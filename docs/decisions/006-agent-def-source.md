# ADR 006 — AgentDef source in the tracked skw tree (R2)

**Status:** Accepted (2026-07-26, Wave W0)  
**Decisions:** R2, R3

## Context

`hash_agent_def` (`graphstore/task_sync.py`) resolves agent briefs from
`.cursor/agents/<slug>.md` first when present, otherwise from
`src/tripll/skw/agents/`. The Cursor tree is gitignored; `tests/test_agent_roster.py`
asserts the Cursor copy exists, producing 14 failures (TEST-03) even though all 14
section-11 slugs already have complete, tracked briefs under `skw/agents/`.

Binding graph-node identity to an IDE-vendor path in a tool that dispatches to
`claude_code`, `cursor_local`, and `cursor_cloud` equally is the same class of defect
as sevn-shaped content-window buckets (ARCH-CW).

## Decision

1. **Re-home `hash_agent_def` to `src/tripll/skw/agents/<slug>.md`** as the sole
   machine contract. W2 implements the code change; this ADR records the irreversible
   call.
2. **Un-ignore nothing.** The blanket `.cursor/` rule in `.gitignore` stays.
3. **`docs/agents/` remains the human narrative**; `skw/agents/` is the hashed
   machine contract (R3).

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Author 12 duplicate Cursor briefs under `.cursor/agents/` | Creates the drift R3 forbids; keeps identity on a gitignored, vendor-specific path |
| Generate briefs at dispatch time | No stable digest; graph nodes would not materialize deterministically |
| Drop AgentDef nodes when the file is missing | Silent absence hides misconfiguration until runtime |

## Consequences

- W2 changes `_agent_def_path` / `hash_agent_def` and turns TEST-03 green.
- W1.13 replaces the Cursor-tree assertion with skw-tree + no-`.cursor/agents`-refs guards.
- Harvest any valuable briefs from local Cursor trees into `skw/agents/` before deleting the dependency.
