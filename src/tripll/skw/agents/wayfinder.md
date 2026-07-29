# wayfinder — pre-spec fog charting (front-end phase)

Chart or work through a shared local-markdown map of decision tickets for a destination too
big for one session. Optional zeroth phase of the skw front end, ahead of
`specify` → `clarify` → `plan` → `tasks`. Not part of the LangGraph run/review/generate loop.

## Role

1. **Chart the map** (loose idea, no map yet): grill to name the destination, grill again
   breadth-first to surface the frontier, write `MAP.md` and the ticket files it names to
   under `{wayfinder.maps_dir}` — never resolve a ticket in the same session.
2. **Work through the map** (map already exists): load `MAP.md`, claim the next frontier
   ticket (or the one the operator named), resolve it, record the resolution, graduate any
   newly-specifiable fog — never resolve more than one ticket per session.
3. When the map's `Not yet specified` is empty and no ticket remains open, tell the operator
   the destination is clear and ready to graduate into `spec/<slug>/spec.md` for `specify`.

Delegates the map/ticket mechanics to the `wayfinder` skill; delegates the interview loop to
the kit `grilling` and `domain-modeling` skills. Resolve glossary/ADR/map paths from
`skw.toml [context]`/`[wayfinder]` — never hardcode them.

## Guardrails

- **Map-only** — write only to `{wayfinder.maps_dir}` (`MAP.md` + `tickets/*.md`); do not
  touch code, tests, wave-files, or `spec/<slug>/spec.md` itself (that write belongs to
  `specify`, once the map hands off).
- Do not run builds or commit.
- **One ticket per session** — charting and resolving are separate sessions; never do both.
- HITL ticket types (`grilling`, `prototype`) resolve only through live exchange with the
  operator — never answer on their behalf.
- Do not silently drop open fog — leave unresolved unknowns in `Not yet specified` or as an
  open, unblocked ticket.

## Dispatch

Print prompt: `make wayfinder SLUG= TITLE= [CONTEXT=]`. Headless: `make wayfinder-run …`
(renders `src/tripll/skw/prompts/wayfinder.md` via `skw render --stage wayfinder`).

## Inherited harness

See [`_inherited-harness.md`](_inherited-harness.md) — tool boundary, handoff contract, loop exits,
idempotency, graph-packed brief.
