# ADR 014 — Rules as graph nodes with operator promotion (R26, R27)

**Status:** Accepted (2026-07-29, Wave W0)
**Decisions:** R26 (repo-scoped Rule nodes), R27 (operator-only activation)

## Context

tripll records rich failure telemetry — `Finding`, `Fix`, `Verdict`, scope breaches, attempt
counts — but nothing durable survives run archival. Every kind in the ontology's `finding` layer
uses a `{run_id}#…` natural key, so lessons evaporate when `runs/` moves to processing.

The compounding gap (RULE-01, RULE-02) requires a **Rule**: a repo-scoped constraint with
provenance that outlives any single run and can be packed into the next wave's brief.

## Decision

1. **Rules are first-class graph nodes**, not a loose directory of markdown files. A `Rule` kind
   joins the `finding` layer with natural key `{repo}#{rule_id}` — repo-scoped, not run-scoped.
   Predicates `PREVENTED_BY` / `PROMOTED_FROM` link a rule back to the `Finding` that produced it.

2. **Rendered markdown is derived, not authoritative.** Active rules render to committed
   `.tripll/rules/<rule_id>.md` for operator review and diff; the graph store is rebuildable from
   those files plus promotion metadata.

3. **Three states:** `proposed`, `active`, `retired`. Agents may propose rules from resolved
   findings; **`proposed → active` requires `tripll rules promote`**, an operator command (R27).
   No CLI flag, env var, or `--auto` path may activate a rule without a human.

4. **Origin is mandatory.** Every rule carries `origin: codebase://<file>:<line>` (derived) or
   `finding://<run>#<id>` (promoted). A rule without a resolving origin is rejected by the
   validator — it is an opinion, not a constraint.

## Rejected

- **Rules as a plain directory of markdown** — cannot express `PROMOTED_FROM` back to the
  finding that produced the rule; provenance becomes optional prose and drifts.
- **Rules as run-scoped nodes** (`{run_id}#…`) — preserves the status quo where every kind in
  the finding layer compounds nothing after archival.
- **Auto-promotion on a confidence threshold** — silent and permanent when wrong; same failure
  mode as auto-merge (D15), applied to binding constraints instead of code.

## Consequences

- W3 adds the `Rule` kind and predicates to `ontology.yaml` and wires promotion in
  `src/tripll/rules/promote.py`.
- W2 authors the store, derivation, and brief-packing seam that W3 writes into.
- `.mergecraft/learnings.md` keeps exporting rejected findings unchanged; active rules render
  beside it through the same learnings renderer.
