# ADR 017 — Executable rules beat prose-only (R29)

**Status:** Accepted (2026-07-29, Wave W0)
**Decisions:** R29 (structural rules must be executable)

## Context

tripll's harness enforces **path** scope via `harness/boundary.py` — may this wave touch this
file? — but not **shape**: may this wave write `logging.getLogger`? The CLAUDE.md rule "loguru
only, never stdlib logging" is prose in a brief, enforced by agent attention (AST-01, AST-02).

A rule that fails the build beats a rule that is prose in a brief.

## Decision

1. **Where a rule can be expressed structurally, it must also be executable.** Rules may carry an
   `ast-grep` pattern; `make rules-check` runs every active executable rule and exits non-zero on
   violation.

2. **Prose-only remains legal** for genuinely semantic constraints that have no stable structural
   pattern (e.g. "only an operator activates a rule").

3. **`ast-grep` is an optional dependency.** Absent binary ⇒ warn, prose-only enforcement, exit 0
   — never crash, never a base-install hard dependency.

4. **Same reporting seam as path breaches.** Structural violations report through
   `harness/boundary.py` as scope breaches of *shape*, not a second breach type with separate
   plumbing.

5. **First executable rule:** `no-stdlib-logging`, derived from this repo's own CLAUDE.md — must
   catch a planted `import logging` in `src/tripll/`.

## Rejected

- **Prose-only rules everywhere** — the starter pack's shape; zero gate enforcement.
- **Executable-only rules** — most real constraints are semantic; structural patterns are a subset.
- **Hard dependency on `ast-grep` in base install** — breaks offline/dev environments; optional
  extra only.
- **A rules gate that always exits 0** — decoration, not enforcement (doctor lesson).

## Consequences

- W4 implements `src/tripll/rules/executable.py`, `make rules-check`, and wires into
  `ci-affected` / `ci-resume`.
- `docs/harness-checks.md` gains structural scope breach as a sixth failure class.
- W2's rule model must support `executable: ast-grep` frontmatter before W4 can run patterns.
