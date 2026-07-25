# ADR 005 — Scope, benchmarks, and L2 seams

**Status:** Accepted
**Date:** 2026-07-25
**Decisions:** P17–P22 (D18, D23, D24, D25)

## Context

L1 must prove the graph earns its keep before L2/L3 work begins. Multi-language extraction,
auto-tuning metrics, and full L2 implementation are out of scope. v1 needs frozen benchmarks,
telemetry seams, and a clear extraction boundary.

## Decision

1. **Graph must pay** (P17/D23). W10 benchmarks graph-packed brief vs grep-brief on frozen tasks.
   Metrics: first-attempt pass rate and tokens-to-green. If graph brief loses, revert the packer;
   keep the graph for telemetry only.
2. **L2/L3 not implemented** (P18). Only §9.6 seams ship: `AgentDef`/`PromptDef` hashes,
   `EnvFingerprint`, `Verdict`/`Escalation`/`Finding` persistence, reserved `Metric`/`Hypothesis`/
   `Experiment` kinds, and `bench/` with ≥3 tasks + baseline.
3. **Goodhart gate** (P19/D24). `bench/METRICS.md` and `bench/tasks/` are frozen artifacts for this
   program. Changing them is out of scope for every wave here; metric changes are L3 decisions.
4. **Python AST only in v1** (P22). Deterministic extractors cover Python via AST. Other languages
   get semantic-only fallback and an open question (design §15.4).
5. **Model freeze** (D25). While classifying a failure, the model is frozen and exactly one system
   component varies per trial.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Ship graph brief without benchmark | No evidence it beats grep; risks token waste and wrong-context failures |
| tree-sitter multi-language in v1 | Scope explosion; semantic fallback sufficient for bootstrap |
| Mutable benchmark suite mid-program | Goodhart risk — optimising to moving targets |
| Build L2 optimizer in L1 program | Distraction; seams only until L1 metrics justify L2 |

## Consequences

- W10 creates `bench/tasks/`, `bench/baselines/`, and `bench/METRICS.md` (frozen at creation).
- W3 ships `extract/ast_python.py` only for deterministic code edges; other langs deferred.
- W11 agent roster includes `spec-cartographer` with Python-first extraction path.
- Repo→spec bootstrap (D18) produces specs folder + KG snapshot; no L2 auto-promotion.
