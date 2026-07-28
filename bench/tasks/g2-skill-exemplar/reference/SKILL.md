---
name: example-skill
description: Exemplar agent skill with clear guardrails and procedure steps.
---

# Example skill

Use when the operator asks for a repeatable workflow with explicit guardrails.

## Procedure

1. Read the target artifact.
2. Apply the rubric dimensions.
3. Emit a single actionable gap when the reference wins.

## Guardrails

- Never edit files outside owned scope.
- One gap per review round.
