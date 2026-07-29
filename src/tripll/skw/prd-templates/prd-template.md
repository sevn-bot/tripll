---
id: prd-NN-slug
kind: prd
title: Feature Name — PRD
status: draft
owner: Alex
summary: One-line outcome statement (max 200 characters). What changes for the operator or user.
last_updated: YYYY-MM-DD
related: []
sources: []
parent_prd: prd-00-main
specs: []
personas: []
prd_profile: standard
---

<!--
  sevn.bot PRD template (skw)

  Synthesis:
  - about-sevn.bot/_docsys frontmatter + six core product sections
  - mattgierhart/PRD-driven-context-engineering — stable IDs, progressive updates, open questions
  - amitgambhir/ai-feature-prd-toolkit — AI-native sections (when prd_profile: ai-native)
  - Fission-AI/OpenSpec — Change Log with ADDED/MODIFIED/REMOVED spec deltas (brownfield)
  - github/spec-kit — [NEEDS CLARIFICATION] markers; specs[] links to engineering specs

  Normative acceptance criteria (EARS/GEARS) belong in about-sevn.bot/specs/, not here.
  See spec-templates/acceptance-criteria-ears.md for spec-level patterns.

  Validate: uv run python -m tripll.skw.prd_validate path/to/this-file.md --kit-root src/tripll/skw
-->

## Problem & Motivation

Who is affected, what pain exists today, and why now. Product prose only — no module paths or
implementation detail.

- **Who:** {persona or operator segment}
- **Pain:** {concrete failure mode today}
- **Why now:** {trigger or cost of inaction}

## Users & Use Cases

Map journeys with stable IDs so agents and humans can reference them across docs and waves.

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | {persona} | {when they reach for this capability} | {value moment} |

**Narrative (optional):**

- **UJ-001 — {title}:** {2–4 sentences: flow, edge case, failure path}

## Goals

Product outcomes. Use **FR-** IDs for testable product requirements (not EARS — those live in
specs).

- **FR-001:** {The product shall … — operator-visible behavior}
- **FR-002:** {…}

## Non-Goals

Hard exclusions to prevent scope creep during spec-kit specify/plan/tasks.

- {Explicit exclusion}
- {Adjacent feature deferred elsewhere — link by prd/spec id if helpful: `spec-NN-…`}

## Experience

What it feels like in Telegram, Mission Control, CLI, or voice — the surfaces the operator
actually uses.

- **Happy path:** {steps}
- **Operator controls:** {config, approvals, kill switches}
- **Degraded path (product-level):** {what the user sees when things go wrong — detail in
  Failure & Degradation when `prd_profile: ai-native`}

## Success Metrics

Measurable signals. Prefer **KPI-** IDs with a number or directional comparison.

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | {name} | {≥ X / ≤ Y / delta vs baseline} | {logs, survey, doctor, MC panel} |

## Traceability

Links this PRD to engineering artifacts. Update in place — never fork `PRD_v2.md`.

### Implementing Specs

List specs that implement this PRD (must match `specs:` in frontmatter).

| Spec id | Scope |
| --- | --- |
| spec-NN-slug | {one-line responsibility} |

Downstream flow: **PRD → `/speckit.specify` → spec.md → plan.md → wave-file v2**.

### Stable ID Index

| Prefix | Meaning | Example |
| --- | --- | --- |
| UJ- | User journey | UJ-001 |
| FR- | Product functional requirement | FR-001 |
| KPI- | Success metric | KPI-001 |
| RISK- | Product risk | RISK-001 |
| OQ- | Open question | OQ-001 |

### Change Log

OpenSpec-inspired **delta** notes when brownfield PRDs or specs evolve. Reference spec ids and
operation — do not paste full spec bodies here.

| Version | Date | Summary | Spec deltas |
| --- | --- | --- | --- |
| 1.0 | YYYY-MM-DD | Initial PRD | — |
| 1.1 | YYYY-MM-DD | {what changed in product intent} | MODIFIED spec-NN-slug §{section} |

Valid delta tokens: `ADDED`, `MODIFIED`, `REMOVED`, `RENAMED` — e.g. `ADDED spec-33-self-improvement §Behavior`.

---

## AI Behavior & Eval

<!-- Required when prd_profile: ai-native (agent tiers, memory, self-improvement, triage, etc.) -->

**AI hypothesis:** We believe that if the system {behavior} in context {Y}, operators will
experience {Z} because {reason}.

**Eval ownership:** {role} · cadence: {weekly / per release} · re-eval triggers: {model change,
prompt change, skill bundle update}

| Eval | Good output | Bad output | Metric | Target |
| --- | --- | --- | --- | --- |
| {name} | {plain language} | {specific failure mode} | {faithfulness / task success / …} | {number} |

**Golden dataset:** {exists? size? owner? refresh cadence?}

**Confidence thresholds (product-level):**

| Band | Threshold | Autonomy | Human checkpoint |
| --- | --- | --- | --- |
| High | {≥ 0.85} | {acts without confirmation} | {none / audit log} |
| Medium | {0.60–0.84} | {suggests} | {operator approves} |
| Low | {< 0.60} | {abstain / fallback} | {see Failure & Degradation} |

---

## Failure & Degradation

<!-- Required when prd_profile: ai-native -->

| Failure | Detection | User-facing behavior | Rollback / owner |
| --- | --- | --- | --- |
| Model timeout | {signal} | {message / silent degrade} | {feature flag / config key} |
| Low confidence | {score band} | {fallback path} | {owner} |
| Wrong output (post-hoc) | {feedback / eval regression} | {correction workflow} | {owner} |

**RISK register (product-level):**

| ID | Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- | --- |
| RISK-001 | {failure mode} | H/M/L | H/M/L | {mitigation linked to spec or test} |

---

## Open Questions

Unresolved items block `status: ready`. Each row needs an owner.

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | {specific question — not "TBD"} | {name} | YYYY-MM-DD | open |

Mark resolved questions with `Status: resolved` and a one-line answer in the Summary column.
