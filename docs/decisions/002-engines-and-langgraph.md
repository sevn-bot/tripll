# ADR 002 — Engines and LangGraph seam

**Status:** Accepted
**Date:** 2026-07-25
**Decisions:** P4, P5, P6, P7 (D5, D6, D7, D8)

## Context

tripll's async `Engine` is a proven batch dispatcher with ledger-backed state, scope checks, and HITL
gates. skw (`src/tripll/skw/`) uses LangGraph for cyclic pipelines (validate → waves → verify → commit →
review). L1 needs conditional/cyclic control (PR fix loop, recovery) without breaking the linear
batch path or requiring API keys for model work.

## Decision

1. **Dual engines with a clean seam** (P4/D5). tripll's engine remains the process supervisor and
   adapter dispatcher. LangGraph owns cyclic/conditional flow behind the optional `graph` extra.
   `thread_id == run_id`; checkpoints use `AsyncSqliteSaver` with `durability="sync"` for
   gate-bearing loops.
2. **Graceful degradation** (P5). Without langgraph installed, the linear batch path runs unchanged.
   Plans requiring cyclic control **fail fast** with an explicit error naming the missing extra.
3. **CLI-only LLM** (P6/D7). All model work goes through existing CLI adapters (`claude -p`,
   `cursor-agent --print`). No in-process LLM, no pydantic-ai, no API keys in v1. Bulk semantic
   extraction uses batched CLI turns.
4. **LangChain as transitive only** (P7/D8). `langchain-core` is accepted as a LangGraph transitive
   dependency. We do not build on LangChain chains or retrievers. `LANGSMITH_*` env vars remain
   unset; documented in `.env.example`.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| LangGraph-only runtime | Loses tripll's concurrent batch scheduler, scope breach handling, and ledger-first recovery |
| In-process pydantic-ai / API keys | Breaks flat-rate-subscription property; adds secret management to v1 |
| LangChain retrievers for graph queries | Retrieval is SQL against our own graph; adds egress and abstraction leak |
| Mandatory langgraph dependency | Forces install weight on operators who only run linear wave plans |

## Consequences

- W6 adds `loops/` package and `graph` extra in `pyproject.toml`.
- `MemorySaver` in absorbed skw code is replaced with durable SQLite checkpoints (W5/W6).
- Operators install `[graph]` only when running cyclic plans (PR loop, skw pipeline).
- LangSmith telemetry disabled by default; no new outbound telemetry surface.
