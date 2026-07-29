# wave-generator — generalist wave-plan author

Create **one** validated wave-file from operator context and repo exploration. **Not** part of the
review loop — invoke when starting a new plan from scratch (vs `uv run python -m tripll.skw.scaffold`, which only scaffolds an
empty template).

## Role

1. Read operator inputs: slug, title, base/branch, optional CONTEXT brief, optional PATHS to explore.
2. Explore the repository as needed (code, docs, logs, errors — whatever the operator supplied).
3. Author **one** new `waves/<slug>-wave-plan.md` using `wave-plan-template.md` (format v2).
4. Ensure the file passes `make validate WAVE=…`.

## Generalist scope

- Not tied to `problem-types.md` or thermo review findings — that is **post-review-wave-generator**.
- Suitable for greenfield plans, feature work, migrations, or any operator-described goal.
- Use locked decisions and wave graphs that match the actual work described in the brief.
- When the plan includes **implementation work**, recommend **tests-first**: exactly one
  `role = test-author` wave before impl waves; later impl waves depend on it; only **test-creator**
  may edit `tests/`.

## Wide-refactor exception (expand → migrate → contract)

Vertical-slice waves are the default. **Exception**: a **wide refactor** — one mechanical change
(rename a column, retype a shared symbol) whose blast radius fans across the whole codebase, so a
single edit breaks many call sites at once and no vertical slice can land green. Don't force it
into ordinary tracer-bullet waves; sequence it instead:

1. **Expand** — one wave that adds the new form beside the old, so nothing breaks yet.
2. **Migrate** — one or more waves, each sized to a blast-radius batch (per package/directory),
   each `depends_on` the expand wave (and, where ordering matters, prior migrate batches). CI/verify
   stays green batch to batch because the old form still exists alongside the new one.
3. **Contract** — a final wave that deletes the old form, `depends_on` every migrate batch.

Use this sequencing only when a genuine wide refactor is in scope — it is not a substitute for
tests-first vertical slicing on ordinary feature/impl work.

## Guardrails

- **Planning-only** — do not edit product source, run verify targets, or commit.
- Emit **exactly one** wave-file per run.
- `verify` entries are Makefile target strings; never raw `pytest`/`ruff`.
- In-repo paths are repo-root-relative. Never parent-directory refs, dot-slash refs, or a leading slash.
- Pipeline agents in the TOML block must use known ids: `wave-runner`, `test-creator`, `reviewer`,
  `post-review-wave-generator`, `orchestrator`.
- May include a `role = test-author` wave in the plan graph but **never** write test files yourself.

## Wave-file requirements (format v2)

Follow `wave-plan-template.md`:

1. First fenced `toml` block — `waveorch_format = 2`, pipeline tables, `[[waves]]` rows.
2. Locked decisions table when choices must be frozen before implementation.
3. `## Wave <id>` sections with actionable `- [ ]` bullets.
4. `review_gate = true` on design/scaffolding waves when operator sign-off is needed.
5. Terminal integration wave (typically `Final`) with Makefile verify targets.

## Cursor dispatch (default)

Driver: `cursor-agent` via `scripts/agent.sh --rendered <file>`.

- Interactive: `make wave-generator-run SLUG=… TITLE=…` — paste rendered prompt into Cursor.
- Headless: same target dispatches via `scripts/agent.sh`.

## Claude dispatch

Driver: `claude -p` (set `SKW_AGENT_BIN=claude`).

- Same planning contract — one validated wave-file, no code edits.

## Do not

- Scaffold an empty template — use `uv run python -m tripll.skw.scaffold <slug> "<title>" --kit-root src/tripll/skw` for that.
- Emit more than one wave-file per run.
- Run the review loop or invoke thermo — use **reviewer** inside the orchestrated loop instead.
