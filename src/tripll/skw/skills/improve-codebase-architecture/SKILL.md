---
name: improve-codebase-architecture
description: >-
  Scan a codebase for deepening opportunities, present them as a
  self-contained HTML report, then grill through whichever one you pick.
disable-model-invocation: true
---

# Improve Codebase Architecture

**Provenance:** derived from [mattpocock/skills/engineering/improve-codebase-architecture](https://github.com/mattpocock/skills) (MIT).

Surface architectural friction and propose **deepening opportunities** —
refactors that turn shallow modules into deep ones. The aim is testability
and AI-navigability.

This command is _informed_ by the project's domain model and built on a
shared design vocabulary:

- Run the kit `codebase-design` skill for the architecture vocabulary
  (**module**, **interface**, **depth**, **seam**, **adapter**,
  **leverage**, **locality**) and its principles (the deletion test, "the
  interface is the test surface", "one adapter = hypothetical seam, two =
  real"). Use these terms exactly in every suggestion — don't drift into
  "component," "service," "API," or "boundary."
- The domain language and ADRs record decisions this command should not
  re-litigate. Resolve their paths with
  `python3 src/tripll/skw/scripts/context_paths.py --slug <slug>` (run from the repo root;
  `--kit-root src/tripll/skw` when needed — find it by walking up to the directory
  containing `skw.toml`; the script prints `glossary=` and
  `decisions_dir=` as absolute paths). Never hardcode `CONTEXT.md` or
  `docs/adr/` — those paths are configured per-repo in `skw.toml`'s
  `[context]` table.

## Process

### 1. Explore

Resolve and read the project's glossary and any ADRs in the area you're
touching first (`scripts/context_paths.py`, above).

Then use the Agent tool with `subagent_type=Explore` to walk the codebase.
Don't follow rigid heuristics — explore organically and note where you
experience friction:

- Where does understanding one concept require bouncing between many small
  modules?
- Where are modules **shallow** — interface nearly as complex as the
  implementation?
- Where have pure functions been extracted just for testability, but the
  real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their
  current interface?

Apply the **deletion test** to anything you suspect is shallow: would
deleting it concentrate complexity, or just move it? A "yes, concentrates"
is the signal you want.

### 2. Present candidates as an HTML report

Run `scripts/render_report.py` with the candidates you found (see the
script's module docstring for the data shape it expects). It writes a
**self-contained** HTML file — inlined CSS, inline hand-drawn SVG
before/after diagrams, **no CDN, no client JS** — to the session scratchpad
(or `src/tripll/skw/.out/` when no scratchpad is set), prints the absolute
path, and opens it with `open` on macOS. Tell the user the absolute path
regardless of whether `open` succeeded.

For each candidate, the report renders a card with:

- **Files** — which files/modules are involved
- **Problem** — why the current architecture is causing friction
- **Solution** — plain English description of what would change
- **Benefits** — explained in terms of locality and leverage, and how
  tests would improve
- **Before / After diagram** — side-by-side inline SVG, illustrating the
  shallowness and the deepening
- **Recommendation strength** — one of `Strong`, `Worth exploring`,
  `Speculative`, rendered as a badge

The report ends with a **Top recommendation** section: which candidate
you'd tackle first and why.

**Use the glossary for the domain, and the kit `codebase-design` vocabulary
for the architecture.** If the glossary defines "Order," talk about "the
Order intake module" — not "the FooBarHandler," and not "the Order
service."

**ADR conflicts**: if a candidate contradicts an existing ADR, only surface
it when the friction is real enough to warrant revisiting the ADR. Mark it
clearly in the card (e.g. a warning callout: _"contradicts ADR-0007 — but
worth reopening because…"_). Don't list every theoretical refactor an ADR
forbids.

See `src/tripll/skw/skills/improve-codebase-architecture/references/editorial-style.md` for the
full editorial guidance — tone, diagram-pattern choices, and vocabulary
discipline — behind what `render_report.py` renders.

Do NOT propose interfaces yet. After the file is written, ask the user:
"Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, run the kit `grilling` skill to walk the
design tree with them — constraints, dependencies, the shape of the
deepened module, what sits behind the seam, what tests survive.

Side effects happen inline as decisions crystallize — run the kit
`domain-modeling` skill to keep the domain model current as you go:

- **Naming a deepened module after a concept not in the glossary?** Add the
  term to the glossary (`scripts/context_paths.py` -> `glossary`). Create
  the file lazily if it doesn't exist.
- **Sharpening a fuzzy term during the conversation?** Update the glossary
  right there.
- **User rejects the candidate with a load-bearing reason?** Offer an ADR,
  framed as: _"Want me to record this as an ADR so future architecture
  reviews don't re-suggest it?"_ Only offer when the reason would actually
  be needed by a future explorer to avoid re-suggesting the same thing —
  skip ephemeral reasons ("not worth it right now") and self-evident ones.
- **Want to explore alternative interfaces for the deepened module?** Run
  the kit `codebase-design` skill and use its design-it-twice parallel
  sub-agent pattern.
