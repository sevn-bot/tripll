---
name: verify
description: >
  Prove the engineering task you just built actually works, then ship it. A fresh
  verifier sub-agent brings up the stack, drives the real app, captures
  screenshot/video proof to `evidence/`, and opens a PR with the proof embedded —
  never before the task is verified. Run this BEFORE opening a PR, or whenever
  asked to verify a change — "verify this", "prove it works", "does this actually
  work", "open a PR with proof", "/verify".
user_invocable: true
---

# /verify — prove the task works, then open the PR

## When to run

- **Before opening a PR** — this is the gate; the PR carries the proof it produces.
- **On explicit request** — "verify this", "does this actually work", "prove it".

You are the **orchestrator + fixer**. Verification splits by who's best at it:

- **The subjective question — "does the task I just built do what was intended?"**
  → delegate to a fresh **verifier sub-agent** that drives the real app and judges
  it. Independence (it didn't write the code) + context-isolation (app-driving is
  verbose) pay off. Most tasks have no spec — **agentic verification, not "run the
  test."** Do it first.
- **Objective, codified checks** (type-check, lint, unit, existing e2e) → **you**
  run them, after, as a regression sweep. Pass/fail can't be rubber-stamped, and
  you need the error to fix it.

## Repo specifics (filled in by `verifier-setup`)

- **Stack** — bring the app up with: `{{STACK_UP}}`
- **Where the app runs** — `{{APP_URL}}`
- **Run mode** — **{{RUN_MODE}}** (local dev stack | isolated sandbox)
- **Driver** — `{{DRIVER}}`
- **Auth** (if login-gated) — `{{AUTH_HELPER}}`
- **Evidence** — write all proof to `evidence/` (gitignored)
- **Proof upload target** — `{{EVIDENCE_UPLOAD}}`

## 0. Preconditions

On a branch, not the default branch; changes committed.

## 1. Bring up the stack — once

`{{STACK_UP}}` — you own it; the verifier reuses it. {{RUN_MODE_NOTE}}

## 2. Verify the TASK (delegate) → fix → re-verify (loop)

Brief from the task/plan file if one exists (point the verifier at it), else pass
the acceptance criteria inline. Spawn a read-only verifier:

```
You are a read-only verifier. Do NOT edit code. Independently confirm THIS task
works by driving the running app (the stack is already up). It likely has no
automated spec — verify it agentically.

TASK (what a user should now be able to do, and the observable success state):
  <intent / acceptance criteria>          (or: see task/plan file <path>)
HOW TO EXERCISE IT:
  {{EXERCISE}}
DRIVER:
  {{DRIVER_INSTRUCTION}}
AUTH (if behind login):
  {{AUTH_INSTRUCTION}}

Walk the exact steps, capture the success state to evidence/ (screenshot AND a
short video for web; response body + status / stdout for non-web), and judge
observed vs expected. Return ONLY:

TASK: works | broken
  expected: <criteria>
  observed: <what actually happened>
  evidence: <paths under evidence/>
```

- **broken** → fix the implementation, then spawn a **fresh** verifier. You never
  declare the task works yourself.
- Cap at ~3 rounds; if still broken, escalate to the human with the verdict.

## 3. Regression sweep — you run the codified checks; fix red directly

`{{REGRESSION_CMDS}}`. Triage failures (real-bug vs stale-test); never weaken an
assertion to go green. If a fix here changes task behavior, re-verify (step 2).

**sevn.bot note:** use `make ci-affected` mid-branch; use `make ci-resume` at merge boundary.
Add `make telegram-e2e` when the diff touches Telegram/menu/session.

## 4. Open the PR — lead with the proof, embed the evidence

The PR body MUST show the evidence, not just mention it. Upload both artifacts
from `evidence/` to a stable URL (`{{EVIDENCE_UPLOAD}}`), then in the body:

- **embed the screenshot inline** with `![proof]()` so a reviewer
  sees the success state without leaving the PR;
- **link the video** — GitHub can't play uploaded video inline via automation, so
  link the stable URL (a reviewer clicks to watch).

```markdown
## What changed
<1–3 lines>

## Task verified ✅  (verifier drove the app)
- <acceptance criteria> — observed working.

![success state](<screenshot-url>)
📹 Video: <video-url>

## Regression guardrails
- [x] {{REGRESSION_CMDS}}

## How to reproduce
{{STACK_UP}} && <exercise steps>
```

## Rules

- **The task is the verdict** — a green suite with an unverified task isn't done.
- **"Does it actually work" → an independent verifier; objective checks → you.**
- Never open a PR until the task is verified. **Proof, not claims.** Branch → PR only.
- **Never** run `git clean -x` or `git clean -X` in this repo (destroys operator trees).

**Provenance:** adapted from [AI-Builder-Club/skills verify template](https://github.com/AI-Builder-Club/skills/blob/main/skills/verifier-setup/assets/verify.template.md) (MIT).
