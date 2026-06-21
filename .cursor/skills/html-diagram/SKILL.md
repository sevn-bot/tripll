---
name: html-diagram
description: Create a self-contained HTML file for visualizing architecture and understanding the stack with a high-quality SVG diagram. Use when the user wants a full-screen diagram, wants the output to be light on prose, or wants an HTML artifact that is mostly there to make the architecture click fast.
disable-model-invocation: true
---

# HTML Diagram

Build a **full-screen, sevn-styled, interactive SVG architecture diagram** in one self-contained `.html` file.

## Start here

1. **Copy the shell** from `references/diagram-shell.html` — it has the required chrome (sevn tokens, pan/zoom, single-click detail, auto-edges, flow chips, theme, legend).
2. Skim `references/html-effectiveness/04-code-understanding.html`, `10-svg-illustrations.html`, `13-flowchart-diagram.html` for layout ideas only.
3. Spend most effort on **node placement** and **EDGE_DEFS accuracy** — arrows are auto-routed; you do not hand-draw paths.

## sevn.bot visual style

Diagrams in this repo use the **sevn design system** (`styles/sevn/style/`). Do **not** invent a parallel palette.

- **Inline the token block** from `diagram-shell.html` (colors from `tokens/colors.css`, roles from `theme-dark.css` / `theme-light.css`, fonts from `tokens/typography.css`). Self-contained HTML cannot `@import` repo CSS paths.
- **Fonts:** Inter Tight (UI), JetBrains Mono (labels/code).
- **Colors:** warm slate-black surfaces; **primary** `#5fb1f7` for flow highlight and selection; **accent** `#ff3b3b` for gates/critical only — never decorative.
- **Theme:** `data-theme="dark|light"` on `<html>`, persisted as `localStorage['sevn-theme']`, default dark. Apply before paint in `<head>`.
- **SVG styling:** CSS classes referencing `var(--sevn-*)` — no hard-coded hex inside SVG markup.
- **Node types:**

| Class | Meaning | Fill |
|-------|---------|------|
| _(default)_ | General module / class | surface-1 |
| `.gate` | Decision / guard / scanner | accent tint |
| `.exec` | Executor / harness / worker | success tint |
| `.store` | Persistent storage / registry | surface-2 (raised) |
| `.ext` | External channel adapter (dashed border) | surface-1 + dashed stroke |

## Required interactions

| Gesture | Behavior |
|---------|----------|
| **Single click** node | Detail panel (select highlight) showing kind, symbol, path:line, description |
| **Scroll wheel** | Zoom toward cursor |
| **+ / − / Fit / R** buttons | Zoom in, out, fit-to-viewport, reset |
| **Drag background** | Pan the diagram |
| **Flow chips** | Dim diagram; animate lit edges; show step list |
| **`/`** | Focus search — filter nodes by title, symbol, path, detail text |
| **Related chips** | In detail panel — click to jump and open that node |
| **Keyboard** | `+` `−` `0` (fit) `R` (reset) `Esc` (dismiss detail) |
| **Legend** | Fixed overlay — gate / exec / store / ext color semantics always visible |

Copy `focusNode()` and `showDetail()` from `diagram-shell.html`. **No popover** — one click opens detail directly.

## Node naming rules (critical)

Every node must anchor to **real code**, not abstract pipeline labels.

| Node `.t` (title) | Must be |
|-------------------|---------|
| Class | `TelegramAdapter`, `SessionManager`, `CommandDispatcher` |
| Function | `build_agent_run_turn`, `triage_turn`, `run_b_turn` |
| Method | `SessionManager.add_message`, `ChannelRouter.route_outgoing` |
| Branch | `_run() tier dispatch` — label the **function + branch**, not "Complexity fork" |

Set `.m` to the **full file path from repo root** under `src/sevn/` (e.g. `src/sevn/gateway/agent_turn.py`, not just `gateway/agent_turn.py`). In `DETAIL`, always include:

- `kind`: `class` \| `function` \| `method` \| `module` \| `branch` \| `store`
- `symbol`: exact Python symbol (must match grep output)
- `m`: full file path from repo root
- `line`: line number where the class/function is defined (shown as `path:LINE` in the panel)
- `b`: 2–4 sentences — what it does, callers/callees, failure behavior
- `spec` / `related` when useful

If logic is inline (no class), use `kind: 'branch'` and name the enclosing function (e.g. `agent_turn._run`).

Do **not** omit infrastructure nodes that sit on the critical path between input and output — `CascadeBudget`, `LoadedBodyCache`, and similar wiring classes belong in the diagram if they are on every turn's hot path.

### DETAIL schema

Each `DETAIL[key]` should be **substantive** — this is the only prose surface. Minimum per node:

```javascript
{
  t: 'Human title',            // matches node .t text exactly
  kind: 'class',               // class | function | method | module | branch | store
  symbol: 'SessionManager',    // exact Python symbol — must match grep
  m: 'src/sevn/gateway/session_manager.py',  // full path from repo root
  line: 42,                    // line number of class/def — shown as path:42 in panel
  b: '2–4 sentences HTML: what it does, what it calls, failure/edge behavior, <code> symbols',
  // optional:
  spec: 'specs/17-gateway.md §2.6',
  related: ['other-key'],      // "See also" chips
}
```

Gate nodes: explain what blocks vs passes. Store nodes: what is persisted. Exec nodes: pass sequence / escalation. Ext nodes: adapter contract.

## Verify symbols before writing DETAIL (mandatory)

Class names and function names in Python are case-sensitive. Before writing any `DETAIL` entry, run:

```bash
grep -rn "class SymbolName\|def symbol_name" src/sevn/
```

Use the exact output to fill `m` and `line`. Common pitfall: multi-word adapter names often differ in capitalization (`WebChatAdapter` not `WebchatAdapter`, `ToolSet` not `SessionToolSet`). Never guess — always grep.

**Self-check before delivery:** for every DETAIL entry, the following must be true:

```
grep -n "class <symbol>\|def <symbol>" src/sevn/<m> | grep -q "^<line>:"
```

If that fails, correct `symbol`, `m`, or `line` before saving.

## Arrow / edge placement (critical)

**Never hand-author SVG `<path d="M…">` for edges.** Misaligned arrows are the #1 failure mode.

1. Place nodes as `<g class="node" data-k="key">` with an inner `<rect x y width height>` — explicit numbers only.
2. Define connectivity in a JS `EDGES` array: `{ id, from, to, label?, dash? }`.
3. Call `renderEdges()` on load — the shell routes cubic beziers from rect anchors (right→left or bottom→top by relative position).
4. Re-run `renderEdges()` if you ever move nodes programmatically.
5. Keep **≥ 48px gap** between node rects so labels and arrows do not collide.
6. Lay nodes on a **grid** (columns = pipeline stages, rows = parallel branches) — free-form placement causes routing crosses.

Optional overrides per edge: `fromSide` / `toSide` (`r|l|t|b`) when auto-pick picks the wrong face — see shell `pickAnchors()`. Use these whenever edges cross zone boundaries or route through a dense area.

## Diagram content rules

- Not prose-heavy — the SVG is the artifact; text lives in `DETAIL` and flow step lists.
- Zones: dashed `<rect>` backgrounds with mono uppercase titles.
- Module paths in node `.m` lines and detail `.meta`.
- Source citation: small mono line (spec path · primary modules).
- `prefers-reduced-motion`: disable edge march animation.

## Cursor workflow

1. Read `references/diagram-shell.html` and copy its `<style>`, stage structure, and `<script>` runtime.
2. Replace placeholder nodes with your architecture; expand `DETAIL`, `FLOWS`, `EDGES`.
3. **Grep every symbol** (see verification section above) — fill in `m` and `line` from grep output.
4. Tune `viewBox` to content bounds + 40px padding.
5. Call `fitView()` on load so the diagram fills the viewport.
6. Save to `docs/<topic>-architecture.html` for drafts; canonical copies may ship under `about-sevn.bot/` (GitHub Pages) per operator preference.
7. Open locally and verify layout: **`</div>` closes `.bar` before `.stage`** — a missing close tag nests the stage inside the bar and hides the SVG.

## Verification checklist (before delivering)

1. Open the HTML file in a browser — do not only inspect code.
2. **Fit** on load — full diagram visible without scrolling.
3. Click 3 nodes — detail panel opens for each; `path:line` is present and correct.
4. For every DETAIL entry: `grep -n "class <symbol>\|def <symbol>" <m>` returns the correct line.
5. Activate each flow chip — lit edges connect the right nodes.
6. Toggle theme — detail and SVG follow dark/light.
7. Legend is visible in the corner with correct color–role mapping.
8. No node uses an approximate or guessed class name (`WebchatAdapter`, `SessionToolSet` style errors are caught by step 4).

## Improvement backlog (prioritize with operator)

| Idea | Value |
|------|-------|
| **Edge side overrides** (`fromSide`/`toSide`) | Fixes ugly auto-routes on dense diagrams |
| **Deep links** `?node=triager` | Shareable URL to focused node + detail open |
| **HTML popover fallback** | For nodes with 3+ `.m` lines — render card in HTML not SVG clone |
| **Minimap** | viewBox width > 2000 only |
| **Export PNG** | canvas snapshot for PRs |
| **Collapsible zones** | Hide column to reduce clutter |
| **Shared `diagram-runtime.js`** | DRY across docs — tradeoff: breaks single-file rule |
| **Fit-view math fix** | Pan/zoom translate should be viewport-aware (shell known rough edge) |
| **Touch: long-press** | Detail panel on mobile where dblclick is awkward |

## Provenance

Adapted from [plannotator/effective-html](https://github.com/plannotator/effective-html). sevn styling from `styles/sevn/style/`. Example corpus from [html-effectiveness](https://thariqs.github.io/html-effectiveness) (Thariq Shihipar).
