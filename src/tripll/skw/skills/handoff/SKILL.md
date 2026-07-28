---
name: handoff
description: >-
  Compact the current conversation into a handoff document for another agent
  to pick up. Use when the user asks to hand off, wrap up, or compact the
  session for a fresh agent to continue.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

# Handoff

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it to the session scratchpad, or `src/tripll/skw/.out/` when running headless inside this kit — never into the host repo tree (no commits, no files under `about-sevn.bot/`, `src/`, or any other tracked path).

**Provenance:** derived from mattpocock/skills/handoff (MIT).

Include a "suggested skills" section in the document, which suggests skills that the agent should invoke.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
