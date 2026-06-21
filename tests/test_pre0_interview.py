"""Tests for tripll.pre0_interview."""

from __future__ import annotations

import json
from pathlib import Path

from tripll.pre0_interview import (
    build_options_for_gate,
    load_run_context,
    parse_decisions_table,
    run_interview,
    write_decisions_sheet,
)

_D1_GATE = (
    "telegram-rich-inline-miniapps: W0.7 Review gate; operator confirms "
    "renderer model (structured tree vs Rich Markdown) before R2."
)

_PLAN_SNIPPET = """# Plan

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| D1 | **Rich payload model** | **Build structured tree** + Markdown fast path. (Recommended) |
"""


def test_parse_decisions_table(tmp_path: Path) -> None:
    p = tmp_path / "x-wave-plan.md"
    p.write_text(_PLAN_SNIPPET)
    rows = parse_decisions_table(p)
    assert "D1" in rows
    assert "structured tree" in rows["D1"][1]


def test_build_options_d1_gate() -> None:
    decisions = {"D1": ("Rich payload", "Structured tree + fast path")}
    opts = build_options_for_gate(_D1_GATE, decisions)
    assert len(opts) >= 3
    assert opts[0].recommended is True
    assert "D1" in opts[0].label or "structured" in opts[0].label.lower()


def test_interview_writes_sheet(tmp_path: Path) -> None:
    run_id = "demo-run"
    run_dir = tmp_path / "processing" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "graph.json").write_text(json.dumps({"pre0_gates": [_D1_GATE]}))
    (run_dir / "demo-wave-plan.md").write_text(_PLAN_SNIPPET)

    ctx = load_run_context(run_id, runs_root=tmp_path)
    answers = run_interview(ctx, input_fn=lambda _: "")
    path = write_decisions_sheet(ctx, answers)

    text = path.read_text()
    assert "[x]" in text
    assert "**Choice:**" in text
    assert "Recommended" in text or "structured" in text.lower()
