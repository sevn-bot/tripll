# clarify — resolve underspecified areas before planning

Read the existing spec at the injected Spec path and reduce ambiguity **before** the `plan`
phase. Edit **only** the spec file. Do **not** edit product code, run builds, author tests,
or commit.

## Step 1 — Scan for ambiguity

- Collect every `[NEEDS CLARIFICATION: …]` marker in the spec.
- Look for underspecified areas: vague requirements, missing acceptance scenarios, unbounded
  scope, undefined entities, or success criteria that are not measurable.

## Step 2 — Ask and record

- Pose a small, prioritized set of concrete questions (coverage-based, most impactful first).
- Record answers in a **`## Clarifications`** section of the spec, dated, and update the
  affected requirements / scenarios in place. Resolve or remove each `[NEEDS CLARIFICATION]`
  marker you settle.
- If the operator intentionally skips clarification (spike/prototype), note that and stop.

## Step 3 — Self-check

- [ ] A `## Clarifications` section exists with dated answers.
- [ ] Every resolved unknown updated the relevant requirement/scenario.
- [ ] Remaining open items are still tagged `[NEEDS CLARIFICATION: …]` (not silently dropped).
- [ ] Only the spec file was edited; nothing built, tested, or committed.

<!-- INJECTED -->

Stage: {{STAGE}}
Title: {{TITLE}}
Slug: {{SLUG}}
Spec path: {{SPEC_PATH}}
Spec template: {{SPEC_TEMPLATE}}

Operator context:
{{OPERATOR_CONTEXT}}

Paths to explore: {{EXPLORE_PATHS}}
