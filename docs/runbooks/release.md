# Release runbook

Operator guide for cutting and publishing **tripll** releases. This document records the
[#65](https://github.com/sevn-bot/tripll/issues/65) evaluation of
[Sentry Craft](https://github.com/getsentry/craft) and the chosen release process.

## Decision summary (#65 / W3)

| Item | Outcome |
| --- | --- |
| **Craft evaluation** | Completed 2026-08-03 |
| **Recommendation** | **Reject** — do not adopt Craft |
| **Alternative** | Tag-triggered GitHub Actions workflow (`.github/workflows/release.yml`) plus operator-driven version and changelog cuts documented below |
| **Craft config** | Not added — rejection rationale captured here instead |

Craft is a strong fit for multi-artifact SDK monorepos (npm + PyPI + Docker + mobile
targets, release branches, artifact fetch from CI). **tripll** is a single Python package
built with **hatchling** / **uv**, installed today via **clone + `make setup`**, not PyPI.
The existing tag workflow already covers build + GitHub Release; adding Craft would introduce
a parallel toolchain and changelog policy without reducing operator toil.

## Craft evaluation (W3.1)

### tripll release needs

| Need | Current state |
| --- | --- |
| Version source | Static `[project].version` in `pyproject.toml` (SemVer) |
| Changelog | [Keep a Changelog](https://keepachangelog.com/) in `CHANGELOG.md`; cut rules in [`docs/skw/CHANGELOG-STANDARDS.md`](../skw/CHANGELOG-STANDARDS.md); CI gate `make changelog-check` |
| Build | `uv build` (wheel + sdist via hatchling) |
| Pre-release gate | Full merge gate: `make check` (lint, typecheck, log-redact, tests) |
| GitHub Release | Tag push `v*` → `.github/workflows/release.yml` → attach `dist/*`, auto release notes |
| PyPI | **Not published** — README documents clone install; workflow has opt-in `uv publish` stub |
| Operator control | Releases require explicit operator approval (tag push + merge gate); no auto-publish |

### Craft capabilities reviewed

Craft ([docs](https://craft.sentry.dev/)) provides:

- `craft prepare` / `craft publish` with release-branch workflow
- Auto version bumps from conventional commits (`craft prepare auto`)
- Built-in changelog policies (conventional-commit driven)
- Multi-target publishing (`github`, `pypi`, `npm`, `docker`, …) from `.craft.yml`
- CI artifact download and coordinated publish

Craft detects hatch projects and can bump `pyproject.toml` when `minVersion >= 2.21.0` and a
`pypi` target is configured.

### Fit assessment

| Criterion | Craft | tripll posture | Verdict |
| --- | --- | --- | --- |
| Single Python wheel | Supported (`pypi` target) | Already covered by `release.yml` | Neutral |
| Custom Keep a Changelog + `changelog-check` | Auto/conventional policies; overlaps custom gate | Deterministic + advisory LLM eval owned by SKW | **Mismatch** |
| Clone-only install (no PyPI yet) | Value peaks at multi-registry publish | PyPI stub commented out | **Low value now** |
| Operator HITL on release | Designed for automated publish after CI | Explicit operator tag push required | **Mismatch** |
| Toolchain | Node binary or `npm i -g @sentry/craft` | Python-first (`uv`, Make) | **Extra dependency** |
| Release branches | Default Sentry workflow | Trunk-based; tag on `main` after merge | **Process friction** |
| Makefile / `make check` gate | `preReleaseCommand` hook possible | Canonical gate already in workflow | Redundant |

### Recommendation (W3.2)

**Reject Craft adoption** for tripll. Revisit only if all of the following become true:

1. tripll publishes to **PyPI** (or additional registries) on every release,
2. release cadence justifies automated release-branch management, and
3. changelog policy moves to conventional-commit automation **or** Craft is limited to publish-only with manual changelog cuts.

Until then, extend the existing workflow rather than introduce `.craft.yml`.

## Recommended release process (alternative)

### Prerequisites

- Changes merged to `main` with green `make ci-resume` on the release commit.
- `CHANGELOG.md` `## [Unreleased]` reflects all user-visible changes (see
  [`CHANGELOG-STANDARDS.md`](../skw/CHANGELOG-STANDARDS.md)).
- Operator has permission to push tags on `sevn-bot/tripll`.

### Operator checklist

1. **Choose version** — SemVer from Unreleased content (breaking → MAJOR, features → MINOR,
   fixes-only → PATCH).
2. **Cut changelog** — Move `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`; add fresh
   Unreleased block with six category headings.
3. **Bump version** — Set `[project].version = "X.Y.Z"` in `pyproject.toml`.
4. **Verify locally** — `make check` (same gate the release workflow runs).
5. **Commit** — Conventional commit, e.g. `chore(release): cut vX.Y.Z`.
6. **Tag and push** — `git tag vX.Y.Z && git push origin vX.Y.Z`.
7. **Confirm CI** — [Release workflow](https://github.com/sevn-bot/tripll/actions/workflows/release.yml)
   completes: bootstrap → `make check` → `uv build` → GitHub Release with `dist/*` assets.

**Do not** push a release tag without operator intent. Tag push is the approval boundary.

### What the workflow does

```yaml
# .github/workflows/release.yml (summary)
on:
  push:
    tags: ["v*"]
# → make check → uv build → softprops/action-gh-release (dist/*, generate_release_notes)
```

PyPI publish remains **commented out**. Enable only after configuring PyPI Trusted Publishing
(OIDC) for `sevn-bot/tripll` and adding `id-token: write` to workflow permissions.

### Future PyPI opt-in (not active)

When the operator decides to publish:

1. Configure PyPI trusted publisher for this repository.
2. Uncomment the `uv publish` step in `.github/workflows/release.yml`.
3. Document the first manual verification release in this runbook.
4. Re-evaluate Craft **only if** multi-target publish complexity grows beyond a single
   `uv publish` step.

## Related docs

| Doc | Purpose |
| --- | --- |
| [`docs/skw/CHANGELOG-STANDARDS.md`](../skw/CHANGELOG-STANDARDS.md) | Changelog format, Unreleased policy, release cut rules |
| [`.github/workflows/release.yml`](../../.github/workflows/release.yml) | Tag-triggered build and GitHub Release |
| [`CONTRIBUTING.md`](../../CONTRIBUTING.md) | Conventional Commits (subjects enforced by hook) |
| [`docs/runbooks/operator-runbook.md`](operator-runbook.md) | Day-to-day tripll operation (separate from package release) |

## Issue close criteria (#65)

- [x] Craft evaluated against tripll release needs — **reject** with rationale above.
- [x] Recommended process documented — tag workflow + operator checklist.
- [x] Craft config stub — **not applicable** (rejected); alternative documented instead.

Final wave may draft the GitHub issue close comment; merging and closing remain operator actions (D15).
