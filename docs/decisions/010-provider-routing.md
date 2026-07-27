# ADR 010 — Provider routing and model identity (R16)

**Status:** Accepted (2026-07-26, Wave P1)

## Context

tripll dispatches waves through multiple agent backends (`claude_code`, `cursor_local`,
`cursor_cloud`). Operators need predictable cost and quality: which provider ran a wave, which
model it used, and what happened when a backend crashed must be auditable from the ledger.

Claude Code exposes `claude --fallback-model`, which silently substitutes a cheaper model on
overload. That is convenient for interactive use but violates wave contracts — a wave that
declared `claude-opus-5` would complete on an unknown model with no ledger record of the swap.

## Decision

1. **Provider and model are declared per wave** in the v3 plan (`provider`, `model`,
   `reasoning_effort`, `max_budget_usd`). Nothing auto-selects a provider or model from graph
   hints; routing hints (P2) are advisory metadata only.

2. **Failover changes the provider only.** When a wave's primary provider is in cooldown or
   unavailable, tripll re-dispatches on `fallback[0]` and records the switch. The wave's model
   intent is preserved (`auto` → the fallback provider's `default_model`).

3. **`claude --fallback-model` is rejected.** tripll never passes `--fallback-model` to the
   Claude Code CLI. Provider failover is tripll's job; model identity stays declared.

4. **Infra failures are a separate class.** Extension-host crashes (`Couldn't start`,
   `Workspace Disconnected`, empty output on non-zero exit) are classified `infra`. They do not
   consume a wave attempt and do not trip the exit-7 breaker. Adaptive throttle (halving the
   provider pool after repeated infra) is scoped per provider.

5. **Reasoning effort is expressed per provider.** On Claude Code, `reasoning_effort` maps to
   `--effort`. On Cursor, effort rides in the model string (`claude-opus-5-thinking-high` or
   parameterized `claude-opus-5[effort=high]`); no separate flag is emitted.

## Consequences

- Operators configure `[providers.*]` and `[pipeline] default_provider` in v3 plans.
- `grep -rn 'fallback-model' src/tripll` must stay empty.
- MODEL-01 keeps `DEFAULT_MODEL` in `claude_code.py` as the single source of truth for the
  Claude Code default (`claude-sonnet-5` as of 2026-07).
