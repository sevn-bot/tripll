# Orchestrator mode — example input set

Minimal **W0-only** slice for orchestrator-mode smoke and operator onboarding. Pair with
the orchestrator prompt file in this directory; the engine activates orchestrator mode when
both files are present (design-note §8.2, D1).

**Full program** (W0→Final): copy from repo [`plan/tripll-orchestrator-mode-wave-plan.md`](../../../../plan/tripll-orchestrator-mode-wave-plan.md) and
[`plan/tripll-orchestrator-mode-orchestrator-prompt.md`](../../../../plan/tripll-orchestrator-mode-orchestrator-prompt.md).
Implementing teams should follow the orchestrator prompt at
[`plan/tripll-orchestrator-mode-orchestrator-prompt.md`](../../../../plan/tripll-orchestrator-mode-orchestrator-prompt.md).

**Golden parse reference** (dashboard UI program): [`plan/tripll-dashboard-ui-orchestrator-prompt.md`](../../../../plan/tripll-dashboard-ui-orchestrator-prompt.md).

## Files in this directory

| File | Role |
|------|------|
| `tripll-orchestrator-mode-wave-plan.md` | v1 execution graph (W0 smoke slice) |
| `tripll-orchestrator-mode-orchestrator-prompt.md` | Serial order, verify, REPORTING FORMAT |

## Install into `runs/input/`

From **`wave-orchestrator/`**:

```bash
make seed-orchestrator-smoke-set    # copies this folder → runs/input/orchestrator-mode-smoke/
make validate-set SET=orchestrator-mode-smoke
make plan-set SET=orchestrator-mode-smoke
```

Or copy manually:

```bash
mkdir -p runs/input/orchestrator-mode-smoke
cp docs/examples/orchestrator-mode-input-set/* runs/input/orchestrator-mode-smoke/
```

## Run (headless orchestrator mode)

Single integration branch, serial waves, `wave-runner` dispatches (D8, D9):

```bash
make run-set SET=orchestrator-mode-smoke PROVIDER=cursor_local MODEL=auto
# Stops at Pre-0 / W0.8 review gate — resolve pre0-decisions.md, then:
make finish-pre0 RUN=<run-id> PROVIDER=cursor_local MODEL=auto
```

Monitor Multitask-style status:

```bash
make status-watch RUN=<run-id>       # Orchestrator block + per-node table (D12)
make orchestrator-watch RUN=<run-id> # tail orchestrator-status.md only
make serve                           # dashboard Orchestrator panel (control-plane §11)
```

Optional headless gate agent at review pause: `TRIPLL_ORCHESTRATOR_AGENT=1` (see operator runbook).

## Automated smoke

```bash
make smoke-orchestrator-w0          # validate + plan + pytest parity check
```

Manual checklist (Final.4): after W0 completes (or seeded fixture run), confirm **the same**
`| W0 |` row appears in:

1. `runs/.../<run-id>/orchestrator-status.md` → `## Status table`
2. `make status-watch RUN=<run-id>` → `── Orchestrator ──` block
3. Dashboard run detail → **Orchestrator** panel (below run header)
