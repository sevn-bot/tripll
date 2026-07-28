---
name: verifier-setup
description: >
  Set sevn.bot up to prove engineering-task work actually works before it ships.
  Investigates the repo, ensures a one-command dev stack exists, asks whether
  verification runs locally or in a sandbox, confirms/installs the driver
  (cursor-ide-browser MCP or telegram_test for channel UX). Outputs three
  artifacts: a committed `/verify` skill (per-task verification SOP — spawn a
  verifier sub-agent → drive the app → screenshot/video proof → open a PR with
  the proof embedded), any missing stack launcher docs, and the installed driver
  skill. Use when someone says "set up verification", "make this repo verifiable",
  "scaffold a verify skill", "set up the verifier".
user_invocable: true
---

# verifier-setup — scaffold this repo's `/verify` skill

Goal: leave sevn.bot able to *prove an engineering task works before it ships* —
run once, and it wires up everything the per-task `/verify` loop needs.

You are **setting up** — not verifying anything yourself right now. The `/verify`
template lives at `assets/verify.template.md` (next to this skill). Canonical
home for this skill is **`src/tripll/skw/skills/verifier-setup/`**; install into
IDE hosts with `make install-skills` (symlinks into
`.cursor/skills/` and `.claude/skills/`).

## What this produces (the outputs)

Running `verifier-setup` end-to-end leaves the repo with:

1. **A `/verify` skill** — `.claude/skills/verify/SKILL.md` **and**
   `.cursor/skills/verify/SKILL.md` (symlink or copy from the generated file),
   the repo-tailored per-task verification SOP (spawn a verifier sub-agent →
   drive the app → screenshot/video proof → open a PR with the proof embedded).
   Generated in Step 5 from `assets/verify.template.md`.
2. **A documented stack launcher** — reuse `make compose-up` when Docker is the
   operator stack; otherwise document the existing one-command path in the
   generated `/verify` skill (`STACK_UP`). Do **not** hand-roll `scripts/dev-local.sh`
   when `make compose-up` already works.
3. **The driver skill installed** — for Mission Control / web UI:
   **cursor-ide-browser** MCP (Cursor) or Playwright via `.cursor/skills/telegram_test`
   for Telegram operator UX; for CLI-only tasks, the built `sevn` binary.

## Step 0 — Inventory what already exists (check before you add ANYTHING)

Before creating anything, take stock — sevn.bot may already have some of this:

- **Stack** — `make compose-up` (Docker gateway + proxy), host gateway, or docs in
  `docs/telegram-e2e-developer-guide.md`.
- **Prior verification** — `.cursor/skills/telegram_test`, wave `make ci-affected`,
  or an earlier `/verify` skill from a prior run.
- **Driver** — `cursor-ide-browser` MCP (Mission Control), `sevn telegram-test`
  (Telegram), or pytest markers for headless checks.
- **Regression checks** — `make ci-affected` (mid-wave), `make lint` + `make typecheck`
  (Python edits), `make telegram-e2e` (Telegram UX).
- **Evidence** — `evidence/` (gitignored; create + add to `.gitignore` if missing).

Every later step is conditional: **reuse and adapt** working setup; only create what's missing.

## Step 1 — Investigate the repo (don't guess)

Discover the real facts the generated skill will hardcode:

1. **How the app is exercised** — Mission Control (web on `SEVN_GATEWAY_PORT`, default
   `3001`), Telegram (`sevn telegram-test`), CLI (`sevn …`), or API-only.
2. **Stack launcher** — note the up-command and URL/port (`make compose-up`,
   `curl http://127.0.0.1:3001/ready`, etc.).
3. **Auth** — dashboard login password, Telegram session (`sevn telegram-test login`),
   or `n/a`.
4. **Regression checks** — from the Makefile: prefer `make ci-affected` for branch work;
   add `make telegram-e2e` when the diff touches Telegram/menu/session paths.
5. **Proof upload** — `gh release upload` to a `pr-evidence-*` prerelease (default), or
   attach paths under `evidence/` in the PR body when upload is unavailable.

## Step 2 — Ensure the prerequisites exist

- **Dev stack.** Reuse `make compose-up` + readiness probe when Docker is the operator
  path. Extend only if a needed service is missing.
- **Driver skill.**
  - **Web / Mission Control** → confirm **cursor-ide-browser** MCP is available (Cursor)
    or document Playwright steps; ensure gateway is reachable on the recorded port.
  - **Telegram UX** → confirm `.cursor/skills/telegram_test` (via `make install-skills`)
    and `sevn telegram-test login` prerequisites.
  - **CLI / API** → confirm `sevn` on PATH and the exercise command.
- **Evidence dir.** Ensure `evidence/` exists and is listed in `.gitignore`.

## Step 3 — Ask the user: local or sandbox?

Present the choice (default and recommend **local**):

- **Local** — one dev stack on the machine (`make compose-up`). Best for a single task.
- **Sandbox** — isolated environment per agent (only when the operator already has one;
  sevn.bot does not ship crabbox by default).

Record the pick as `RUN_MODE` in the generated `/verify` skill.

## Step 4 — Confirm the driver

State the detected driver and confirm with the user:

| Surface | Default driver |
| --- | --- |
| Mission Control / web | `cursor-ide-browser` MCP |
| Telegram operator UX | `telegram_test` skill + `make telegram-e2e` |
| CLI / API | `sevn` CLI + curl or pytest |

This becomes `DRIVER` in the generated skill.

## Step 5 — Generate the `/verify` skill

If `.claude/skills/verify/SKILL.md` or `.cursor/skills/verify/SKILL.md` already exists,
**update in place** — refresh repo-specific placeholders; preserve team hand-edits.

Otherwise copy `assets/verify.template.md` → both skill dirs (or generate once under
`src/tripll/skw/skills/verify/SKILL.md` and run `make install-skills` with `COPY=1` for
verify only). Fill every `{{...}}` placeholder from Steps 1–4:

`STACK_UP`, `APP_URL`, `RUN_MODE` (+ `RUN_MODE_NOTE`), `DRIVER` (+ `DRIVER_INSTRUCTION`),
`AUTH_HELPER` (+ `AUTH_INSTRUCTION`), `EXERCISE`, `REGRESSION_CMDS`, `EVIDENCE_UPLOAD`,
`DATE`. Delete branches that don't apply (e.g. drop browser/video language for CLI-only work).

## Step 6 — Hand off

Tell the user:

- Run **`/verify`** (or load the `verify` skill) before opening a PR on a branch with
  changes committed.
- Re-run **`make install-skills`** after adding kit skills.
- Headless dispatch: **`make verifier-setup-run`** (renders the agent
  prompt; same contract as this skill).
- Prerequisites: Docker for `compose-up`, `gh auth` for evidence upload, Playwright for
  Telegram E2E when that driver is selected.

## Principles

- **Check before you create; adapt, never clobber.**
- **Discover, don't assume** — stack command, port, auth, and checks come from the repo.
- **Provision before you generate** — driver, launcher, and `evidence/` exist before `/verify` ships.
- **Right-sized** — web/Telegram tasks get browser/video proof; CLI tasks get stdout/assertion proof.
- **The output is a skill, not a run.** verifier-setup scaffolds; `/verify` runs.

**Provenance:** adapted from [AI-Builder-Club/skills verifier-setup](https://github.com/AI-Builder-Club/skills/blob/main/skills/verifier-setup/SKILL.md) (MIT).
