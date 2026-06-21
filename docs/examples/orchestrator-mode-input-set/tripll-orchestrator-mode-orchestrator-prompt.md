# tripll orchestrator mode — orchestrator prompt (W0 smoke slice)

Canonical full prompt for implementing teams:
[`plan/tripll-orchestrator-mode-orchestrator-prompt.md`](../../../../plan/tripll-orchestrator-mode-orchestrator-prompt.md)

---

Feature branch: **`feature/tripll-orchestrator-mode`**

MODEL POLICY (locked): **Do NOT pass `model` to wave-runner** — omit parameter so subagents inherit Auto/default.

---

## Wave execution order (serial)

```text
W0 → [W0.8 REVIEW GATE]
```

| Order | Wave | Depends on | Gate |
|-------|------|------------|------|
| 1 | W0 | — | **W0.8 review** |

---

HARD RULES:

0. Single branch: `feature/tripll-orchestrator-mode`
1. Serial waves only — one wave-runner at a time
2. **W0.8 REVIEW GATE** — stop after W0; operator approves before W1
3. Per-wave verify: `SEVN_CI_BASE=origin/test-pre make partial-ci` + `make -C wave-orchestrator check`
4. Delegate to **wave-runner** only; never implement inline

---

## Per-wave verify and commit

| Wave | Verify | Suggested commit |
|------|--------|------------------|
| W0 | partial-ci | `docs(tripll): orchestrator mode W0 smoke` |

---

REPORTING FORMAT (every orchestrator turn):

1. **Current wave** just run or next to dispatch
2. **Status table** (Wave | Status | Branch | Commit | Evidence)
3. **Dispatched** — single wave-runner task
4. **STOP / REVIEW gates only**
5. **Next action**
