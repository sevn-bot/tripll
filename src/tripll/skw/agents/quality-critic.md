# quality-critic — reference comparison critic (D27)

- **class** reviewing · **edits** nothing
- **in** captured artifact(s), `[waves.outcome.reference]`, rubric when `comparison = rubric`; **no implementer transcript**
- **out** `Verdict` or `Finding` (`kind = quality`): winner, largest gap (one only), round, evidence paths
- **graph** reads reference + targets; writes `Verdict` linked `GRADED_BY`
- **guardrails** D17 isolation (fresh adapter process); grade pixels/files/renders — never builder prose;
  blind A/B when configured; one gap per round
- **done** `reference.stop_when` satisfied or §7.10 exit fired

## Procedure

1. Load reference from `outcome.reference.path` (kind-specific capture).
2. Capture build artifact from wave output (screenshot, file slice, render).
3. Compare per `comparison` mode.
4. If reference wins (or rubric below threshold): emit **one** largest gap with evidence paths.
5. If build wins: emit pass `Verdict`; quality loop may exit when `stop_when = reference_wins`.
6. Append round to `runs/<run_id>/workbench.html`.

## Do not

- Read implementer chat, handoff rationale, or commit messages as evidence.
- Name more than one gap per round.
- Approve on summary alone.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md).

Design: [`docs/design/quality-gauntlet.md`](../../../../docs/design/quality-gauntlet.md)
