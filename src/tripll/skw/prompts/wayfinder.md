# wayfinder — chart or work through the pre-spec map

Clear pre-spec fog for a destination too big for one session: chart a shared **map** of
decision tickets under the resolved wayfinder maps dir, or resolve the next frontier ticket
on an existing map. Optional phase before `specify`. Do not edit product code, run builds,
or commit.

## Step 1 — Load context

Read the injected block below. If **Map path** already exists, this session is **work
through the map**; otherwise it is **chart the map**. Resolve `{context.*}` /
`{wayfinder.maps_dir}` values from the injected paths — never hardcode them.

## Step 2 — Chart the map (no `MAP.md` yet)

1. Grill (kit `grilling` skill) to name the **Destination** — settle this first, it fixes
   scope for everything else.
2. Grill again, breadth-first, to surface the frontier. If this surfaces no fog, stop and
   tell the operator the job fits one session — no map needed.
3. Write **Map path** with Destination and Notes filled in, Decisions-so-far empty, and the
   fog sketched into Not yet specified.
4. Create the ticket files you can specify now under **Tickets dir**, then wire `Blocked by:`
   edges in a second pass.
5. Stop — do not also resolve a ticket this session.

## Step 3 — Work through the map (`MAP.md` exists)

1. Load **Map path** (low-res view only).
2. Choose the ticket: the one the operator named, or the first frontier ticket (open,
   unblocked, unclaimed) found by scanning **Tickets dir**. Claim it by writing your name
   into its `Assignee:` line before any work.
3. Resolve it — invoke `grilling` / `domain-modeling` for HITL types; zoom into related or
   closed tickets on demand.
4. Append a `## Resolution` section to the ticket, flip `Status:` to `closed`, and append a
   one-line pointer to the map's Decisions so far.
5. Add newly-surfaced tickets (create, then wire); graduate any fog the answer made
   specifiable, clearing it from Not yet specified.
6. Never resolve more than one ticket per session.

## Step 4 — Handoff check

When Not yet specified is empty and no ticket file remains `Status: open`, tell the operator
the destination is clear and ready to graduate into **Spec handoff path** via `specify`.

## Self-check

- [ ] Wrote or updated only files under **Wayfinder maps dir**.
- [ ] Charting sessions created no ticket resolutions; resolving sessions closed **at most
      one** ticket.
- [ ] HITL ticket types (`grilling`, `prototype`) were resolved through live exchange, never
      answered on the operator's behalf.
- [ ] No open fog silently dropped — left in Not yet specified or as an open ticket.
- [ ] Nothing built, tested, or committed.

<!-- INJECTED -->

Title: {{TITLE}}
Slug: {{SLUG}}
Base: {{BASE}} | Branch: {{BRANCH}}
Output: {{OUTPUT_DIR}}

Glossary: {{GLOSSARY_PATH}}
Decisions dir: {{DECISIONS_DIR}}
Wayfinder maps dir: {{WAYFINDER_MAPS_DIR}}
Map path: {{MAP_PATH}}
Tickets dir: {{TICKETS_DIR}}

Operator context:
{{OPERATOR_CONTEXT}}

Spec handoff path: {{SPEC_PATH}}

Wayfinder agent: wayfinder
Wayfinder prompt: prompts/wayfinder.md
