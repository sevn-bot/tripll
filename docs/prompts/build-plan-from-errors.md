# build-plan-from-errors — agent prompt

W5 driver substitutes `{{…}}` placeholders, appends the **turn problem taxonomy** template,
then dispatches this prompt with agent
[`build-plan-from-errors`](../agents/build-plan-from-errors.md).

---

## Context

| Field | Value |
|-------|-------|
| Run id | `{{RUN_ID}}` |
| Turn bundles folder | `{{BUNDLES_FOLDER}}` |
| Workspace content root | `{{CONTENT_ROOT}}` |
| Error turn ids (this run) | `{{ERROR_TURN_IDS}}` |
| Plan output directory | `{{OUTPUT_DIR}}` |

**D6 — one plan per run:** write exactly **one** `*-wave-plan.md` under
`{{OUTPUT_DIR}}` (`runs/input/from-errors-{{RUN_ID}}/`). If you
would otherwise split work, merge into shared waves instead (**D11**).

**D11 — problem grouping:** cluster turns that share a root cause or a single fix into
**shared waves** by **problem type** (see taxonomy below). Cite **every** contributing
`turn_id` in the wave bullets. Do **not** emit one wave per error turn when one remediation
addresses several.

---

## Task

You are the **build-plan-from-errors** agent. Gateway turns failed or degraded during live
or test traffic; each was captured as a JSONL bundle under `{{BUNDLES_FOLDER}}` with logs,
session messages, and trace spans interleaved.

Diagnose **all turn problems** — not only log/trace errors. Classify every turn against the
full taxonomy, then produce **one** valid **tripll v1** wave-plan that an operator can run
with:

```bash
cd wave-orchestrator
make validate-set SET=from-errors-{{RUN_ID}}
make plan-set SET=from-errors-{{RUN_ID}}
make run-set SET=from-errors-{{RUN_ID}}
```

---

## Step 1 — Explore every error bundle (full streams)

Run from `{{CONTENT_ROOT}}` (directory with `sevn.json`):

```bash
sevn turn-bundle view <turn_id> --section meta
sevn turn-bundle view <turn_id> --section summary
sevn turn-bundle view <turn_id> --stream message
sevn turn-bundle view <turn_id> --errors-only
```

For each `turn_id` in `{{ERROR_TURN_IDS}}`:

1. Read **meta** and **summary** — channel, session, `terminal_status`, error counts.
2. Read the **full message stream** (`--stream message`): operator vs assistant roles, tool
   calls, tool results, empty or missing assistant replies.
3. Run **`--errors-only`** for a compact view of failing log/message/trace rows.
4. Drill into streams when needed:
   - `sevn turn-bundle view <turn_id> --stream log --grep '<pattern>'`
   - `sevn turn-bundle view <turn_id> --stream trace`
5. Cross-check **all three streams** (log + message + trace) before assigning problem types.

**Explorer contract (W3):**

- `<turn_id>` is the full gateway correlation id (e.g.
  `telegram:user=…:session=<hex>:msg=<hex>`).
- Resolution goes through `index.json` → `<safe_turn_id>.jsonl`; missing turns exit with a
  clear error — do not invent bundle contents.
- Output is deterministic plain text, one record per line — agent-friendly for grep and
  diff.
- `--stream` and `--section` are mutually exclusive.
- Valid `--stream`: `log`, `message`, `trace`. Valid `--section`: `meta`, `summary`.

Do **not** skip any turn in `{{ERROR_TURN_IDS}}`.

### Step 1b — Taxonomy checklist (required)

Using the **Turn problem taxonomy** appended below this prompt, fill the **per-turn
checklist** for **every** `turn_id` × **every** problem kind (`log_error` through `other`).

| Focus | streams / signals |
|-------|-------------------|
| `no_answer` | message roles: user without substantive assistant follow-up; log `executor_no_answer`; timeout |
| `wrong_answer` | compare operator message to assistant reply — off-topic, hallucination, contradicts intent |
| `wrong_tool_use` | message `tool_call` kinds, tool result errors, trace tool spans, permission denials, tool loops |
| `triage_routing` | trace triage/executor spans, tier attrs, escalation when inappropriate |
| `channel_delivery` | adapter send failures, partial delivery, missing outbound after assistant |
| `log_error` / `log_warning` / `trace_error` / `terminal_failure` | standard error predicates |

Mark each cell `yes` or `no`; `yes` requires an evidence pointer. Do not proceed to Step 2
until the checklist is complete.

---

## Step 2 — Group by problem type (D11)

After exploring all bundles and completing the taxonomy checklist:

1. List each distinct **problem type** present across the batch (from the checklist), with
   evidence (log line, message id, span).
2. **Group** turns that share the same problem type cluster or would be fixed by the **same
   code change** into one remediation cluster.
3. For each cluster, record:
   - Problem type id(s) (e.g. `wrong_tool_use`, `triage_routing`),
   - Contributing `turn_id`s (all of them),
   - Affected subsystem / file paths (from stack traces, tool names, span attrs),
   - Proposed fix summary in one sentence.

If two turns fail for unrelated problem types, they belong in **separate waves** within the
**same** plan file — still only **one** plan file for the run.

---

## Step 3 — Author the tripll v1 plan

Follow [`docs/wave-plan-template.md`](../wave-plan-template.md) and
[`docs/agents/wave-plan-author.md`](../agents/wave-plan-author.md).

Write the plan to:

`{{OUTPUT_DIR}}/<slug>-wave-plan.md`

Required sections:

1. **Goal** — what remediation ships; what must not regress (gateway turn spine, tracing,
   tripll CLI).
2. **`## Turn problem matrix`** — summary of the Step 1b checklist (turn_id × problem_type
   × present × evidence); or an equivalent decisions table with the same columns.
3. **Files in scope** — table of paths each wave will touch.
4. **Decisions baked into this plan** — lock remediation choices inferred from diagnostics
   (reference contributing `turn_id`s and problem types in decision rows where helpful).
5. **`## tripll execution graph`** with `tripll_format: 1` and valid `depends_on`
   edges.
6. **Per-wave checklist** (`## Wave W0`, …) with `- [ ]` bullets citing files and
   evidence; every problem cluster must map to at least one wave; cite all `turn_id`s in
   the bullets you group.
7. **`## Wave Final`** — `make ci-resume` + commit note. Run the gate with `make ci-resume`
   (resumable: stops at the first failing step, resumes from it on re-run, skipping passed
   steps) and iterate fix → `make ci-resume` until it reports all steps passed — rather than
   re-running `make ci` whole each time. Mid-wave waves use `make ci-affected` (or
   `make ci-changed` for Python-only).

`verify_targets` must list **Makefile targets only** (e.g. `make lint`, `make typecheck`,
`make ci-affected`, `make ci-changed`, `make ci-resume`, `make ci`) — never raw `pytest` or `ruff`.

Typical shape for error-driven plans:

| wave_id | title | depends_on | review_gate | effort | verify_targets |
|---------|-------|------------|-------------|--------|----------------|
| W0 | Confirm problem matrix + scope | | yes | S | make lint, make typecheck |
| W1 | First fix cluster | W0 | | M | make ci-affected |
| … | … | … | | | |
| Final | Integration | last impl wave | | L | make ci |

Use `review_gate: yes` on W0 so the operator confirms the filled taxonomy and grouped
problem types before implementation waves.

---

## Step 4 — Self-check before finishing

- [ ] Every `turn_id` in `{{ERROR_TURN_IDS}}` was explored via `sevn turn-bundle view`
  (including full `--stream message`).
- [ ] Taxonomy checklist complete — every turn × every problem kind classified with evidence
  where `present=yes`.
- [ ] Plan includes **`## Turn problem matrix`** summarizing classifications.
- [ ] Related problems are grouped into shared waves (**D11**); all cited `turn_id`s appear
  in the plan.
- [ ] Exactly **one** `*-wave-plan.md` was written under `{{OUTPUT_DIR}}` (**D6**).
- [ ] `## tripll execution graph` is present and every `depends_on` target exists as a
  `wave_id` row.
- [ ] Plan would pass `make validate-set SET=from-errors-{{RUN_ID}}` (structure only — you
  may not run it unless the driver environment allows).

---

## Do not

- Write multiple plan files for this run.
- Rely on `--errors-only` alone — always read the full message stream.
- Skip the taxonomy checklist or any problem kind.
- Create one wave per error turn by default — merge when one fix addresses several.
- Fabricate diagnostics not present in the bundles.
- Remove spec/PRD references when the failure touches a documented subsystem.
