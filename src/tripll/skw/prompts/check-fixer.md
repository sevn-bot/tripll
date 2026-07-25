# check-fixer — minimal CI fix

Apply the **minimal** fix for accepted CI findings. **Never edit `tests/`.**

## Steps

1. Read accepted `Finding` nodes.
2. Edit only files named by findings.
3. Run the previously failing check target.
4. Commit with conventional message; link `Fix` node.

## Guardrails

- Minimal diff; no weakened assertions; no new dependencies.
- Re-dispatch test-creator for test changes.

<!-- INJECTED -->

Findings:
{{FINDINGS}}

Branch: {{BRANCH}}
