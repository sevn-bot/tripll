# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- [2026-08-03] mergeCraft pin bump (#64 W8): workflow and `MERGECRAFT_REF` pinned to `f369164` (`diff-review --json` available); `tripll review diff --json` forwards structured output; `tripll review load-json` normalizes mergeCraft Finding payloads into tripll schema
- [2026-07-30] Rewrote `README.md` with a numbered 6-step quickstart and a dedicated **Authentication** section (subscription `claude setup-token` / `CLAUDE_CODE_OAUTH_TOKEN` recommended, `ANTHROPIC_API_KEY` fallback). Corrected the install path — tripll is not published on PyPI, so `pip install tripll` / `uv tool install tripll` were removed in favour of clone + `make setup` + `uv run tripll` (also fixed in the `about-tripll/` site sources). `tripll doctor`/`setup` now hint `claude setup-token` for headless auth. Hardened GitHub Actions: SHA-pinned third-party actions and added least-privilege `permissions` to `ci.yml`
- [2026-07-30] God-module extraction (#16, W8): split 22 dashboard routes from `api/ui/router.py` into `api/ui/_routes_{runs,agents,fragments}.py` with shared helpers in `api/ui/_helpers.py`; `make_ui_router()` unchanged surface (no URL or template changes)
- [2026-07-29] Final AI-layer compounding gate: xfail reconciliation (24 removed), `plan` callback accepts interspersed `--runs-root` after W6 subcommand (Typer fix)
- [2026-07-29] **Breaking:** replace pullfrog-py with [mergeCraft@pre-0.0.1](https://github.com/alexhawat/mergeCraft) — workflow `.github/workflows/mergecraft.yml`, config `.mergecraft/`, learnings `.mergecraft/learnings.md`, check `mergecraft-approval`, exit context `review_success`, `make review` / `mergecraft-ref-check`, and `tripll review diff|watch|init|dispatch`. Configurable `[review].posture` (`review_only` default; `fix`/`full` enable mode dispatch)
- [2026-07-29] God-module extraction (#16): run / inject / reconcile-graph CLI commands moved to `tripll.cli._run`; shared helpers to `tripll.cli._shared` (no CLI behavior change)

### Added
- [2026-08-03] Review baseline promotion (#64 W2): `tripll findings promote --to bench/review/baseline.jsonl` emits operator-curated findings with mandatory `provenance` (`human`/`mergecraft`/`ci`) and `requires_context_outside_diff`; D24 Goodhart gate refuses to overwrite a non-empty baseline corpus unless `--force`
- [2026-08-03] Findings LLM noise gate (#64 W1): `baseline_candidate` finding state, `tripll findings gate` (and `findings sync --gate`) flags nits/questions without auto-rejecting; gate precision vs operator triage recorded on Verdict nodes
- [2026-08-03] Nous Research OpenAI-compatible provider (#76): `nous_research` backend with `deepseek/deepseek-v4-flash` default model, `NOUS_API_KEY` / base URL documented in the operator runbook, config under `[providers.nous_research]` (stdlib HTTP — no Nous SDK)
- [2026-07-31] Pipeline charts are now readable at a glance: placement is **serpentine** (row 0 reads left to right, row 1 right to left, …) so a long pipeline turns at the end of each row and returns instead of running off the page, and every edge is routed **orthogonally with rounded 90° corners** — down-edges drop through the gutter above their target row (fanned out when several share it), along-row edges follow that row's inferred reading direction, feedback edges dip below their row, and return edges use a corridor beside the nodes. Decision arms are declarable: `answer = "yes" | "no"` on a transition draws a green ✓ / red ✗ label pill and matching arrowhead, a badge on each node counts how many ways it routes, and optional side paths stay dotted. Charts gained a colour system (per-kind node palette with accent rails and shadows, tinted cluster panels, dot-grid canvas, legend chips) plus hover-to-isolate focus, drag-to-pan, and `+`/`-`/`0` zoom keys
- [2026-07-31] Pipeline files and pipeline charts: `pipeline_format = 1` TOML (`src/tripll/pipeline_spec.py`) declares the steps of an agent pipeline — agent/phase/gate, transitions with conditions, and the artifact state each step produces — and `src/tripll/pipeline_views/` derives two self-contained HTML/SVG charts from any such file: an execution graph (step is node, transition is edge) and a state graph (state is node, edge is the wave plus agent work). Placement comes from the file's `layer`/`column` or is derived from the transitions. `tripll pipeline-view <pipeline.toml> --view execution|state --out <path>`; the L1 pipeline sample and its committed charts live at `docs/examples/pipelines/tripll-l1-pipeline.toml` and `docs/examples/pipeline-{execution,state}-graph.html`. The charts are interactive offline: zoom in/out/fit, click a node for its agent note (`summary`, `harness`, `model`, `[steps.params]` — state nodes list every agent on their incoming edges), and hover an edge for the flow explanation declared in `detail`
- [2026-07-31] Wave-graph HTML view: `src/tripll/graph_html.py` renders a `RunGraph` as a self-contained inline-SVG DAG (wave nodes laid out by dependency depth, one arrow per `depends_on`, review-gate/test-author/batch/effort annotations). `tripll validate --graph-html <path>` emits it after a plan validates; example input set and committed diagram at `docs/examples/wave-graph-input-set/` and `docs/examples/wave-graph.html`
- [2026-07-30] Open-source governance files: `SECURITY.md` (coordinated disclosure via GitHub private vulnerability reporting), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, issue forms (`.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml` + `config.yml` with a security contact link), and a SHA-pinned `.github/workflows/codeql.yml` (Python + Actions) code-scanning workflow
- [2026-07-30] Module-size gate (GOD-06, Final): `scripts/check_module_size.py`, `make module-size-check` wired into `ci-resume` and `ci-affected`; allowlists `inject.py` and `skw/render.py` (not in #16 scope)
- [2026-07-29] Tracker protocol and idempotent plan publish: `src/tripll/trackers/{base,github,publish}.py`, `src/tripll/github/issues.py`, and `tripll plan publish --tracker github --parent <ref>` with pre-read idempotence (R30, ADR 016)
- [2026-07-29] Calibration loop (R28 advisory): `src/tripll/calibrate/{predict,score,routing,sync}.py`, `compile_plan` PREDICTED metrics, `tripll calibrate --run`, REALIZED `attempts_to_green` / `first_attempt_pass_rate`, Brier scoring, and calibration section in `report.md`
- [2026-07-29] Executable structural rules: `src/tripll/rules/executable.py`, committed `.tripll/rules/no-stdlib-logging.md`, `make rules-check` gate wired into `ci-affected` and `ci-resume`, and structural scope breaches via `harness/boundary.py`
- [2026-07-29] Bug-to-rule loop: `Rule` graph nodes (`{repo}#{rule_id}`), wave postmortem, `tripll rules promote|retire|list`, finding→proposed promotion with `finding://` provenance, and active-rules section in learnings export
- [2026-07-29] Derived rules and on-demand context modules: `tripll rules derive`, `.tripll/rules/` + `.tripll/context/` on `tripll init`, origin validator, scoped brief packing under `[rules].pack_budget_tokens`, and `[rules]` config table
- [2026-07-29] Incremental CI: `make ci-affected` and `make ci-changed` (path-aware partial gate vs `origin/main`; Python ruff/mypy/pytest plus mapped make targets such as `about-site-check` and `log-redact-check`). **`make ci-resume`** is the resumable pre-merge gate (replaces monolithic `make ci`; GitHub Actions and local Final waves)

## [0.0.0] - 2026-07-29
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
