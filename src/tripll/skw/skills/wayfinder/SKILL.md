---
name: wayfinder
description: >-
  Plan a chunk of work too big for one agent session as a shared map of
  decision tickets under spec/<slug>/wayfinder/, and resolve them one at a
  time until the way to the destination is clear. Use when a loose idea
  needs charting before `specify`, or when the operator points at an
  existing map to work through.
disable-model-invocation: true
---

# wayfinder — pre-spec fog, charted as a local-markdown map

A loose idea has arrived — too big for one agent session, and wrapped in fog: the way from
here to the **destination** isn't visible yet. Wayfinding is about finding that way, not
charging at the destination. This skill charts the way as a **shared map** of tickets, then
works through them one at a time until the route is clear.

**Provenance:** derived from mattpocock/skills/wayfinder (MIT).

The destination varies per effort, and naming it is the first act of charting — it shapes
every ticket. It might be a spec to hand off and iterate on, a decision to lock before
planning starts, or a change made in place. The map is domain-agnostic.

## Plan, don't do

Wayfinder is **planning** by default: each ticket resolves a decision, and the map is done
when the way is clear — nothing left to decide before someone goes and does the thing. The
pull to just do the work is usually the signal you've reached the edge of the map and it's
time to hand off (to `specify`). An effort can override this in its **Notes** — carrying
execution into the map itself — but absent that, produce decisions, not deliverables.

## Backend: local-markdown (no issue tracker)

This kit does not wire an issue tracker. The map and its tickets are plain files, resolved
from `skw.toml [wayfinder]` via `scripts/context_paths.py --slug <slug>` (never hardcoded):

```
{wayfinder.maps_dir}/MAP.md                  # default: spec/<slug>/wayfinder/MAP.md
{wayfinder.maps_dir}/tickets/NNNN-<slug>.md  # one file per ticket, zero-padded sequence
```

Run `python3 scripts/context_paths.py --slug <slug>` (from the kit root) to print the
resolved `wayfinder_maps_dir` absolute path before reading or writing either file. No issue
tracker bootstrap is wired here — the local-markdown layout is the only backend.

### The map body (`MAP.md`)

The whole map at low resolution, loaded once per session. Open tickets are **not** listed
inline — they are files under `tickets/`, found by scanning.

```markdown
## Destination

<what reaching the end of this map looks like — the spec, decision, or change this effort
is finding its way to. One or two lines; every session orients to it before choosing a
ticket.>

## Notes

<domain; skills every session should consult — normally `grilling` and `domain-modeling`;
standing preferences for this effort>

## Decisions so far

<!-- the index — one line per closed ticket: enough to judge relevance, then open the
     ticket file for the detail it holds -->

- [<closed ticket title>](tickets/NNNN-<slug>.md) — <one-line gist of the answer>

## Not yet specified

<!-- see "Fog of war" below: in-scope fog you can't ticket yet -->

## Out of scope

<!-- see "Out of scope" below: work ruled beyond the destination; closed, never graduates -->
```

### Tickets (`tickets/NNNN-<slug>.md`)

Each ticket is one file, numbered sequentially (`0001-`, `0002-`, …) and slugged from its
title. Its body is the question, sized to one ~100K-token agent session:

```markdown
## Question

<the decision or investigation this ticket resolves>

Type: grilling
Assignee:
Blocked by:
Status: open
```

- **`Type:`** — one of `research`, `prototype`, `grilling`, `task` (see Ticket Types).
- **`Assignee:`** — the claim. A session claims a ticket by writing its own name/handle here
  **first**, before any work, so concurrent sessions skip it. Blank `Assignee:` = unclaimed.
- **`Blocked by:`** — a list of blocking ticket titles (or filenames), one per line, prefixed
  `- `. Empty list = unblocked.
- **`Status:`** — `open` or `closed`. On resolution, flip to `closed` and append a
  `## Resolution` section below the frontmatter block with the answer.

The **frontier** — open, unblocked, unclaimed tickets — is computed by this skill by scanning
`tickets/*.md` each session; there is no tracker UI to render it, so list it explicitly:
a ticket is on the frontier when `Status: open`, every title in `Blocked by:` corresponds to
a ticket whose own `Status:` is `closed`, and `Assignee:` is blank.

Assets created while resolving a ticket are linked from the ticket file, not pasted in.

## Ticket Types

Every ticket is either **HITL** — human in the loop, worked *with* a human who speaks for
themselves — or **AFK**, driven by the agent alone. A HITL ticket only resolves through that
live exchange; the agent never stands in for the human's side of it.

- **Research** (AFK): reading documentation, third-party APIs, or local resources. Creates a
  markdown summary as a linked asset. Use when knowledge outside the working tree is needed.
- **Prototype** (HITL): raise the fidelity of the discussion with a cheap, rough, concrete
  artifact to react to. Links the prototype as an asset. Use when "how should it look/behave"
  is the key question.
- **Grilling** (HITL): conversation via the kit `grilling` and `domain-modeling` skills, one
  question at a time. The default case.
- **Task** (HITL or AFK): manual work that must happen before a *decision* can be made —
  signing up for a service, provisioning access, moving data so its shape can be seen. The
  one type that *does* rather than *decides* — it earns its place by unblocking a decision,
  not by delivering the destination. Resolved when the work is done; the answer records what
  was done and any resulting facts later tickets depend on.

## Fog of war

The map is *deliberately* incomplete: don't chart what you can't yet see. Beyond the live
tickets lies the **fog of war** — decisions and investigations you can tell are coming but
can't yet pin down, because they hang on questions still open. Resolving a ticket clears the
fog ahead of it, graduating whatever's now specifiable into fresh tickets — one at a time.

The map's **Not yet specified** section is where that dim view is written down. The test is
whether you can state the question precisely now — *not* whether you can answer it now.

- **Ticket when** the question is already sharp — even if it's blocked.
- **Not yet specified when** you can't yet phrase it that sharply. Don't pre-slice the fog
  into ticket-sized pieces.

## Out of scope

Fog only ever gathers *toward* the destination. Work beyond it is **out of scope** — it isn't
fog, and it doesn't belong in **Not yet specified**. It gets its own **Out of scope** section:
work you've consciously ruled out of *this* effort.

When an existing ticket turns out to sit past the destination, set its `Status:` to `closed`
and leave one line in the map's **Out of scope** section: the gist plus why, linking the
closed ticket file. It stays out of **Decisions so far**, which records the route actually
walked.

## Invocation

Two modes. Either way, **never resolve more than one ticket per session.**

### Chart the map

User invokes with a loose idea.

1. **Name the destination.** Run a `grilling` and `domain-modeling` session (this kit's
   skills — resolve their glossary/ADR paths via `scripts/context_paths.py`) to pin down
   what this map is finding its way to. Settle this first; it fixes scope for everything else.
2. **Map the frontier.** Grill again, **breadth-first**: fan out across the whole space
   rather than deep on any one thread. If this surfaces no fog, the way is already clear —
   stop and ask the operator how they'd like to proceed instead of creating a map.
3. **Create `MAP.md`**: Destination and Notes filled in, Decisions-so-far empty, the fog
   sketched into Not yet specified.
4. **Create the ticket files you can specify now** under `tickets/` — then wire `Blocked by:`
   edges in a **second pass** (tickets need their titles/filenames before they can reference
   each other). Everything you can't yet specify stays in Not yet specified.
5. **Stop** — charting is one session's work; do not also resolve tickets.

### Work through the map

User invokes with a map path. A ticket is optional — without one, pick the next frontier
ticket, not the user.

1. Load `MAP.md` — the low-res view, not every ticket file.
2. Choose the ticket. If the user named one, use it. Otherwise take the first frontier
   ticket (see frontier rule above). **Claim it**: write your name into `Assignee:` before
   any work.
3. Resolve it — zoom as needed: read the full body of any related or closed ticket on
   demand; invoke the skills the map's `## Notes` names (usually `grilling` and
   `domain-modeling`).
4. Record the resolution: append a `## Resolution` section to the ticket with the answer,
   flip `Status:` to `closed`, and append a one-line pointer to the map's Decisions so far.
5. Add newly-surfaced tickets (create, then wire `Blocked by:`); graduate any fog the answer
   made specifiable, clearing it from Not yet specified. If the answer reveals a ticket sits
   beyond the destination, rule it out of scope instead of resolving it on the route.

The operator may work unblocked tickets in parallel across sessions, so re-scan `tickets/`
each session rather than trusting a stale frontier list.

## HITL loop

For `grilling`/`prototype` tickets, use `AskUserQuestion` one question at a time when running
in a Claude/Cursor host; under headless `skw run` this degrades to the prompt-driven exchange
the kit already uses for other stages.

## When the map is done

When `Not yet specified` is empty and no ticket files remain open, the destination is clear.
Tell the operator the map is ready to graduate — its Destination becomes the seed for
`spec/<slug>/spec.md` via the kit's `specify` phase (see `spec-kit-wave/agents/wayfinder.md`).
