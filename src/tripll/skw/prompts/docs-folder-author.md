# docs-folder-author — specs/PRD folder create, update, validate

Create, update, or validate a **whole folder** of committed docs against skw rules and real code.
Wraps `tripll spec sync|validate|score` (or `tripll prd …`) plus agent-authored prose.

## Step 1 — Confirm scope

- **Folder**, **kind** (`spec` | `prd`), and **mode** (`validate` | `update` | `create`).

## Step 2 — Sync scaffolding

Run `make spec-sync` / `make prd-sync` to refresh frontmatter and scaffold missing files.
Sync never fabricates prose.

## Step 3 — Author and gate

For each `*.md` (except `README.md`): read the rules TOML, verify claims against the codebase,
fix prose to be code-true, set honest `status`, then loop `make spec-check` / `make prd-check`
until every file passes (score ≥ 80 for `done`/`ready`).

## Guardrails

- **Docs-only** — never edit `tests/` or product code under `src/`.
- **No fabrication** — unverifiable claims stay scaffold + `## Human-input needed`.
- Do **not** commit unless the operator asks.
- **Never** `git clean -x` / `git clean -X`.

<!-- INJECTED -->

Kind: {{KIND}}
Folder: {{DOCS_DIR}}
Repo root: {{REPO_ROOT}}
Operator context:
{{OPERATOR_CONTEXT}}

Paths to explore: {{EXPLORE_PATHS}}
