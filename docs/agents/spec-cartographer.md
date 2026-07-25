# spec-cartographer

Author specs for a **previously unknown repo** (D18). Extract the Code KG first, then emit one
spec per architectural layer using skw's 7-section template.

## Contract

| Field | Value |
|-------|-------|
| **class** | authoring |
| **edits** | `spec/**` in the target repo only |
| **inputs** | git URL or local checkout; no language/layout assumption |
| **outputs** | specs per module/layer, `spec/index.md`, Code KG snapshot id |
| **graph** | reads layer `code`; writes `Spec`, `Requirement`, `SPECIFIES`, `OWNS` |
| **guardrails** | every claim cites `file:line`; no invented requirements; unknowns → `## Open Questions`; **never** edits product code |
| **done** | `skw spec-check` passes; `doc_score ≥ 80` for every spec; every large `Module` owned by exactly one spec |

## Inherited harness

Tool boundary · handoff contract · loop exits · idempotency · graph-packed brief —
[`src/tripll/skw/agents/_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md).

## Procedure

1. `tripll graph extract --repo <path> --sha <base>`
2. Dispatch `spec-cartographer` with graph-packed brief from code layer.
3. Validate: `tripll spec-check --dir spec/` and `tripll doc-score --kind spec --dir spec/`.

## E2E proof (W11.6)

**Fixture repo:** [`tests/fixtures/spec_cartographer_mini/`](../../tests/fixtures/spec_cartographer_mini/)
— a minimal Python package with no prior specs (simulates an unknown third-party repo).

**Recorded run (stub):**

| Step | Command / artifact | Result |
|------|-------------------|--------|
| Extract | `tripll graph extract` on fixture pkg | Code KG at fixture sha |
| Emit | Agent writes `spec/index.md` + layer specs | See fixture `spec/` tree |
| Validate | `tripll spec-check` + `doc_score` | ≥ 80 on all emitted specs |

The automated gate is `tests/test_agent_roster.py::test_spec_cartographer_fixture_passes_spec_check`
— runs deterministic validation against the fixture output without an LLM dispatch.

**Operator full e2e:** point the agent at any OSS repo with no existing `spec/` tree, run extract
→ cartography → spec-check. Record repo URL and output path in this section.

## Agent definitions

| Surface | Path |
|---------|------|
| Operator docs (this file) | `docs/agents/spec-cartographer.md` |
| skw brief | [`src/tripll/skw/agents/spec-cartographer.md`](../../src/tripll/skw/agents/spec-cartographer.md) |
| Cursor subagent | [`.cursor/agents/spec-cartographer.md`](../../.cursor/agents/spec-cartographer.md) |
| Prompt | [`src/tripll/skw/prompts/spec-cartographer.md`](../../src/tripll/skw/prompts/spec-cartographer.md) |
