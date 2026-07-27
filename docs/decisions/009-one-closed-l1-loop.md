# ADR 009 — One closed L1 loop end-to-end (R10)

**Status:** Accepted (2026-07-26, Wave W0)  
**Decisions:** R10

## Context

`loops/l1_outer.py` and `loops/l1_pr.py` emit dispatch state without invoking adapters.
Investigate/fix nodes return dicts only (L1-scaffold). The audit expects at least one
honest L1 path — PR investigate → fix with real agent calls — not multiple stubbed loops
that look wired in docs but never dispatch.

Schedule pressure at the tail of a long remediation plan historically defers hard wiring;
R10 rejects that pattern for the one loop tripll must prove.

## Decision

1. **W9 wires one real path end-to-end** behind the `graph` extra: PR investigate → fix
   through `dispatch_bridge` with adapter invocation asserted by tests.
2. **Execute W9 immediately after W7**, not at plan tail, so exit wiring and L1 closure
   share the same Engine context before docs waves describe behaviour.
3. **Breadth over depth.** One closed loop beats two stubbed loops. A second L1 loop is
   out of scope for this plan.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Ship multiple partial loops | Docs claim coverage; none dispatch — worse than one honest path |
| Defer L1 wiring to post-remediation | Same schedule pressure R10 guards against |
| Wire loops without the `graph` extra gate | Hides dependency on code-graph features not installed in base installs |

## Consequences

- W9 adds `loops/dispatch_bridge.py` and turns W1.12 green via fake-adapter assertions.
- W12 docs describe W9's actual scope only after W9 lands.
- Human merge gate at the PR loop end stays mandatory (D15 / Thermos).
