# ADR 016 — Tracker protocol with GitHub-only implementation (R30)

**Status:** Accepted (2026-07-29, Wave W0)
**Decisions:** R30 (one protocol, one implementation; Jira out of scope)

## Context

tripll generates wave plans in-repo but has no downstream publish path — a PM cannot see the
breakdown without cloning (PM-02). The intake side hardcodes `gh` in `github/` with no seam an
org on Jira or Linear could implement (PM-01).

External starter-pack skills call Atlassian MCP tool ids from prose (`mcp__atlassian__*`), which
is unversioned coupling forbidden by tripll's standalone dependency rule.

## Decision

1. **Ship a `Tracker` protocol** in `src/tripll/trackers/base.py` with provider-neutral
   vocabulary: `fetch_epic`, `list_children`, `create_child`, `publish_breakdown`. No `gh`,
   `issue`, `PR`, `jira`, or `confluence` in `base.py`.

2. **One real implementation:** `src/tripll/trackers/github.py` wraps the existing `github/`
   module — no new HTTP client, no tracker SDK in base dependencies.

3. **`tripll plan publish`** writes the local artifact first, publishes the breakdown summary,
   then creates missing tickets. **Idempotence by pre-read:** list existing children before
   creating; a second run creates nothing and reports every skip.

4. **Prove the seam with a fake tracker** in the test suite that requires no edit to `base.py`.
   Jira/Confluence is documented as future work, not implemented in this plan.

## Rejected

- **Shipping an Atlassian/Jira integration in W6** — hard dependency on another product's SDK;
  violates `CLAUDE.md` standalone rule. Tracked as an out-of-scope issue.
- **MCP tool ids in agent prompts or source** — unversioned coupling; breaks when MCP servers
  rename tools.
- **Tracker calls on the dispatch hot path** — publish is an operator command after plan compile,
  not inline with wave execution.

## Consequences

- W6 implements `trackers/` and `tripll plan publish`.
- `grep -rn 'mcp__' src/tripll src/tripll/skw/agents` must stay empty.
- Implementing Jira later means adding `trackers/jira.py` without changing `base.py`.
