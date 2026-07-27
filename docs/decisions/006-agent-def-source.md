# ADR 006 — AgentDef source in the tracked skw tree (R2)

**Status:** Accepted (2026-07-26, Wave W0); implemented W2 (2026-07-27)  
**Decisions:** R2, R3

## Context

Before W2, `hash_agent_def` (`graphstore/task_sync.py`) could resolve agent briefs from a
gitignored IDE-local agent tree first, then from `src/tripll/skw/agents/`. The test suite
asserted that IDE tree (TEST-03) even though all 14 section-11 slugs already had complete,
tracked briefs under `skw/agents/`.

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
| Author 12 duplicate IDE-local agent briefs | Creates the drift R3 forbids; keeps identity on a gitignored, vendor-specific path |
| Generate briefs at dispatch time | No stable digest; graph nodes would not materialize deterministically |
| Drop AgentDef nodes when the file is missing | Silent absence hides misconfiguration until runtime |

## Consequences

- W2 changes `_agent_def_path` / `hash_agent_def` and turns TEST-03 green.
- W1.13 replaces the IDE-tree assertion with skw-tree + no-IDE-agent-path guards in `src/`.
- Harvest any valuable briefs from local IDE trees into `skw/agents/` before deleting the dependency.
