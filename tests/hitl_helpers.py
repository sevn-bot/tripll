"""Shared helpers for completing HITL in engine and API tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tripll import hitl

if TYPE_CHECKING:
    from tripll.engine import Engine


def complete_hitl_responses(run_dir: Path, run_id: str) -> None:
    """Fill ``hitl-responses.json`` with recommended or default answers."""
    form = hitl.load_form(run_dir)
    if form is None:
        return
    answers: list[hitl.HitlAnswer] = []
    for q in form.questions:
        if q.type == "confirm":
            answers.append(hitl.HitlAnswer(question_id=q.id, checked=True))
            continue
        if not q.options:
            continue
        opt = next((o for o in q.options if o.recommended), q.options[0])
        answers.append(hitl.HitlAnswer(question_id=q.id, option_id=opt.id))
    responses = hitl.HitlResponses(
        run_id=run_id,
        form_id=form.form_id,
        gate_kind=form.gate_kind,
        status="submitted",
        answers=answers,
    )
    hitl.save_responses(run_dir, responses)
    if form.gate_kind == hitl.GateKind.PRE0.value:
        hitl.write_decisions_sheet(run_dir, form, responses)


def approve_run_with_hitl(engine: Engine, run_id: str) -> None:
    """Complete HITL responses then approve the pending gate."""
    run_dir = engine.runs_root.run_dir(run_id)
    complete_hitl_responses(run_dir, run_id)
    engine.approve(run_id)
