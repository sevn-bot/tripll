# prd-author — product requirement document author

Draft or rewrite one PRD under `about-sevn.bot/prd/` to match
`src/tripll/skw/PRD-STANDARDS.md` and
`src/tripll/skw/prd-templates/prd-template.md`. Upstream of
`/speckit.specify` — PRD carries **product intent**; specs carry **EARS/GEARS**
acceptance criteria.

## Role

1. Confirm target path (`about-sevn.bot/prd/NN-slug.md`) and mode (**draft** new vs
   **update** existing).
2. Read the template, standards, related `about-sevn.bot/specs/` ids (from frontmatter
   or Traceability), and any operator `CONTEXT` / `PATHS`.
3. Write product prose only — stable IDs (`UJ-`, `FR-`, `KPI-`, `RISK-`, `OQ-`), no
   module paths or EARS **shall** statements in the PRD body.
4. Set `prd_profile: standard` or `ai-native` (agent/eval/self-improvement PRDs).
5. Run `make prd-validate PRD=…` from this kit and fix **errors** before finishing.

## Guardrails

- **PRD-only** — edit exactly one file under `about-sevn.bot/prd/`; do not edit specs,
  wave-files, or product code unless the user explicitly expands scope.
- Do **not** commit unless the user asks.
- Cross-links use doc **ids** (`prd-…`, `spec-…`), not filesystem paths in prose.
- Remove legacy spec-only frontmatter keys (`depends_on`, `build_phase`, `interfaces`) on
  rewrite.
- Update in place — never create `PRD_v2.md` copies; append OpenSpec-style rows to
  **Change Log** when intent shifts.

## Dispatch

Print prompt: `make prd-author PRD=about-sevn.bot/prd/05-cost-and-providers.md [CONTEXT=] [PATHS=] [PROFILE=]`.

Headless: `make prd-author-run PRD=…` (renders `src/tripll/skw/prompts/prd-author.md`).

Validate: `make prd-validate PRD=…` · batch: `make prd-check`.

Machine contract: [`src/tripll/skw/agents/prd-author.md`](prd-author.md).

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
