# spec-cartographer — unknown repo → specs

Author one spec per architectural layer from the Code KG. Edit **`spec/**` only**.

## Steps

1. Read the graph-packed brief and explore cited `pkg/` paths.
2. Write `spec/index.md` and one spec per module using the 7-section template (Purpose · Public
   Interface · Data Model · Internal Architecture · Behavior · Failure Modes · Test Strategy).
3. Every claim cites `file:line`. Unknowns → `## Open Questions`.
4. Self-check: no product code edits; no invented requirements.

## Guardrails

- **Spec-only** — never edit product code, tests, or Makefile.
- **Never** run `git clean -x` / `git clean -X`.

<!-- INJECTED -->

Target repo: {{REPO_ROOT}}
Code KG snapshot: {{GRAPH_SNAPSHOT_ID}}
Spec output dir: {{SPEC_DIR}}

Paths to explore:
{{PATHS}}
