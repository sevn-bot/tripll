# Rules and calibration runbook

Operator guide for the **compounding loop**: derived rules, finding promotion, executable
structural checks, and calibration reports. Agents may **propose** rules; **only an operator
activates them** (R27).

## Quick reference

| Task | Command |
|------|---------|
| Derive rules from evaluation | `tripll rules derive` |
| List rules | `tripll rules list` |
| Promote proposed → active | `tripll rules promote <rule_id>` |
| Retire a wrong rule | `tripll rules retire <rule_id>` |
| Run executable rules gate | `make rules-check` |
| Score predictions vs ledger | `tripll calibrate --run <run-id>` |
| Publish plan to tracker | `tripll plan publish <plan.md> --tracker github --parent <ref>` |

Config lives in repo `tripll.toml` under `[rules]` (see
[`docs/decisions/014-rules-as-graph-nodes.md`](../decisions/014-rules-as-graph-nodes.md)).

---

## Derive rules (`tripll rules derive`)

Brownfield onboarding (`tripll init`) writes `docs/evaluation-<date>.md` with file:line
evidence. Derivation turns those findings into **proposed** rules and scoped context modules:

```bash
cd ~/code/my-project
tripll rules derive              # writes .tripll/rules/ and .tripll/context/
tripll rules derive --force      # overwrite existing markdown
```

Every derived rule must cite a resolving `origin` (`codebase://…` or `finding://…`). Rules
with `[rules].enabled = false` skip derivation.

**When to run:** after `tripll init`, when the evaluation changes, or when you want to refresh
context modules from the current codebase assessment.

---

## Propose from a finding

When a wave resolves a defect, the postmortem path may propose a durable rule automatically
(`[rules].auto_propose = true`). You can also sync findings and inspect proposals:

```bash
tripll findings sync --pr <n>
tripll findings list
tripll rules list --state proposed
```

Proposed rules **do not pack** into agent briefs until an operator promotes them (R27).

---

## Promote and retire (operator-only, R27)

```bash
tripll rules promote no-stdlib-logging
tripll rules list --state active
tripll rules retire no-stdlib-logging   # when superseded or wrong
```

Promotion is intentionally **not** exposed to agent backends. An agent that can activate its
own constraints will eventually write one that excuses its own failure.

After promotion, the rule renders under `.tripll/rules/<rule_id>.md` (committed) and packs into
future briefs within `[rules].pack_budget_tokens`.

---

## Make a rule executable

Executable rules fail `make rules-check` instead of relying on brief prose (R29). Add front
matter to an **active** rule:

```yaml
---
rule_id: no-stdlib-logging
state: active
origin: codebase://about-tripll/_standards/coding-standards.md:271
scope:
  - "src/tripll/**"
executable: ast-grep
severity: error
pattern: import logging
---
```

Then:

```bash
make rules-check    # exit 0 on clean tree; non-zero on violation
```

If `ast-grep` is absent from PATH, the gate **degrades** to prose-only with exit 0 and a
warning — CI still passes, but structural enforcement is off until the tool is installed.

Wave attempts also report structural scope breaches through `harness/boundary.py` using the
same executable-rules engine.

---

## Read a calibration report

At compile time each wave gets a **predicted** first-pass probability. After the run:

```bash
tripll calibrate --run <run-id>
```

Example output:

```text
Calibration — 20260729-abc123
Predictor: tripll.calibrate.predict:v1

Wave                     Predicted  Actual (1st pass)  Attempts to green
-----------------------  ---------  -----------------  -----------------
W2                       0.620                  1                  1

Brier score: uncalibrated (prior runs=0, need 3)
```

- **Uncalibrated** — fewer than three prior runs in history; routing and gates are unchanged
  (R28 advisory-only).
- **Brier score** — lower is better once enough history exists.

Calibration never changes dispatch routing, model choice, attempt budget, or human gates.

---

## When a rule turns out wrong

This is the case operators hit most often.

1. **Retire immediately** — do not leave a wrong rule active:

   ```bash
   tripll rules retire <rule_id>
   ```

2. **Fix the source** — if the rule came from a finding, resolve or reject the finding in the
   tracker so it is not re-proposed on the next sync.

3. **Add a replacement** — derive or hand-write a corrected rule with a fresh `origin` citing
   the real constraint (`file:line` or `finding://…`). Keep it `proposed` until reviewed.

4. **Promote the replacement** — only after you trust it:

   ```bash
   tripll rules promote <new-rule-id>
   ```

5. **Verify the gate** — for executable rules, run `make rules-check` on a clean tree and plant
   a violation locally to confirm the pattern still catches the defect.

6. **Check brief packing** — start a dry-run dispatch or inspect the packed brief to confirm
   the retired rule no longer appears and the replacement is scoped correctly.

If `make rules-check` fails in CI but the rule is wrong (false positive), **retire first**, then
adjust the pattern or scope before re-promoting.

---

## Plan publish (tracker round trip)

Publish a wave-plan breakdown to GitHub (requires `--parent` epic ref):

```bash
tripll plan publish docs/plans/my-plan.md --tracker github --parent 42 --dry-run
tripll plan publish docs/plans/my-plan.md --tracker github --parent 42
```

The second run is idempotent — it creates nothing new when tickets already exist.

---

## Related docs

- [`docs/decisions/014-rules-as-graph-nodes.md`](../decisions/014-rules-as-graph-nodes.md) — R26, R27
- [`docs/decisions/017-executable-rules.md`](../decisions/017-executable-rules.md) — R29
- [`docs/harness-checks.md`](../harness-checks.md) — structural scope breach
- [`docs/plans/ai-layer-compounding.md`](../plans/ai-layer-compounding.md) — full compounding design
- Product diagram: [`about-tripll/assets/pipeline.html`](../../about-tripll/assets/pipeline.html)
