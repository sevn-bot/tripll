# reference-picker

> **Dispatch status:** **Contract + design** — pre-plan or plan-amendment helper; SKW / plan-author
> adjunct; not engine-dispatched on impl waves.

Proposes a concrete quality bar when a goal lacks `[waves.outcome.reference]` (design §11.19).

| Field | Value |
|-------|-------|
| **class** | authoring |
| **edits** | plan file `[waves.outcome.reference]` block only — or amendment appendix |
| **inputs** | wave goal text, optional operator hints, graph context for target repo |
| **outputs** | filled `[waves.outcome.reference]` + one-sentence bar rationale |
| **graph** | reads specs/requirements for wave scope |
| **guardrails** | bar must be **inspectable** (file path, screenshot, rubric, or bench task); reject "make it amazing"; cite why bar fits task (Gauntlet meta-prompt pattern) |
| **done** | reference block validates against plan v3 schema; plan-author or operator accepts before Pre-0 |

Use when plan-author or operator knows the destination but not the comparison artifact — e.g.
"menu section should match redesign HTML", "skill should read like bundled `gh-pr` exemplar".

## Inherited harness

[`src/tripll/skw/agents/_inherited-harness.md`](../../src/tripll/skw/agents/_inherited-harness.md)

## Agent definitions

| Surface | Path |
|---------|------|
| Operator docs (this file) | `docs/agents/reference-picker.md` |
| skw brief | [`src/tripll/skw/agents/reference-picker.md`](../../src/tripll/skw/agents/reference-picker.md) |
| Design | [`docs/design/quality-gauntlet.md`](../design/quality-gauntlet.md) |
