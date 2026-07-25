# [CHECKLIST TYPE] Checklist: [FEATURE NAME]

**Purpose**: [What this checklist validates — "unit tests for English".]
**Created**: [DATE]
**Feature**: `spec/[slug]/spec.md`

Optional quality gate (spec-kit checklist standard). Use it to validate that the
`spec.md` / `plan.md` are complete, clear, and consistent **before** the `tasks` phase
generates the wave-file. Replace the sample items below with real ones derived from the
spec and plan.

## Requirement Completeness

- [ ] CHK001 Every user story has a priority and an independent test.
- [ ] CHK002 Every functional requirement is unambiguous (no open `NEEDS CLARIFICATION`).
- [ ] CHK003 Success criteria are measurable and technology-agnostic.

## Constitution Alignment

- [ ] CHK004 The plan's Constitution Check addresses every principle in `constitution.md`.
- [ ] CHK005 A tests-first (`role = test-author`) wave is planned for behavioral changes.

## Notes

- Check items off as completed: `[x]`.
- Record findings inline; unresolved items feed back into `clarify` or `plan`.
