# Report style guide

Editorial guidance behind `scripts/render_report.py`'s output. The
renderer already implements the layout below — this file is for tuning the
*content* you feed it (candidate copy, diagram labels) so the report reads
right, not for re-deriving the HTML.

**Provenance:** derived from
mattpocock/skills/engineering/improve-codebase-architecture/HTML-REPORT.md
(MIT). The upstream scaffold used Tailwind + Mermaid via CDN; this repo's
kit rule (helper scripts are Python/sh only; generated HTML must be
self-contained, no CDN, no client JS) replaced it with inlined CSS and
hand-drawn inline SVG in `render_report.py`. The editorial voice below is
unchanged.

## What the renderer draws

`render_report.py` renders exactly two diagram shapes per candidate — feed
it `before_modules` (a chain of shallow module names) and `after_module` /
`after_internals` (one deep module with its now-internal calls shown
faded inside it). This is the **call-graph collapse** pattern: before, a
row of small boxes each doing one thin thing; after, one thick-bordered box
with the same responsibilities folded inside, faded to signal "no longer a
caller's concern." Pick module names for `before_modules` that actually
name the shallow hops (not generic labels like "Layer 1") — the diagram
carries the weight, so vague labels waste it.

If a candidate's shape doesn't fit collapse (e.g. it's about interface
surface area, not a call chain), you can still describe it faithfully
through the same two lists — list the *before* concerns as separate
"modules" and the *after* concerns as the *internals* of one deep module.
Don't invent a third diagram shape in the input JSON; the renderer only
draws these two.

## Candidate card content

- **Title** — short, names the deepening (e.g. "Collapse the Order intake
  pipeline").
- **Strength** — `Strong`, `Worth exploring`, or `Speculative`. Pick
  honestly; don't inflate to make the report look more actionable.
- **Tags** — dependency category, e.g. `in-process`, `local-substitutable`,
  `ports & adapters`, `mock`.
- **Files** — the modules/files actually involved (monospaced in the
  rendered card automatically).
- **Problem** — one sentence. What hurts.
- **Solution** — one sentence. What changes.
- **Wins** — bullets, ≤6 words each, e.g. "Tests hit one interface",
  "Pricing logic stops leaking", "Delete 4 shallow wrappers".
- **ADR callout** (optional) — one line, only when a candidate genuinely
  contradicts a recorded decision worth reopening.

No paragraphs of explanation. If a candidate's problem/solution needs a
paragraph to land, the diagram is probably wrong — fix the module lists
instead of padding the prose.

## Tone

Plain English, concise — but the architectural nouns and verbs come
straight from the kit `codebase-design` skill. Concision is not an excuse
to drift.

**Use exactly:** module, interface, implementation, depth, deep, shallow,
seam, adapter, leverage, locality.

**Never substitute:** component, service, unit (for module) · API,
signature (for interface) · boundary (for seam) · layer, wrapper (for
module, when you mean module).

**Phrasings that fit the style:**

- "Order intake module is shallow — interface nearly matches the
  implementation."
- "Pricing leaks across the seam."
- "Deepen: one interface, one place to test."
- "Two adapters justify the seam: HTTP in prod, in-memory in tests."

**Wins bullets** name the gain in glossary terms: _"locality: bugs
concentrate in one module"_, _"leverage: one interface, N call sites"_,
_"interface shrinks; implementation absorbs the wrappers"_. Don't write
_"easier to maintain"_ or _"cleaner code"_ — those terms aren't in the
glossary and don't earn their place.

No hedging, no throat-clearing, no "it's worth noting that…". If a
sentence could be a bullet, make it a bullet. If a bullet could be cut, cut
it. If a term isn't in the kit `codebase-design` glossary, reach for one
that is before inventing a new one.

## Top recommendation

One larger card. Candidate name, one sentence on why. That's it — the
renderer wires the anchor link automatically.
