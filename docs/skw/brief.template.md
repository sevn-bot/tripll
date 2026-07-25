# Operator brief — <plan title>

<!--
  This is the CONTEXT file for `make plan-generate ... CONTEXT=brief.md`.
  Its **entire content is injected verbatim** into the wave-generator prompt as
  "Operator context" — the agent reads it to design the wave graph, pick verify
  targets, and record locked decisions. Write prose, not TOML: the agent authors
  the wave-file TOML itself.

  Keep it tight and decision-dense. Delete guidance comments before use, or leave
  them — the agent ignores HTML comments. Every section below is optional except
  Goal; fill what helps and drop the rest. See brief.example.md for a worked copy.
-->

## Goal

<!-- One or two sentences: what this plan must ship, and the problem it solves.
     This becomes the wave-file's "Goal" section. Be concrete about the outcome. -->

## Why now / motivation

<!-- Optional. The trigger: a bug, a user request, tech debt, a blocked feature.
     Helps the agent prioritise and scope. -->

## Scope

**In scope:**
<!-- Bullet the work that IS included. -->

**Out of scope:**
<!-- Bullet what to explicitly NOT touch — prevents the agent over-reaching. -->

## Relevant code & entry points

<!-- Prose pointers to the code that matters: modules, functions, the turn spine,
     the config key. Complements PATHS= (which lists dirs the agent will explore).
     Name the file:function you expect to change if you know it. -->

## Constraints & locked decisions

<!-- Frozen choices the plan must honour and NOT re-litigate during execution.
     These become the wave-file's "Decisions baked into this plan" section.
     e.g. "Use existing X helper, don't add a dependency", "keep the public
     signature of Y", "config lives in sevn.json under z.*". -->

## Acceptance / how we know it's done

<!-- The observable done-state, and — important — which `make` targets verify it.
     Verify targets in the wave-file must start with `make ` (e.g. `make lint`,
     `make typecheck`, `make ci-changed`). List the ones that gate this work. -->

## Must not regress

<!-- Behaviours/tests that must stay green. The agent turns these into guard rails
     and non-goals. -->

## References

<!-- Optional: issue/PR numbers, error logs, stack traces, spec paths, prior art.
     Paste short logs directly — they're high-signal context for the agent. -->

## Suggested wave breakdown (optional)

<!-- If you already have a shape in mind, sketch it. The agent may refine it, but
     hints help. Remember the tests-first rule: exactly one `role = test-author`
     wave before the impl waves when the plan includes implementation work.
     e.g.
       - W0 (impl, review_gate): scaffolding / config plumbing
       - W1 (test-author): RED test suite for the new behaviour
       - W2 (impl): implement, turn W1 green
       - Final (impl): docs + green gate
-->
