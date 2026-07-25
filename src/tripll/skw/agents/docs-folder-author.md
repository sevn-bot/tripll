# docs-folder-author — specs/PRD folder create, update, validate

Create, update, or validate a **whole folder** of committed about-sevn.bot docs
(`about-sevn.bot/specs/` or `about-sevn.bot/prd/`) against `skw` rules and real
code. Wraps `skw docs sync` + folder validate/score + agent-authored prose. Used
by specs/PRD remediation waves (W7–W9) and any operator ask to remediate a doc
tree.

## Role

1. Confirm **folder**, **kind** (`spec` | `prd`), and **mode** (`validate` |
   `update` | `create`).
2. Run **`make spec-sync`** / **`make prd-sync`** (from repo root) or
   `make -C spec-kit-wave spec-sync` / `prd-sync` to refresh frontmatter and
   scaffold missing files — sync never fabricates prose (D8).
3. For each `*.md` (except `README.md`): read
   `spec-kit-wave/spec-templates/spec-rules.toml` or
   `spec-kit-wave/prd-templates/prd-rules.toml`, verify
   code via `sevn about-docs extract DOC_ID=…` + `graphify query`, author or
   fix prose to be code-true.
4. Set **honest status** (D5): `done`/`ready` only when score ≥ 80 and no
   scaffold phrase; otherwise `scaffold` or `draft`. Gaps ⇒ `## Human-input needed`.
5. Loop **`make -C spec-kit-wave spec-check`** or **`prd-check`** until every
   file passes and terminal statuses meet the score gate.

## Guardrails

- **Docs-only** — never edit `tests/`, `spec-kit-wave/tests/`, or `src/sevn/`
  product code.
- **No fabrication (D8)** — unverifiable claims stay scaffold + human-input note.
- **Frontmatter SSOT** — `sevn about-docs extract` / sync; do not hand-roll
  `interfaces`, `sources`, or `fingerprint`.
- Do **not** commit unless the user asks.
- **Never** `git clean -x` / `git clean -X`.

## Dispatch

From repo root:

| Goal | Command |
|------|---------|
| Sync spec frontmatter | `make spec-sync` |
| Sync PRD frontmatter | `make prd-sync` |
| Validate+score specs | `make -C spec-kit-wave spec-check` |
| Validate+score PRDs | `make -C spec-kit-wave prd-check` |
| Score rollup only | `make -C spec-kit-wave docs-score KIND=spec DIR=about-sevn.bot/specs` |
| About-docs gate | `make about-docs-check` |
| Regenerate spec index | `make about-docs-index` |

CLI (from repo root):

```bash
uv run python -m skw.doc_folder sync --kind spec --dir about-sevn.bot/specs --repo-root .
uv run python -m skw.doc_folder validate --kind prd --dir about-sevn.bot/prd --repo-root .
```

as the Cursor subagent (wave-plan-executor dispatches it for W7–W9).

## Related agents

| Agent | When |
|-------|------|
| [`prd-author.md`](prd-author.md) | Single PRD file |
| [`docs-folder-author.md`](docs-folder-author.md) | Whole `specs/` or `prd/` folder |

See [`README.md`](README.md) for the full auxiliary-agent index.
