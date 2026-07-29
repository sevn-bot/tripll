# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Live injection completion (L2-W5): `POST /api/runs/{id}/reconcile-graph`, `--force-after-drain`
  on inject/reconcile CLI and API, dashboard hotfix badge + SSE inject/reconcile timeline refresh.
  `[waves.outcome.reference]` + `[waves.outcome.quality_gauntlet]` schema, agent contracts
  (`quality-critic`, `smoothing-pass`, `reference-picker`), and harness contract parsers.
- W13 config spine: `tripll.toml` + user config (`~/.config/tripll/config.toml`), `tripll setup`,
  `tripll doctor`, four-layer config precedence, packaged v3 wave-plan template, and wheel
  packaging guard for templates/rules/prompts.
- P0 gate restoration: CI job timeout (20m), Python 3.12 pin in bootstrap, `sync` prereqs on
  `make lint`/`make typecheck`, plan self-hosting (`[pipeline] creates` validate-plan exemption),
  `human_gates` config (`prompt` | `auto_accept` | `fail`) with tier-4 CI canary parking, and
  per-wave stop-rule threshold (SHAPE-01).
- Final L1 gate: xfail sweep complete (0 `green after W*` xfails); W3 CSRF auth-success tests
  green; CAP-01 tier2 probe skipped; `make ci` green twice on branch head.
- W12 docs and operator guides: L1 design-note §0 (task graph, `unverified`, exits, ledger vs
  checkpoint), control-plane §12 (LangGraph seam), `docs/ontology.md`, `docs/harness-checks.md`,
  PR-loop runbook, updated `about-tripll` architecture page.
- Dashboard L1 panels on run detail — graph subgraph, findings by state, exit caps (§12).
- pullfrog-py CI (`.github/workflows/pullfrog.yml`), `.pullfrog/config.yaml`, `make review`,
  and `pullfrog-ref-check` pin parity gate.
- Code factory L1 agent roster (design §11): `spec-cartographer`, graph pipeline agents
  (`graph-extractor`, `graph-librarian`, `graph-fuser`), plan agents (`plan-author`,
  `plan-shape-critic`), PR loop agents (`ci-investigator`, `check-fixer`,
  `review-comment-triager`, `review-comment-fixer`, `pr-shepherd`), and `implementer` as
  successor to `wave-runner`; hardened `wave-verifier` (D17); inherited harness preamble on
  all agents; `tests/test_agent_roster.py` + spec-cartographer fixture e2e stub.
- Graph-packed brief under `src/tripll/serve/brief_packer.py` — TARGETS seeds, 2-hop
  subgraph, finding paths, triple tables with provenance, token spill-to-file; integrated
  into dispatch briefs with `--grep-brief` A/B flag (D23).
- Frozen benchmark suite under `bench/{tasks,baselines,METRICS.md}` and
  `tripll bench run` for metric deltas vs baseline; D23 verdict recorded in
  `docs/graph-serving.md`.
- PR phase under `src/tripll/github/pr.py` and `src/tripll/loops/l1_pr.py` — idempotent
  push/open/comment/resolve/merge commit nodes, CI and review fix loop with fan-out dispatch,
  wired loop exits, human merge gate (never auto-merge), and `tripll pr shepherd|status|approve-merge`
  CLI plus dashboard API routes.
- GitHub ingestion under `src/tripll/github/` — check-runs and review threads normalize
  into `Finding` nodes with dedup, `ABOUT` resolution, staleness via `valid_to_sha`, and
  rejected-finding export to `.pullfrog/learnings.md`; `tripll findings sync|list|triage` CLI.
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
- Dispatch briefs default to graph-packed context instead of the legacy no-exploration
  directive; grep briefs remain available via `--grep-brief`.
- `langgraph` moved from core dependencies to the optional `graph` extra; dev/CI sync
  installs `--extra graph`. Linear batch runs work without it; cyclic plans fail fast.
- `graph.CW_HOTSPOTS` is derived from plan-corpus replay (legacy buckets retained as reference);
  `docs/wave-plan-template.md` rewritten for format v3.
- Renamed package, CLI, and env prefix from `waveorch` / `WAVEORCH_*` to
  `tripll` / `TRIPLL_*`.
- `TRIPLL_REPO_ROOT` no longer defaults to the parent directory; the target repo is the
  current working git root (override with `TRIPLL_REPO_ROOT`).

[Unreleased]: https://github.com/sevn-bot/tripll/commits/main
