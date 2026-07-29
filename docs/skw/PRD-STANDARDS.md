# PRD standards (skw)

Product requirement documents for sevn.bot live under `about-sevn.bot/prd/`. This kit owns
the **template**, **rules**, and **validator** until the standard is applied repo-wide.

## What we borrowed

| Source | What we took | Where it lives |
| --- | --- | --- |
| [about-sevn.bot/_docsys](https://github.com/sevn-bot/sevn) | YAML frontmatter schema, six core H2 sections | `prd-template.md` frontmatter + §Problem…Success Metrics |
| [github/spec-kit](https://github.com/github/spec-kit) | `[NEEDS CLARIFICATION]` discipline; PRD → specify → plan → tasks | Traceability §Implementing Specs; `SPEC-KIT-STANDARDS.md` |
| [mattgierhart/PRD-driven-context-engineering](https://github.com/mattgierhart/PRD-driven-context-engineering) | Stable IDs (UJ/FR/KPI/RISK/OQ), progressive update in place, open questions gate readiness | Traceability §Stable ID Index; §Open Questions; §Change Log |
| [amitgambhir/ai-feature-prd-toolkit](https://github.com/amitgambhir/ai-feature-prd-toolkit) | Eval, confidence bands, failure/degradation, golden dataset | §AI Behavior & Eval; §Failure & Degradation (`prd_profile: ai-native`) |
| [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) | ADDED/MODIFIED/REMOVED spec deltas in change log | Traceability §Change Log |
| EARS / GEARS | Normative **shall** criteria | **Specs only** — `spec-templates/acceptance-criteria-ears.md` |

### PRD-driven-context-engineering — fit for sevn

**Use:** ID discipline, progressive documentation (update in place), open-questions as gates,
readiness mindset.

**Do not adopt wholesale:** the v0.1→v1.0 lifecycle gates, SoT/ folder taxonomy, 47 skills,
and EPIC-centric execution — sevn already has `about-sevn.bot/specs/`, wave-orchestrator, and
`src/tripll/skw/` for execution.

## Document layers

```mermaid
flowchart TB
  prd["about-sevn.bot/prd/*.md\n(product intent)"]
  specify["spec-kit specify → spec.md"]
  plan["plan.md"]
  waves["wave-file v2"]
  specs["about-sevn.bot/specs/*.md\n(EARS acceptance criteria)"]

  prd --> specify
  specify --> plan
  plan --> waves
  prd -.->|specs[] + Change Log deltas| specs
  waves --> specs
```

## Profiles

| `prd_profile` | When | Extra required sections |
| --- | --- | --- |
| `standard` | Default — operator UX, config, cost, channels | — |
| `ai-native` | Agent behavior, eval, memory, self-improvement, triage | AI Behavior & Eval; Failure & Degradation |

Set in frontmatter. Validator enforces profile-specific sections.

## Frontmatter rules

- `kind` must be `prd`.
- `id` pattern: `prd-NN-slug` (stable cross-links — never link by path).
- `parent_prd`: `null` only for `prd-00-main`; all other PRDs require `prd-00-main` or a
  domain umbrella id.
- `summary`: ≤ 200 characters.
- `specs`: list of `spec-NN-slug` ids implementing this PRD (must match Traceability table).
- Forbidden on PRDs: `depends_on`, `build_phase`, `interfaces` (spec-only fields).

## Body rules

1. **Required H2 sections** (in order): Problem & Motivation → … → Traceability.
2. **Traceability H3:** Implementing Specs, Change Log (OpenSpec-style deltas).
3. **No code** in PRD bodies — type sketches and EARS live in specs.
4. **`status: ready` or `done`:** no scaffold placeholders; Open Questions must not contain
   unresolved `open` rows without owner and due date.
5. **Stable IDs** when used must match `UJ-###`, `FR-###`, `KPI-###`, `RISK-###`, `OQ-###`.

## Commands

```bash
# Validate one file (path relative to repo root or absolute)
uv run python -m tripll.skw.prd_validate about-sevn.bot/prd/05-cost-and-providers.md --kit-root src/tripll/skw

# Validate all PRDs under a directory (default: docs/prd)
make prd-check

# JSON output for hooks/CI
uv run python -m tripll.skw.prd_validate path/to/prd.md --kit-root src/tripll/skw --json
```

## Applying to about-sevn.bot/prd

1. Copy `prd-templates/prd-template.md` as the starting point for each PRD rewrite.
2. Set `prd_profile: ai-native` for prd-12-self-improvement, prd-02-personality-and-memory,
   prd-13-extensibility, and similar agent-centric PRDs.
3. Run `make prd-check` from the repo root until clean.
4. Record spec brownfield edits in PRD Change Log with OpenSpec delta tokens.

## Files

| File | Purpose |
| --- | --- |
| `agents/prd-author.md` | Agent reference + dispatch |
| `prompts/prd-author.md` | Headless prompt template |
| `prd-templates/prd-template.md` | Authoring template |
| `prd-templates/prd-rules.toml` | Machine-readable rules for validator |
| `src/skw/prd_validate.py` | Validator implementation |
| `scripts/validate_prd.py` | CLI entry |
| `spec-templates/acceptance-criteria-ears.md` | Spec-level EARS/GEARS + OpenSpec deltas |
