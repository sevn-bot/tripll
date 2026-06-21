# tripll orchestrator mode — W0 smoke slice

**Purpose:** Minimal input set for `make validate-set SET=orchestrator-mode-smoke` and
orchestrator-mode parity smoke (terminal + dashboard status table). Full program plan:
[`plan/tripll-orchestrator-mode-wave-plan.md`](../../../../plan/tripll-orchestrator-mode-wave-plan.md).

orchestrator_mode: serial

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Docs | `wave-orchestrator/docs/` |
| Agents | `.cursor/agents/wave-orchestrator.md` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets |
|---------|-------|------------|-------------|--------|----------------|
| W0 | Orchestrator mode design + agent definition | | yes | M | make check |

## tripll batches

| batch_id | waves | human_gate | parallel |
|----------|-------|------------|----------|
| Pre-0 | W0 | yes | no |

---

## Wave W0 — Orchestrator mode design (review gate)

- [ ] **W0.1** Validate orchestrator mode activates from prompt + plan (smoke slice).
