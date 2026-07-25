# Changelog entry row (Unreleased)

Use under `## [Unreleased]` → `### Added|Changed|…`.

```markdown
- [YYYY-MM-DD] Sentence-case impact statement with `backticks` for code (#123)
```

Rules (see `CHANGELOG-STANDARDS.md`):

- Leading **`[YYYY-MM-DD]`** datestamp on every Unreleased bullet (released sections exempt)
- Sentence case after the stamp; **no trailing period**
- Minimum 12 characters in the full bullet body (stamp + prose)
- Issue refs as `(#123)` at the end — bare `#123`, no backticks

Examples:

```markdown
- [2026-07-14] New `--retry` flag on `sevn onboard` to resume an interrupted setup (#412)
- [2026-07-14] Mission Control defaults to dark theme on first launch
```

Optional time suffix (allowed, not default): `[2026-07-14T12:00Z]`.
