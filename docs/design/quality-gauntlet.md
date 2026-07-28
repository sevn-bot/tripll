# Quality gauntlet — reference-driven inner loop (design extension)

**Status:** Design — `wave/quality-gauntlet-design` (2026-07-28)
**Extends:** [`tripll-code-factory-design.md`](../../ignorelocal/design/plan/tripll-code-factory-design.md)
§7.9.4 · §7.10 · §8 · §9.4 · §11 · §12
**Source:** [Gauntlet Loop](https://somethingbig.ai/gauntlet-loop) — builder/critic loops against a
concrete reference bar for artifacts tests cannot fully encode.

---

## 0. What this adds

L1 already runs a **correctness gauntlet**: outcome contracts, isolated `wave-verifier` (D17), PR
fix loop until CI + review green. That bar is machine-checkable.

The **quality gauntlet** is an optional **inner loop** for subjective deliverables — menu copy,
skill prose, docs, rendered UI — where the bar is a **reference artifact** (HTML crop, exemplar
skill, rubric) rather than a pytest line.

| Loop | Bar | When |
|------|-----|------|
| **Correctness** (existing) | `[waves.outcome].required` / `forbidden` + `wave-verifier` | Every impl wave |
| **Quality** (this doc) | `[waves.outcome.reference]` + `quality-critic` | When plan declares it |

Both loops share D17 isolation, loop exits (§7.10), and L2 telemetry. Quality rounds are
**additional** attempts — they do not replace correctness verify.

---

## 1. Decisions register (extension)

| # | Topic | Decision |
|---|-------|----------|
| **D26** | Quality loop opt-in | Quality gauntlet is **off by default**. A wave enables it via `[waves.outcome.quality_gauntlet].enabled = true` and a non-empty `[waves.outcome.reference]`. |
| **D27** | Critic isolation | `quality-critic` uses the **same isolation rules as D17**: fresh adapter process, no implementer transcript, inspects rendered/captured artifacts only. |
| **D28** | Decomposition mode | `decomposition = prescribed` (default) — plan-author owns wave split (D20/D21). `decomposition = gauntlet` — implementer may split **within owned `targets`** into improvable units; compiler still enforces one-writer-per-file. |

---

## 2. Plan v3 schema — `[waves.outcome.reference]`

Normative TOML (nested under `[waves.outcome]`):

```toml
  [waves.outcome.reference]
  kind = "html_crop"                       # see table below
  path = "docs/examples/menu-deployment.html#section"
  comparison = "blind_ab"                  # blind_ab | side_by_side | rubric
  stop_when = "reference_wins"             # reference_wins | max_rounds | operator

  [waves.outcome.quality_gauntlet]
  enabled = true
  max_rounds = 5                           # pairs with exit 2 / exit 5
  sub_budget_usd = 2.0                     # sub-budget under pipeline.budget_usd (exit 3)
  decomposition = "prescribed"             # prescribed | gauntlet
  smoothing = false                        # run smoothing-pass before wave-verifier
```

Optional wave-level override:

```toml
[[waves]]
id = "W7c"
decomposition = "gauntlet"                 # overrides quality_gauntlet.decomposition when set
```

### 2.1 `reference.kind`

| kind | `path` points to | Critic inspects |
|------|------------------|-----------------|
| `screenshot` | PNG/WebP under repo or run dir | Pixels (browser screenshot, Telegram capture) |
| `html_crop` | HTML file + optional `#anchor` | Rendered DOM region or static HTML section |
| `spec_section` | Spec/PRD markdown heading | Prose vs reference section |
| `skill_exemplar` | Bundled `SKILL.md` path | Skill structure, clarity, guardrails |
| `benchmark_task` | `bench/tasks/<id>/reference/*` | Sealed bench reference bundle |
| `rubric_only` | Inline rubric path or `bench/rubrics/*.md` | Rubric dimensions; no single reference file |

### 2.2 `reference.comparison`

| mode | Behaviour |
|------|-----------|
| `blind_ab` | Critic receives `(A, B)` without labels; one is reference, one is build output; picks better; names largest gap if reference wins |
| `side_by_side` | Labels shown; same gap naming |
| `rubric` | Score 0–10 per rubric dimension; pass when all dimensions ≥ plan threshold (default 7) |

Generalises D23 (graph-brief vs grep-brief A/B) from **brief packing** to **product output**.

### 2.3 `reference.stop_when`

| value | Exit |
|-------|------|
| `reference_wins` | Loop ends when critic picks build output over reference (or rubric pass) |
| `max_rounds` | Exit after `quality_gauntlet.max_rounds` regardless |
| `operator` | Loop ends only on human interrupt (exit 6) or external stop |

---

## 3. Loop shape — `quality-gauntlet`

Runs **after** implementer produces a candidate artifact, **before** `wave-verifier` (correctness).

```text
implementer → [quality-gauntlet ⟲] → [smoothing-pass?] → wave-verifier → …
```

Inner cycle (LangGraph optional sub-graph or engine micro-loop):

```text
capture_artifact → quality-critic → (reference wins? → exit)
                              ↓ gap
                         implementer (one gap only)
                              ↓
                         capture_artifact → …
```

**Rules:**

1. **One gap per round** — critic names the single largest meaningful gap; implementer fixes only that.
2. **Inspect real output** — critic grades screenshots, rendered HTML, committed files, or bench
   captures — never the implementer's summary.
3. **Receipts** — each round writes a `Verdict` or `Finding` with `kind = quality`, round number,
   comparison mode, winner, gap text, artifact paths.
4. **Workbench** — `runs/<run_id>/workbench.html` updated each round (artifact thumb, reference
   crop, verdict, round count). Dashboard links from §12 findings/exits panels.
5. **Exits** — inherit §7.10: turn cap (`max_rounds`), sub-budget (`sub_budget_usd`), no-progress
   (three identical artifact hashes), error threshold, human interrupt.

When `[waves.outcome.reference]` is absent, the quality loop is skipped; behaviour matches pre-D26
L1.

---

## 4. Harness integration (§7.9.4 extension)

Outcome evaluation order for impl waves with quality gauntlet enabled:

1. **Code graders** — `required` / `forbidden` from existing harness (`harness/contracts.py`).
2. **Quality gauntlet** — reference comparison rounds until stop condition.
3. **Correctness verify** — isolated `wave-verifier` (unchanged).

Wave states:

| State | Meaning |
|-------|---------|
| `quality_loop` | Inner gauntlet in progress |
| `unverified` | Quality or correctness grader could not run |
| `done` | Both correctness contract **and** reference stop condition satisfied |

`render_completion` includes quality round summary when present.

---

## 5. L1 phase table (§8 extension)

Insert between phases 8 and 9 when enabled on a wave:

| Phase | Node kind | Owner agent | Output |
|-------|-----------|-------------|--------|
| 8b Quality gauntlet ⟲ | `quality_loop` | `implementer` ↔ `quality-critic` | artifact captures, round `Verdict`s, `workbench.html` |
| 8c Smoothing | `smooth` | `smoothing-pass` (optional) | consistency pass across independently improved units |

Phase 9 `verify` remains **`wave-verifier` isolated (D17)** — quality critic does not substitute
for correctness verify.

---

## 6. Agent contracts (§11 extension)

See:

- [`docs/agents/quality-critic.md`](../agents/quality-critic.md)
- [`docs/agents/smoothing-pass.md`](../agents/smoothing-pass.md)
- [`docs/agents/reference-picker.md`](../agents/reference-picker.md)

Roster summary:

| Agent | class | edits | Role |
|-------|-------|-------|------|
| `quality-critic` | reviewing | nothing | Fresh-context reference comparison; one gap per round |
| `smoothing-pass` | reviewing | owned targets only | Post-parallel consistency; no redesign |
| `reference-picker` | authoring | plan reference block only | Proposes concrete bar when plan lacks `[waves.outcome.reference]` |

All three inherit §7.9.1–§7.9.3, §7.10, graph-packed brief (§7.6).

---

## 7. L2 benchmark (§9.4 extension — human gate per D24)

Proposed metrics (require human approval before editing `bench/METRICS.md` on main):

| # | Metric | Definition |
|---|--------|------------|
| 10 | `reference_win_rate` | Share of quality-gauntlet tasks where build output beats reference |
| 11 | `quality_rounds_to_pass` | Mean inner-loop rounds before stop condition |
| 12 | `quality_delta_finding_density` | Finding density with vs without quality gauntlet on sealed tasks |

Sealed bench tasks (design placeholders — implement under `bench/tasks/` after D24 gate):

- **G1** — one menu section keyboard vs HTML crop (sevn Telegram menu)
- **G2** — one `SKILL.md` vs bundled exemplar
- **G3** — one changelog Unreleased block vs `changelog-eval` rubric

---

## 8. What not to import from Gauntlet Loop

| Idea | Rejection |
|------|-----------|
| Single mega-prompt, no plan | Conflicts with D10, D20, skw phase model |
| Unbounded polish | tripll exits 2–8 remain mandatory |
| Builder self-grades | Replaced by outcome contracts + D17/D27 |
| Replace wave plans with dynamic-only decomposition | Factory refactors stay `prescribed` |

---

## 9. Implementation waves (future)

Not in scope for this design branch — tracked follow-up:

1. **Engine** — `quality_loop` node kind, artifact capture hooks, workbench writer
2. **LangGraph** — optional sub-graph for inner cycle (§7.8)
3. **Graders** — `harness/quality.py` blind A/B orchestration
4. **Bench** — G1–G3 tasks + D24 metric gate
5. **Prompt bodies** — skw briefs beyond contract stubs

---

## 10. Traceability

| Design anchor | This doc |
|---------------|----------|
| D16 outcome contracts | §4 — quality is additive grader |
| D17 verifier isolation | D27 — same rules for quality-critic |
| D23 graph vs grep A/B | §2.2 — generalised to product output |
| D24 Goodhart gate | §7 — new metrics need human gate |
| §7.10 loop exits | §3 — inner loop uses caps 2, 3, 5, 6, 7 |
| §11.8 implementer | §3 — builder in inner loop |
| §11.9 wave-verifier | §4 — runs after quality loop |
