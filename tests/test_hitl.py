"""Tests for tripll.hitl."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripll.hitl import (
    GateKind,
    HitlAnswer,
    HitlResponses,
    RunHitlContext,
    approve_gate,
    build_form,
    build_options_for_gate,
    detect_pending_gate,
    responses_complete,
    validate_responses,
    write_decisions_sheet,
    write_form,
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


def test_build_options_d1_gate() -> None:
    decisions = {"D1": ("Rich payload", "Structured tree + fast path")}
    opts = build_options_for_gate(_D1_GATE, decisions)
    assert len(opts) >= 3
    assert opts[0].recommended is True


def test_form_generation_and_validation(tmp_path: Path) -> None:
    run_id = "demo-run"
    run_dir = tmp_path / "processing" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "demo-wave-plan.md").write_text(_PLAN_SNIPPET)
    ctx = RunHitlContext(
        run_id=run_id,
        run_dir=run_dir,
        gates=[_D1_GATE],
        plan_path=run_dir / "demo-wave-plan.md",
        decisions={"D1": ("Rich payload", "Structured tree + fast path")},
    )
    form = build_form(ctx)
    write_form(run_dir, form)
    assert (run_dir / "hitl-form.json").is_file()

    q = form.questions[0]
    opt = next(o for o in q.options if o.recommended)
    responses = HitlResponses(
        run_id=run_id,
        form_id=form.form_id,
        gate_kind=GateKind.PRE0.value,
        answers=[
            HitlAnswer(question_id=q.id, option_id=opt.id, notes=""),
        ],
    )
    assert not validate_responses(form, responses)
    write_decisions_sheet(run_dir, form, responses)
    assert "[x]" in (run_dir / "pre0-decisions.md").read_text()


def test_approve_gate_requires_responses(tmp_path: Path) -> None:
    run_dir = tmp_path / "processing" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "pre0-decisions.md").write_text("1. [ ] gate\n")
    (run_dir / "graph.json").write_text(json.dumps({"pre0_gates": ["gate one"]}))
    assert detect_pending_gate(run_dir) is not None
    with pytest.raises(ValueError, match="HITL form"):
        approve_gate(run_dir)


def test_responses_complete_false_without_form(tmp_path: Path) -> None:
    run_dir = tmp_path / "processing" / "r2"
    run_dir.mkdir(parents=True)
    assert responses_complete(run_dir) is False
