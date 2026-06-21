"""tripll.pre0_interview — interactive Pre-0 decision sheet helper.

Prompts the operator with multiple-choice options (plus free-text notes) and
updates ``pre0-decisions.md`` in the run directory.  Delegates form/response
logic to :mod:`tripll.hitl`.

Exports:
    DecisionOption — one multiple-choice answer.
    GateAnswer — recorded answer for one Pre-0 gate.
    load_run_context — resolve run dir + gates + optional wave plan.
    build_options_for_gate — derive choices from gate text and plan decisions.
    run_interview — interactive stdin loop (or *answers* override for tests).
    write_decisions_sheet — persist answers to ``pre0-decisions.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TextIO

from tripll import hitl

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


@dataclass(frozen=True)
class DecisionOption:
    """One multiple-choice option for a Pre-0 gate."""

    label: str
    value: str
    recommended: bool = False


@dataclass
class GateAnswer:
    """Operator answer for one Pre-0 gate."""

    index: int
    gate: str
    choice_label: str
    choice_value: str
    notes: str = ""


@dataclass
class RunContext:
    """Paths and data for a paused Pre-0 run."""

    run_id: str
    run_dir: Path
    gates: list[str]
    plan_path: Path | None = None
    decisions: dict[str, tuple[str, str]] = field(default_factory=dict)


def load_run_context(run_id: str, *, runs_root: Path | None = None) -> RunContext:
    """Load Pre-0 gates and optional wave plan from a processing run directory."""
    ctx = hitl.load_run_hitl_context(run_id, runs_root=runs_root)
    return RunContext(
        run_id=ctx.run_id,
        run_dir=ctx.run_dir,
        gates=ctx.gates,
        plan_path=ctx.plan_path,
        decisions=ctx.decisions,
    )


def parse_decisions_table(plan_path: Path) -> dict[str, tuple[str, str]]:
    """Return ``{D1: (topic, decision_text), ...}`` from the plan decisions table."""
    return hitl.parse_decisions_table(plan_path)


def build_options_for_gate(
    gate: str, decisions: dict[str, tuple[str, str]]
) -> list[DecisionOption]:
    """Build multiple-choice options for one Pre-0 gate."""
    return [
        DecisionOption(label=o.label, value=o.value, recommended=o.recommended)
        for o in hitl.build_options_for_gate(gate, decisions)
    ]


def _prompt_choice(
    options: Sequence[DecisionOption],
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> DecisionOption:
    out = output or __import__("sys").stdout
    for i, opt in enumerate(options, 1):
        tag = " (Recommended)" if opt.recommended else ""
        out.write(f"  {i}. {opt.label}{tag}\n")
    while True:
        raw = input_fn(f"Choice [1-{len(options)}] (Enter=1): ").strip()
        if raw == "":
            for opt in options:
                if opt.recommended:
                    return opt
            return options[0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        out.write(f"  Enter a number 1-{len(options)}, or Enter for recommended.\n")


def _prompt_notes(
    *,
    required: bool = False,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> str:
    out = output or __import__("sys").stdout
    prompt = "Your answer / notes (optional — Enter to skip): "
    if required:
        prompt = "Your answer / notes (required for Other): "
    while True:
        raw = input_fn(prompt).strip()
        if raw or not required:
            return raw
        out.write("  Please enter text for a custom answer.\n")


def _display_gate(gate: str) -> str:
    return hitl._display_gate(gate)


def run_interview(
    ctx: RunContext,
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> list[GateAnswer]:
    """Run the interactive Pre-0 interview; return recorded answers."""
    out = output or __import__("sys").stdout
    answers: list[GateAnswer] = []

    if not ctx.gates:
        out.write("No Pre-0 gates for this run.\n")
        return answers

    out.write(f"\nPre-0 interview — run {ctx.run_id}\n")
    if ctx.plan_path:
        out.write(f"Plan: {ctx.plan_path.name}\n")
    out.write("=" * 60 + "\n")

    for i, gate in enumerate(ctx.gates, 1):
        out.write(f"\nQuestion {i}/{len(ctx.gates)}\n")
        out.write(f"{_display_gate(gate)}\n\n")
        options = build_options_for_gate(gate, ctx.decisions)
        choice = _prompt_choice(options, input_fn=input_fn, output=out)
        notes = _prompt_notes(
            required="Other" in choice.label,
            input_fn=input_fn,
            output=out,
        )
        answers.append(
            GateAnswer(
                index=i,
                gate=gate,
                choice_label=choice.label,
                choice_value=choice.value,
                notes=notes,
            )
        )

    return answers


def _answers_to_hitl_responses(
    ctx: RunContext, answers: Sequence[GateAnswer], form: hitl.HitlForm
) -> hitl.HitlResponses:
    hitl_answers: list[hitl.HitlAnswer] = []
    for ans in answers:
        qid = f"gate-{ans.index}"
        q = next((qq for qq in form.questions if qq.id == qid), None)
        option_id: str | None = None
        if q and q.type == "multiple_choice":
            for opt in q.options:
                if opt.label == ans.choice_label or opt.value == ans.choice_value:
                    option_id = opt.id
                    break
            if option_id is None and q.options:
                option_id = q.options[0].id
        hitl_answers.append(
            hitl.HitlAnswer(
                question_id=qid,
                option_id=option_id,
                checked=True,
                notes=ans.notes,
            )
        )
    return hitl.HitlResponses(
        run_id=ctx.run_id,
        form_id=form.form_id,
        gate_kind=hitl.GateKind.PRE0.value,
        status="submitted",
        answers=hitl_answers,
    )


def write_decisions_sheet(ctx: RunContext, answers: Sequence[GateAnswer]) -> Path:
    """Write ``pre0-decisions.md`` with checked items and recorded choices."""
    form = hitl.build_form(
        hitl.RunHitlContext(
            run_id=ctx.run_id,
            run_dir=ctx.run_dir,
            gates=ctx.gates,
            plan_path=ctx.plan_path,
            decisions=ctx.decisions,
        )
    )
    hitl.write_form(ctx.run_dir, form)
    responses = _answers_to_hitl_responses(ctx, answers, form)
    hitl.save_responses(ctx.run_dir, responses)
    return hitl.write_decisions_sheet(ctx.run_dir, form, responses)


def interview_run(run_id: str, *, runs_root: Path | None = None) -> Path:
    """Load context, run interview on stdin, write decisions sheet."""
    ctx = load_run_context(run_id, runs_root=runs_root)
    answers = run_interview(ctx)
    if not answers:
        msg = "No answers recorded."
        raise SystemExit(msg)
    return write_decisions_sheet(ctx, answers)
