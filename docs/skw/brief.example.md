# Operator brief — JSON output for `sevn status`

<!-- Worked example CONTEXT file for `make wave-generator-run ... CONTEXT=brief.example.md`.
     Illustrative only: paths/targets are placeholders — adapt to your repo.
     The whole file is injected into the wave-generator prompt as Operator context. -->

## Goal

Add a `--json` flag to the `sevn status` CLI command so tooling can consume machine-readable
status instead of parsing the human table. Human output stays the default and unchanged.

## Why now / motivation

Mission Control and CI scripts currently scrape the pretty-printed `sevn status` table, which
breaks whenever the layout changes. A stable JSON contract removes that fragility.

## Scope

**In scope:**
- New `--json` boolean flag on `sevn status`.
- A serializer that emits the same fields the table shows (channels, workers, queue depth, last-turn ts).
- JSON shape documented and covered by tests.

**Out of scope:**
- Changing the default human output.
- New status fields or data sources — mirror exactly what the table already reports.
- Any other `sevn` subcommand.

## Relevant code & entry points

- `src/foo/cli/status.py` — the `status` command; renders the table today. The `--json` branch goes here.
- `src/foo/status_model.py` — where the status dict is assembled; reuse it, don't recompute.
- Human table rendering must remain the fallback when `--json` is absent.

## Constraints & locked decisions

- Reuse the existing status assembly in `status_model.py`; do **not** add a new data path or dependency.
- JSON keys are `snake_case` and match the model field names verbatim (stable public contract).
- Emit via `json.dumps(..., indent=2, sort_keys=True)` so output is deterministic and diff-friendly.
- Timestamps are ISO-8601 UTC strings.

## Acceptance / how we know it's done

- `sevn status --json` prints valid JSON with all table fields; exit code 0.
- `sevn status` (no flag) output is byte-for-byte unchanged.
- Verified by: `make lint`, `make typecheck`, `make ci-changed`.

## Must not regress

- The existing human-table test suite stays green.
- No change to `sevn status` timing/side effects (read-only command).

## References

- Related ask: MC dashboard wants to poll status without HTML scraping.
- Prior art: `sevn doctor --json` already follows this pattern — mirror its flag wiring.

## Suggested wave breakdown (optional)

- **W0** (impl, `review_gate = true`): add the `--json` flag plumbing + serializer stub; verify `make lint`.
- **W1** (`role = test-author`): RED tests for JSON shape, key stability, and unchanged human output.
- **W2** (impl): implement the serializer, turn W1 green; verify `make ci-changed`.
- **Final** (impl): docs + full green gate.
