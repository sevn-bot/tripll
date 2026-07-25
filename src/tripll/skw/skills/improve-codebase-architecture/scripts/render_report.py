#!/usr/bin/env python3
"""Render a self-contained architecture-review HTML report.

Used by the ``improve-codebase-architecture`` skill's Phase 2. Replaces the
upstream Tailwind-via-CDN + Mermaid-via-CDN scaffold (see
``references/report-style.md`` for the editorial guidance that survived the
port) with **inlined CSS** and **hand-drawn inline SVG** before/after
diagrams — no CDN, no external fetch, no client JS (kit rule: helper
scripts are Python/sh only, and generated HTML must be fully self-contained).

Input is a JSON document (file path via ``--input``, or stdin) shaped like::

    {
      "repo_name": "sevn.bot",
      "candidates": [
        {
          "title": "Collapse the Order intake pipeline",
          "strength": "Strong",              // Strong | Worth exploring | Speculative
          "tags": ["in-process", "ports & adapters"],
          "files": ["src/sevn/orders/intake.py", "src/sevn/orders/validate.py"],
          "problem": "Understanding intake requires bouncing across 5 modules.",
          "solution": "Merge validate/normalize/dispatch behind one Intake interface.",
          "wins": ["locality: bugs concentrate in one module", "interface shrinks"],
          "before_modules": ["Handler", "Validator", "Normalizer", "Dispatcher", "Repo"],
          "after_module": "OrderIntake",
          "after_internals": ["validate", "normalize", "dispatch"],
          "adr_callout": "contradicts ADR-0007 -- worth reopening because ..."  // optional
        }
      ],
      "top_recommendation": "Collapse the Order intake pipeline",
      "top_recommendation_reason": "Highest friction, smallest blast radius."
    }

Usage:
    python3 render_report.py --input candidates.json
    python3 render_report.py < candidates.json
    python3 render_report.py --demo   # smoke-test with built-in sample data

Prints the absolute path of the written HTML file to stdout as the final
line, and opens it with ``open`` on macOS (best-effort; never raises).

**Provenance:** derived from
mattpocock/skills/engineering/improve-codebase-architecture (MIT) — the
Phase-2 report step of ``SKILL.md`` and the diagram/style guidance of
``HTML-REPORT.md``, rewritten to a no-CDN stdlib renderer per this repo's
locked decision D2/D5.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_STRENGTH_STYLE = {
    "Strong": ("#065f46", "#d1fae5"),
    "Worth exploring": ("#92400e", "#fef3c7"),
    "Speculative": ("#334155", "#e2e8f0"),
}

_BOX_W = 108
_BOX_H = 34
_GAP = 24


@dataclass
class Candidate:
    """One deepening-opportunity card in the report."""

    title: str
    strength: str
    files: list[str]
    problem: str
    solution: str
    wins: list[str]
    before_modules: list[str]
    after_module: str
    after_internals: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    adr_callout: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candidate:
        """Build a Candidate from a parsed JSON object, tolerating omissions."""
        return cls(
            title=str(data["title"]),
            strength=str(data.get("strength", "Worth exploring")),
            files=[str(f) for f in data.get("files", [])],
            problem=str(data.get("problem", "")),
            solution=str(data.get("solution", "")),
            wins=[str(w) for w in data.get("wins", [])],
            before_modules=[str(m) for m in data.get("before_modules", [])],
            after_module=str(data.get("after_module", "")),
            after_internals=[str(m) for m in data.get("after_internals", [])],
            tags=[str(t) for t in data.get("tags", [])],
            adr_callout=(str(data["adr_callout"]) if data.get("adr_callout") else None),
        )


@dataclass
class Report:
    """Top-level report document."""

    repo_name: str
    candidates: list[Candidate]
    top_recommendation: str
    top_recommendation_reason: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Report:
        """Build a Report from a parsed JSON object."""
        return cls(
            repo_name=str(data.get("repo_name", "this repo")),
            candidates=[Candidate.from_dict(c) for c in data.get("candidates", [])],
            top_recommendation=str(data.get("top_recommendation", "")),
            top_recommendation_reason=str(data.get("top_recommendation_reason", "")),
        )


def _esc(text: str) -> str:
    """HTML-escape text for safe interpolation into the report."""
    return html.escape(text, quote=True)


def _box(
    label: str, x: float, y: float, w: float, h: float, *, deep: bool = False, faded: bool = False
) -> str:
    """Render one module box as inline SVG."""
    fill = "#0f172a" if deep else "#ffffff"
    stroke = "#0f172a" if deep else "#334155"
    text_fill = "#f8fafc" if deep else "#0f172a"
    stroke_w = "2.5" if deep else "1.5"
    opacity = "0.55" if faded else "1"
    return (
        f'<g opacity="{opacity}">'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}" />'
        f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" text-anchor="middle" '
        f'dominant-baseline="middle" font-size="10.5" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
        f'fill="{text_fill}" letter-spacing="0.02em">{_esc(label)}</text>'
        f"</g>"
    )


def _arrow(x1: float, y1: float, x2: float, y2: float, *, leak: bool = False) -> str:
    """Render a connecting arrow between two boxes as inline SVG."""
    stroke = "#dc2626" if leak else "#64748b"
    dash = ' stroke-dasharray="4 3"' if leak else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2 - 5:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="1.6"{dash} marker-end="url(#seam-arrow)" />'
    )


def _before_svg(modules: list[str]) -> str:
    """Chain-of-shallow-boxes diagram: many small modules, one per hop."""
    if not modules:
        modules = ["(unspecified)"]
    height = _BOX_H + 20
    width = len(modules) * _BOX_W + max(0, len(modules) - 1) * _GAP + 16
    y = 10.0
    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" role="img" aria-label="before: shallow chain">'
    ]
    x = 8.0
    for i, name in enumerate(modules):
        parts.append(_box(name, x, y, _BOX_W, _BOX_H))
        if i < len(modules) - 1:
            leak = i == len(modules) - 2 and len(modules) > 2
            parts.append(
                _arrow(x + _BOX_W, y + _BOX_H / 2, x + _BOX_W + _GAP, y + _BOX_H / 2, leak=leak)
            )
        x += _BOX_W + _GAP
    parts.append("</svg>")
    return "".join(parts)


def _after_svg(module: str, internals: list[str]) -> str:
    """One thick deep-module box with faded internal labels stacked inside."""
    inner_h = 18
    inner_gap = 4
    internals = internals or ["(implementation)"]
    body_h = len(internals) * (inner_h + inner_gap) + inner_gap
    box_h = body_h + 34
    box_w = max(_BOX_W + 40, max((len(s) for s in [module, *internals]), default=8) * 7 + 24)
    height = box_h + 20
    width = box_w + 16
    y = 10.0
    x = 8.0
    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" role="img" aria-label="after: deep module">'
    ]
    parts.append(_box(module.upper(), x, y, box_w, 26, deep=True))
    iy = y + 30
    for name in internals:
        parts.append(_box(name, x + 10, iy, box_w - 20, inner_h, faded=True))
        iy += inner_h + inner_gap
    parts.append("</svg>")
    return "".join(parts)


def _candidate_card(c: Candidate) -> str:
    """Render one candidate as an HTML article."""
    strength_fg, strength_bg = _STRENGTH_STYLE.get(c.strength, _STRENGTH_STYLE["Speculative"])
    tags_html = "".join(f'<span class="tag">{_esc(t)}</span>' for t in c.tags)
    files_html = "".join(f"<li>{_esc(f)}</li>" for f in c.files) or "<li>(none listed)</li>"
    wins_html = "".join(f"<li>{_esc(w)}</li>" for w in c.wins)
    adr_html = f'<div class="adr-callout">{_esc(c.adr_callout)}</div>' if c.adr_callout else ""
    anchor = _esc(c.title).lower().replace(" ", "-")
    return f"""
<article class="card" id="candidate-{anchor}">
  <div class="card-head">
    <h3>{_esc(c.title)}</h3>
    <div class="badges">
      <span class="strength" style="color:{strength_fg};background:{strength_bg}">{_esc(c.strength)}</span>
      {tags_html}
    </div>
  </div>
  <div class="diagrams">
    <div class="diagram">
      <div class="diagram-label">Before</div>
      {_before_svg(c.before_modules)}
    </div>
    <div class="diagram">
      <div class="diagram-label">After</div>
      {_after_svg(c.after_module, c.after_internals)}
    </div>
  </div>
  <p class="problem"><strong>Problem</strong> {_esc(c.problem)}</p>
  <p class="solution"><strong>Solution</strong> {_esc(c.solution)}</p>
  <ul class="wins">{wins_html}</ul>
  {adr_html}
  <div class="files">
    <div class="diagram-label">Files</div>
    <ul>{files_html}</ul>
  </div>
</article>
""".strip()


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "Segoe UI", ui-sans-serif, system-ui, sans-serif;
  background: #fafaf9;
  color: #0f172a;
}
@media (prefers-color-scheme: dark) {
  body { background: #0b0f16; color: #e2e8f0; }
  .card { background: #0f1520 !important; border-color: #1f2937 !important; }
  .tag { background: #1f2937 !important; color: #cbd5e1 !important; }
  .adr-callout { background: #3f2d0f !important; color: #fde68a !important; }
  .files ul, .wins { color: #cbd5e1; }
}
main { max-width: 960px; margin: 0 auto; padding: 48px 24px 80px; }
header { margin-bottom: 40px; }
header h1 { font-size: 1.6rem; margin: 0 0 4px; }
header .meta { font-size: 0.85rem; opacity: 0.7; }
.legend { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 14px; font-size: 0.78rem; opacity: 0.75; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .swatch { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
section.candidates { display: flex; flex-direction: column; gap: 32px; }
.card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 24px;
}
.card-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.card-head h3 { margin: 0; font-size: 1.15rem; }
.badges { display: flex; gap: 8px; flex-wrap: wrap; }
.strength { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; padding: 3px 8px; border-radius: 999px; }
.tag { font-size: 0.72rem; padding: 3px 8px; border-radius: 999px; background: #f1f5f9; color: #334155; }
.diagrams { display: flex; gap: 24px; flex-wrap: wrap; margin: 16px 0; overflow-x: auto; }
.diagram { flex: 1 1 320px; }
.diagram-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.6; margin-bottom: 4px; }
.diagram svg { max-width: 100%; height: auto; }
p.problem, p.solution { margin: 8px 0; line-height: 1.5; }
.wins { margin: 12px 0; padding-left: 20px; }
.wins li { margin: 3px 0; }
.adr-callout {
  margin: 12px 0;
  padding: 10px 14px;
  border-radius: 6px;
  background: #fef3c7;
  color: #92400e;
  font-size: 0.85rem;
}
.files ul { margin: 4px 0 0; padding-left: 20px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.82rem; }
.top-recommendation {
  margin-top: 48px;
  padding: 24px;
  border-radius: 10px;
  border: 2px solid #0f172a;
}
@media (prefers-color-scheme: dark) { .top-recommendation { border-color: #64748b; } }
.top-recommendation h2 { margin: 0 0 6px; font-size: 1.05rem; }
.top-recommendation a { color: inherit; }
"""


def render_html(report: Report) -> str:
    """Render the full self-contained HTML document for a Report."""
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    cards = (
        "\n".join(_candidate_card(c) for c in report.candidates) or "<p>No candidates found.</p>"
    )
    top_anchor = report.top_recommendation.lower().replace(" ", "-")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Architecture review — {_esc(report.repo_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute">
  <defs>
    <marker id="seam-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L6,3 L0,6 Z" fill="#64748b" />
    </marker>
  </defs>
</svg>
<main>
  <header>
    <h1>Architecture review — {_esc(report.repo_name)}</h1>
    <div class="meta">Generated {generated_at}</div>
    <div class="legend">
      <span><span class="swatch" style="background:#ffffff;border:1.5px solid #334155"></span> module</span>
      <span><span class="swatch" style="background:#0f172a"></span> deep module</span>
      <span><span class="swatch" style="background:#dc2626"></span> leakage</span>
      <span><span class="swatch" style="background:#e2e8f0"></span> shallow / faded internals</span>
    </div>
  </header>
  <section class="candidates">
{cards}
  </section>
  <section class="top-recommendation" id="top-recommendation-{_esc(top_anchor)}">
    <h2>Top recommendation: {_esc(report.top_recommendation) or "(none selected)"}</h2>
    <p>{_esc(report.top_recommendation_reason)}</p>
  </section>
</main>
</body>
</html>
"""


def _default_out_dir() -> Path:
    """Pick the output directory: an env-declared scratchpad, else kit .out/."""
    for var in ("SEVN_SCRATCHPAD_DIR", "CLAUDE_SCRATCHPAD_DIR"):
        raw = os.environ.get(var)
        if raw:
            return Path(raw)
    kit_root = Path(__file__).resolve().parent.parent.parent.parent
    return kit_root / ".out"


def write_report(report: Report, out_dir: Path | None = None) -> Path:
    """Render and write the report HTML file, returning its absolute path."""
    target_dir = out_dir or _default_out_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = target_dir / f"architecture-review-{timestamp}.html"
    out_path.write_text(render_html(report), encoding="utf-8")
    return out_path.resolve()


def _open_in_browser(path: Path) -> None:
    """Best-effort ``open`` on macOS; never raises."""
    if platform.system() != "Darwin":
        return
    try:
        subprocess.run(["open", str(path)], check=False, timeout=10)
    except Exception:
        pass


_DEMO_REPORT: dict[str, Any] = {
    "repo_name": "demo-repo",
    "candidates": [
        {
            "title": "Collapse the Order intake pipeline",
            "strength": "Strong",
            "tags": ["in-process", "ports & adapters"],
            "files": ["src/orders/handler.py", "src/orders/validator.py", "src/orders/repo.py"],
            "problem": "Understanding intake requires bouncing across 5 shallow modules.",
            "solution": "Merge validate/normalize/dispatch behind one Intake interface.",
            "wins": [
                "locality: bugs concentrate in one module",
                "interface shrinks; implementation absorbs wrappers",
            ],
            "before_modules": ["Handler", "Validator", "Normalizer", "Dispatcher", "Repo"],
            "after_module": "OrderIntake",
            "after_internals": ["validate", "normalize", "dispatch"],
            "adr_callout": "contradicts ADR-0007 -- worth reopening because the split predates the current call pattern.",
        },
        {
            "title": "Fold PricingClient behind PricingModule",
            "strength": "Worth exploring",
            "tags": ["local-substitutable"],
            "files": ["src/pricing/client.py", "src/orders/handler.py"],
            "problem": "Pricing leaks across the seam into OrderHandler.",
            "solution": "Give Pricing a deep module interface; OrderHandler stops knowing its shape.",
            "wins": ["leverage: one interface, N call sites"],
            "before_modules": ["OrderHandler", "PricingClient", "PricingCache"],
            "after_module": "Pricing",
            "after_internals": ["quote", "cache"],
        },
    ],
    "top_recommendation": "Collapse the Order intake pipeline",
    "top_recommendation_reason": "Highest friction, smallest blast radius, and unblocks the pricing seam next.",
}


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--input", type=Path, default=None, help="Path to a candidates JSON file (default: stdin)."
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="Override the output directory.")
    parser.add_argument(
        "--demo", action="store_true", help="Render built-in sample data instead of reading input."
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Skip attempting to open the report."
    )
    args = parser.parse_args()

    if args.demo:
        data = _DEMO_REPORT
    elif args.input is not None:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        data = json.loads(sys.stdin.read())

    report = Report.from_dict(data)
    out_path = write_report(report, out_dir=args.out_dir)

    if not args.no_open:
        _open_in_browser(out_path)

    print(str(out_path))


if __name__ == "__main__":
    main()
