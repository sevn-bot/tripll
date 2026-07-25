# Feature Specification: [FEATURE NAME]

**Slug**: `[slug]` | **Branch**: `feature/[slug]` | **Created**: [DATE] | **Status**: Draft

**Input**: Operator description: "[what you want to build]"

Written by the `specify` phase to `spec/<slug>/spec.md`. Focus on **what** and **why**,
never the tech stack (that belongs in `plan.md`). This is the spec-kit spec standard; the
downstream `tasks` phase (wave-generator) turns these user stories into wave-file v2 waves.

## User Scenarios & Testing *(mandatory)*

<!--
  User stories are PRIORITIZED user journeys (P1, P2, P3…), each INDEPENDENTLY TESTABLE.
  Implementing just one still yields a viable MVP slice. Each story maps to one or more
  waves in the generated wave-file, tagged with its story id (US1, US2, …).
-->

### User Story 1 - [Brief Title] (Priority: P1)

[Describe this user journey in plain language.]

**Why this priority**: [Value and why it ranks here.]

**Independent Test**: [How this story can be verified on its own.]

**Acceptance Scenarios**:

1. **Given** [initial state], **When** [action], **Then** [expected outcome]

---

### User Story 2 - [Brief Title] (Priority: P2)

[Describe this user journey in plain language.]

**Why this priority**: [Value and why it ranks here.]

**Independent Test**: [How this story can be verified on its own.]

**Acceptance Scenarios**:

1. **Given** [initial state], **When** [action], **Then** [expected outcome]

---

[Add more user stories as needed, each with an assigned priority.]

### Edge Cases

- What happens when [boundary condition]?
- How does the system handle [error scenario]?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST [specific capability].
- **FR-002**: Users MUST be able to [key interaction].
- **FR-003**: System MUST [data/behavior requirement].

*Mark unclear requirements for the `clarify` phase:*

- **FR-00X**: System MUST [capability] via [NEEDS CLARIFICATION: unspecified detail].

### Key Entities *(include if the feature involves data)*

- **[Entity 1]**: [What it represents; key attributes without implementation.]

## Seams *(mandatory when this spec implies implementation contracts)*

<!--
  A seam is the public boundary the feature will be built and tested at (see the kit's
  `codebase-design` skill / SPEC-KIT-STANDARDS.md vocabulary cross-link). Prefer existing seams
  over new ones. Use the highest seam possible. The ideal number of new seams this spec
  introduces is ONE — if more feel necessary, push back on the design before writing FR bullets.
-->

- **Existing seam(s) reused**: [name the module/interface(s) this feature builds behind.]
- **New seam(s), if any**: [name + one-line justification for why no existing seam fits. Aim for
  at most one.]

## Success Criteria *(mandatory)*

Technology-agnostic, measurable outcomes.

- **SC-001**: [Measurable metric, e.g. "Users complete X in under N seconds".]
- **SC-002**: [Measurable metric.]

## Assumptions

- [Assumption about users, scope boundaries, data, or existing systems.]
