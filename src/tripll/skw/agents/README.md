# spec-kit-wave — auxiliary agents

Kit-local agent briefs for **non-pipeline** workflows (docs authoring, PRD
writing, verification setup). Runtime pipeline agents (`wave-runner`,
`test-creator`, `reviewer`, …) are documented in the full kit README when
present; this index lists **folder- and doc-kind** agents added for
about-sevn.bot remediation.

| Agent | Path | Scope |
|-------|------|-------|
| docs-folder-author | [`docs-folder-author.md`](docs-folder-author.md) | Whole `about-sevn.bot/specs/` or `about-sevn.bot/prd/` — sync, validate, score, author prose |
| prd-author | [`prd-author.md`](prd-author.md) *(host checkout)* | Single PRD under `about-sevn.bot/prd/` |

Cursor host copies live under `.cursor/agents/` (gitignored locally; copy or
symlink from the host checkout when needed). The canonical cross-link target for
**docs-folder-author** is
