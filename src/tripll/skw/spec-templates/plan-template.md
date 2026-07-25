# Implementation Plan: [FEATURE]

**Slug**: `[slug]` | **Branch**: `feature/[slug]` | **Date**: [DATE] | **Spec**: `spec/[slug]/spec.md`

**Input**: Feature specification from `spec/[slug]/spec.md`

Written by the `plan` phase to `spec/<slug>/plan.md`. This is the spec-kit plan standard:
it records the tech-stack and architecture decisions the downstream `tasks` phase
(wave-generator) needs to author wave-file v2 waves. Keep in-repo paths repo-root-relative
(`src/…`, `tests/…`).

## Summary

[Primary requirement (from spec.md) + the technical approach in one paragraph.]

## Technical Context

**Language/Version**: [e.g. Python 3.12]

**Primary Dependencies**: [frameworks/libraries, or "no new runtime deps"]

**Storage**: [if applicable, or N/A]

**Testing**: [test framework + the `make` verify targets waves will run]

**Target Platform**: [e.g. Linux server, CLI]

**Project Type**: [single project / web / library / …]

**Performance Goals**: [domain-specific, or N/A]

**Constraints**: [domain-specific, or N/A]

**Scale/Scope**: [domain-specific, or N/A]

## Constitution Check

*GATE: Must pass before the `tasks` phase. Re-check after design.*

Evaluate this plan against each principle in [`constitution.md`](../constitution.md).
List how the plan satisfies (or must be adjusted to satisfy) Principles I–V. Any deviation
goes in **Complexity Tracking** with a justification, or the plan is changed.

- **I. Code Quality**: [how satisfied]
- **II. Test-Backed Change**: [tests-first wave planned; verify targets]
- **III. UX Consistency**: [how satisfied / N/A]
- **IV. Performance**: [how satisfied / N/A]
- **V. Minimal Deps & Safe I/O**: [how satisfied]

## Project Structure

### Files in scope (repository root)

```text
src/…      # modules this feature touches
tests/…    # test files (authored only in the test-author wave)
```

**Structure Decision**: [Selected layout and the real directories touched.]

## Complexity Tracking

> Fill ONLY if the Constitution Check has violations that must be justified.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| [e.g. new dependency] | [current need] | [why existing primitives insufficient] |
