---
id: prd-99-fixture-standard
kind: prd
title: Fixture Standard — PRD
status: draft
owner: Alex
summary: Minimal valid standard-profile PRD for spec-kit-wave validator tests.
last_updated: 2026-07-08
related: []
sources: []
parent_prd: prd-00-main
specs:
- spec-17-gateway
personas:
- operator
prd_profile: standard
---

## Problem & Motivation

Operators need a deterministic way to validate PRD shape before rewriting about-sevn.bot
documents.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Operator | Authoring a new PRD | Validator passes before review |

## Goals

- **FR-001:** The validator shall report missing required H2 sections.

## Non-Goals

- Rewriting existing PRDs automatically.

## Experience

Run `make prd-validate` from spec-kit-wave with a file path.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Validator pass rate on fixtures | 100% | pytest |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-17-gateway | Gateway turn spine |

### Stable ID Index

| Prefix | Meaning |
| --- | --- |
| UJ- | User journey |

### Change Log

| Version | Date | Summary | Spec deltas |
| --- | --- | --- | --- |
| 1.0 | 2026-07-08 | Initial | — |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | None for fixture | Alex | 2026-07-08 | resolved |
