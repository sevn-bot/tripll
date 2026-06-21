# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial standalone release of **tripll**, extracted from the sevn.bot
  `wave-orchestrator/` subtree.
- Optional Logfire/OpenTelemetry observability (`obs` extra, `tripll.obs`).
- GitHub Actions CI (lint + typecheck + test + build) and tag-triggered release workflow.

### Changed
- Renamed package, CLI, and env prefix from `waveorch` / `WAVEORCH_*` to
  `tripll` / `TRIPLL_*`.
- `TRIPLL_REPO_ROOT` no longer defaults to the parent directory; the target repo is the
  current working git root (override with `TRIPLL_REPO_ROOT`).

[Unreleased]: https://github.com/sevn-bot/tripll/commits/main
