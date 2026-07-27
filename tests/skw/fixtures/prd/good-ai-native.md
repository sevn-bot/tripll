---
id: prd-99-fixture-ai-native
kind: prd
title: Fixture AI Native — PRD
status: draft
owner: Alex
summary: Minimal ai-native PRD fixture for validator tests.
last_updated: 2026-07-08
related: []
sources: []
parent_prd: prd-00-main
specs:
- spec-33-self-improvement
personas: []
prd_profile: ai-native
---

## Problem & Motivation

Self-improvement loops need explicit eval and degradation specs at the product layer.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Operator | Enabling improve mode | Safe bounded self-edit proposals |

## Goals

- **FR-001:** The product shall require operator approval before applying self-improvement patches.

## Non-Goals

- Fully autonomous self-modification without review.

## Experience

Operator reviews proposals in Mission Control before merge.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Unapproved patch rate | 0 | audit log |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-33-self-improvement | Self-improvement pipeline |

### Change Log

| Version | Date | Summary | Spec deltas |
| --- | --- | --- | --- |
| 1.0 | 2026-07-08 | Initial | — |

## AI Behavior & Eval

**AI hypothesis:** Bounded propose-only loops reduce stale prompts without silent drift.

| Eval | Good output | Bad output | Metric | Target |
| --- | --- | --- | --- | --- |
| Patch quality | Actionable diff | Destructive wipe | human review pass | ≥ 90% |

## Failure & Degradation

| Failure | Detection | User-facing behavior | Rollback / owner |
| --- | --- | --- | --- |
| Eval regression | weekly eval | disable auto-propose | operator |

| ID | Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- | --- |
| RISK-001 | Runaway self-edit | H | L | approval gate |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | None | Alex | 2026-07-08 | resolved |
