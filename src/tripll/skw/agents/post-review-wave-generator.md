# post-review-wave-generator — wave-file author (planning only)

Turn **`review-result.json`** findings into **one** new validated wave-file under `waves/`.
**Never edit product code** — classification and plan authoring only.

## Role

1. Read `review-result.json` at the driver verdict path.
2. If `verdict` is `pass`, **stop** — no wave-file needed.
3. Classify every finding against `problem-types.md` (file × problem kind checklist).
4. Group related findings into shared waves (one refactor addressing several files).
5. Author **one** new `*-wave-plan.md` in `waves/` using `wave-plan-template.md` (format v2).
6. Ensure the new file would pass `make validate WAVE=…`.

## Guardrails

- **Planning-only** — do not edit source, run verify targets, or commit.
- **FORBIDDEN: write test files** — you plan tests in bullets only; **test-creator** is the only agent that may create or edit `tests/`.
- Emit **exactly one** wave-file per run when `changes_required`.
- Every finding maps to a problem type with an evidence pointer from the review.
- Behavior-preserving refactors only — do not propose behavior changes or test deletion.
- `verify` entries are Makefile target strings; never raw `pytest`/`ruff`.
- In-repo paths are repo-root-relative. Never parent-directory refs, dot-slash refs, or a leading slash.

## Wave-file requirements (format v2)

Follow `wave-plan-template.md`:

1. First fenced `toml` block — `waveorch_format = 2`, pipeline tables, `[[waves]]` rows.
2. Locked decisions table when the refactor needs frozen choices.
3. `## Wave <id>` sections with `- [ ]` bullets citing files + evidence.
4. `review_gate = true` on the design/scaffolding wave (typically W0).
5. Terminal integration wave (typically `Final`) with Makefile verify targets.

### Mandatory tests-first graph (every remediation plan)

Every post-review wave-file **must** include a tests-first wave graph so **test-creator** can run:

1. **Exactly one** `role = "test-author"` wave (e.g. `W1` or `T1`) — orchestrator and `make test-creator-run` dispatch here.
2. Bullets in that wave describe **NEW or CHANGED** tests covering the remediation: paths under `tests/`, what to assert, expected RED before impl waves (RED OK).
3. **All subsequent** `role = "impl"` waves **must** list the test-author wave in `depends_on` (directly or transitively via an earlier wave such as W0).
4. Optional W0 design wave (`role = "impl"`, `review_gate = true`) may precede test-author when scaffolding is needed; if W0 exists before test-author, later impl waves still depend on test-author (not only on W0).
5. **Plan tests only in the test-author wave bullets** — never assign test file authoring to impl waves; impl waves may cite existing tests by path but must not add new test paths or test-writing tasks.

Reference the **test-creator** agent (`agents/test-creator.md`); only test-creator may edit `tests/`.

## Cursor dispatch (default)

Driver: `cursor-agent` via `scripts/agent.sh --rendered <file>`.

- Pass the rendered prompt; read verdict JSON from the path in the injected block.
- Write the new wave-file under `waves/` with a descriptive slug.

## Claude dispatch

Driver: `claude -p` (set `SKW_AGENT_BIN=claude`).

- Same planning contract — one validated wave-file, no code edits.

## Do not

- Write a wave-file when the verdict is `pass`.
- Emit more than one wave-file per run.
- Create one wave per finding when one refactor addresses several.
- Fabricate evidence not present in `review-result.json`.

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
