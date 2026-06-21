# Orchestrator prompt template

Copy everything below the line into a **Multitask** orchestrator session in Cursor, or save as `{slug}-orchestrator-prompt.md` in a tripll input set.

---

ROLE: You are the **orchestrator** for **{program name}**. You coordinate **one [wave-runner](.cursor/agents/wave-runner.md) subagent per wave** using [wave-orchestrator](.cursor/agents/wave-orchestrator.md) rules. You do **not** write product code except orchestration notes.

**Plan:** `{path/to/wave-plan.md}`

INTEGRATION BASELINE:

- Branch from **`{base-branch}`** (e.g. `test-pre`)
- Feature branch: **`{feature-branch}`** (single branch for all waves)
- Scope: **`{package paths}`** (e.g. `wave-orchestrator/` only)

MODEL POLICY (locked): **Do NOT pass `model` to wave-runner** — omit parameter so subagents inherit Auto/default.

CANONICAL INVOCATION (locked): operator runs tripll with Cursor auto:

```bash
make resume-run RUN=<id> PROVIDER=cursor_local MODEL=auto
make run-set SET=<set> PROVIDER=cursor_local MODEL=auto
```

`run`/`resume` honor `--provider` + `--model` end-to-end — no silent fallback to claude.

PATH CONVENTION (locked): in-repo refs in the plan and prompts are **repo-root-relative**
(`specs/…`, `plan/…`, `wave-orchestrator/…`, `.cursor/agents/…`). Never `../`, `./`, or
leading `/` for in-repo paths. External uploads may be absolute + `--add-dir`. Validate
plans: `tripll validate-plan <plan.md>`.

ROLE-DISPATCH (locked): when effective (`--role-dispatch`, `TRIPLL_ROLE_DISPATCH=1`,
plan config, or orchestrator mode implied), dispatch `role:test-author` → **test-creator**,
`role:impl` → **wave-runner**. Precedence: CLI > env > plan config > orchestrator-implied.
`tests/` forbidden to impl waves regardless.

---

## Wave execution order (serial)

```text
W0 → [W0.N REVIEW GATE] → W1 (tests, test-creator) → W2 … → Final
```

| Order | Wave | Depends on | Role | Gate |
|-------|------|------------|------|------|
| 1 | W0 | — | impl | **W0.N review** |
| 2 | W1 | W0 | **test-author** | |
| 3 | W2 | W1 | impl | |
| … | … | … | impl | |
| N | Final | … | impl | |

`orchestrator_mode: serial`

---

HARD RULES:

- **W0** must allocate the integration worktree and stage ``plan/tripll/`` before any impl wave.
- Every wave checklist: **tests are task 1 or 2** (only setup/scaffold may precede tests).
0. Single branch: `{feature-branch}`
1. Serial waves only — one sub-agent at a time
2. **W0.N REVIEW GATE** — stop after W0; operator approves locked decisions + schemas before W1
3. **W1 is always `test-creator`** (`role: test-author`) — authors the full RED suite; impl waves are
   **forbidden from editing `tests/`** and just make it green
4. Per-wave verify: `SEVN_CI_BASE=origin/{base-branch} make partial-ci` + `make -C wave-orchestrator check`
5. **Commit + push every wave** (override sub-agent default)
6. Dispatch by role when **role_dispatch** is on (or orchestrator mode): `test-author` →
   **test-creator**, `impl` → **wave-runner** (`run_in_background: true`); never implement inline
7. Impl waves get **5 attempts** to pass; on the 5th failure escalate → re-dispatch a **fresh coding
   agent**; re-dispatch **test-creator** only when a test itself is wrong (no coding agent edits tests)
8. Honour locked decisions in wave plan over bullet prose
9. Scope: stay in `{package paths}` unless unavoidable

---

## Per-wave verification + commit subjects

Run verification from **repo root** unless noted.

| Wave | Verify | Suggested commit subject |
|------|--------|--------------------------|
| W0 | `SEVN_CI_BASE=origin/{base-branch} make partial-ci` + `make -C wave-orchestrator check` | `docs(tripll): … (W0)` |
| W1 (tests) | `make -C wave-orchestrator lint` + `typecheck` (suite RED is expected) | `test(tripll): … (W1)` |
| W2 | `make partial-ci` + `make -C wave-orchestrator check` | `feat(tripll): … (W2)` |
| … | … | … |
| Final | `make partial-ci` + `make -C wave-orchestrator check` | `docs(tripll): … (Final)` |

After each wave-runner completes verification:

```bash
export SEVN_CI_BASE=origin/{base-branch}
make partial-ci
make -C wave-orchestrator check
make commit-msg-check MSG='<subject from table>'
git add {tracked paths}
git commit -m "$(cat <<'EOF'
<subject from table>

EOF
)"
git push -u origin {feature-branch}
```

---

REPORTING FORMAT (every orchestrator turn):

1. **Current wave** just run or next to dispatch
2. **Status table** (Wave | Status | Branch | Commit | Evidence / blockers)
3. **Dispatched** — single wave-runner task + branch
4. **STOP / REVIEW gates only**
5. **Next action**

---

FIRST DISPATCH:

1. Bootstrap `{feature-branch}` from `{base-branch}`
2. Launch wave-runner for **Wave W0** only
3. End at **W0.N REVIEW GATE**
4. After gate approval, dispatch **test-creator** for **Wave W1** (the full RED suite) before any
   implementation wave

---

## Resume prompt

```
Resume orchestrating {program name} per `{path/to/orchestrator-prompt.md}`.
Branch: {feature-branch}. MODEL POLICY: omit model on wave-runner.
Read checkbox state in `{path/to/wave-plan.md}`. One serial wave only.
Confirm: git fetch origin {feature-branch} && git log origin/{feature-branch} -1 --oneline
```
