# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Harness pillars under `src/tripll/harness/` — 13-field `EnvFingerprint`, reset receipts,
  outcome contracts with `unverified` wave state, pre-commit reconciliation, and 8-layer tool
  boundary with isolated verifier dispatch (D16/D17).
- `src/tripll/loops/idempotency.py` — idempotency keys, decide/commit split, destructive retry refusal.
- `src/tripll/serve/handoff.py` — 10-field handoff block integrated into dispatch briefs.
- LangGraph control plane under `src/tripll/loops/` (`graph` extra): durable
  `AsyncSqliteSaver` checkpoints (`thread_id == run_id`, `durability="sync"`),
  L1 outer loop seam, all eight loop exits, ledger-backed recovery, and checkpoint TTL purge.
- Absorbed **spec-kit-wave** as `src/tripll/skw/` — doc validators (`spec`, `prd`, `changelog`),
  LangGraph wave pipeline, prompt templates, and skills; unified CLI (`tripll spec|prd|changelog|doc-score`,
  deprecated `skw` / `tripll skw` alias).
- Plan format v3 (`waveorch_format = 3`) with typed `depends_on`, per-wave `targets` and
  `[waves.outcome]` contracts; v1/v2 compat readers; compile-time fake-edge, stop-rule, and
  one-writer shape checks; task-graph compiler with cross-layer `TARGETS` edges.
- Deterministic code KG extractors (`ast_python`, `tests_cov`, `specs_docs`, `make_ci`), batched
  semantic extraction (`IMPLEMENTS`, `ABOUT`), fusion with reversible merges, quality gate, and
  `tripll graph extract|fuse|gate|query` CLI subcommands.
- SQLite graph store (`GraphStore` port, three-layer ontology, task-layer sync alongside ledger).
- Initial standalone release of **tripll**, extracted from the sevn.bot
  `wave-orchestrator/` subtree.
- Optional Logfire/OpenTelemetry observability (`obs` extra, `tripll.obs`).
- GitHub Actions CI (lint + typecheck + test + build) and tag-triggered release workflow.

### Changed
- `langgraph` moved from core dependencies to the optional `graph` extra; dev/CI sync
  installs `--extra graph`. Linear batch runs work without it; cyclic plans fail fast.
- `graph.CW_HOTSPOTS` is derived from plan-corpus replay (legacy buckets retained as reference);
  `docs/wave-plan-template.md` rewritten for format v3.
- Renamed package, CLI, and env prefix from `waveorch` / `WAVEORCH_*` to
  `tripll` / `TRIPLL_*`.
- `TRIPLL_REPO_ROOT` no longer defaults to the parent directory; the target repo is the
  current working git root (override with `TRIPLL_REPO_ROOT`).

[Unreleased]: https://github.com/sevn-bot/tripll/commits/main
