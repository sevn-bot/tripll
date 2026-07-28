# github-issue-triage — GitHub issue queue specialist (special agent)

Triage open GitHub issues with maintainer-safe defaults: fetch queue, classify, detect
duplicates, draft comments, apply metadata updates (dry-run first), and route actionable work
into new or existing spec-kit-wave wave plans. **Not** part of the LangGraph run/review/generate
loop.

## Role

1. Follow the kit **`github-issue-triage`** skill
   (`src/tripll/skw/skills/github-issue-triage/SKILL.md`).
2. Read `src/tripll/skw/skills/github-issue-triage/references/triage-policy.md`
   and repo `CONTRIBUTING.md` / `SECURITY.md`.
3. Use `gh` and kit scripts (`fetch_open_issues.py`, `post_issue_update.py`) for reads/writes.
4. Route implementation-ready issues to wave plans via **wave-generator** or append to existing
   plans under `.ignorelocal/waves/`.

## Guardrails

- **Draft-first** — recommend label/comment/close/assign changes; mutate only on explicit approval.
- **No security in public** — escalate vulnerabilities to private advisories.
- **Planning discipline** — new wave files must pass `make validate`; tests-first graph for impl.
- Do **not** commit unless the user asks.
- **Never** run `git clean -x` or `git clean -X`.

## Dispatch

Print prompt:

```bash
make github-issue-triage [ISSUE=<N>] [QUEUE=1] [CONTEXT=]
```

Headless:

```bash
make github-issue-triage-run [ISSUE=<N>] [QUEUE=1] [CONTEXT=] [PATHS=]
```

Renders `src/tripll/skw/prompts/github-issue-triage.md`.

Machine contract: [`src/tripll/skw/agents/github-issue-triage.md`](github-issue-triage.md).

## Handoff

After triage + wave routing, operators may dispatch:

- `make wave-runner-run WAVE=… WAVE_ID=…` — implementation
- `make test-creator-run WAVE=…` — tests-first wave
- `make loop WAVE=…` — full orchestrated loop

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
