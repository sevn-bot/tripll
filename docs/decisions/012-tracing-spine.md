# ADR 012 — Tracing spine consolidation

**Status:** Accepted (2026-07-26, Wave P3)  
**Decisions:** R21 (capture policy), R22 (one configurator, one hide-list)

## Context

tripll had two independent Logfire configurators (`tripll.obs` gated on `LOGFIRE_TOKEN`,
`tripll.skw.tracing` gated on `SKW_TRACE` / `skw.toml`), no local trace sinks, and
`instrument_httpx(capture_all=True)` that could ship auth headers and bodies. Agent dispatch —
the single adapter seam shared by every backend — emitted no spans.

## Decision

1. **One configurator:** `tripll.obs.configure_observability` is the only `logfire.configure`
   call site. It wires scrubbing from `config/log-hide-keys.toml`, httpx with
   `capture_all=False`, pydantic-ai instrumentation, optional Logfire cloud/self-hosted/OTLP
   exporters, and stores the resolved `[tracing]` config for local sinks.

2. **Local sinks always available:** When tracing is enabled, JSONL + SQLite writers under
   `runs/processing/<run-id>/traces/` persist span events without any cloud token.

3. **Span taxonomy at dispatch seams:** `tripll.run`, `tripll.wave`, and
   `tripll.agent.dispatch` spans carry `run_id`, `node_id`, and `attempt_id` for ledger
   correlation — no schema migration.

4. **Capture policy (R21):** `capture = "shape"` is the default; prompt/completion text is
   never recorded unless an operator opts into `full`.

5. **SKW forwarder:** `tripll.skw.tracing` keeps its public API but delegates configuration
   to `tripll.obs` and uses Logfire spans only (no second SDK setup).

## Rejected

- **Per-subsystem configurators** — two hide-lists drift (sevn lesson); rejected in R22.
- **Ledger `trace_id` column** — collides with W5/W6 ledger work; join on `attempt_id` instead.
- **Default `capture = full`** — too easy to leak prompts into durable stores.

## Consequences

- W4 OBS-01 re-verifies httpx capture; W4 SEC-07 grows the hide-list and all consumers inherit it.
- SKW mount retirement can delete the forwarder once SKW CLI is removed.
- Operators query `traces/traces.db` beside `ledger.db` for dispatch cost/token parity checks.
