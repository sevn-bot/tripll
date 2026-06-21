"""tripll.hitl — Human-in-the-loop gate forms, responses, and approval.

Generates ``hitl-form.json`` when a run pauses at Pre-0 or a review gate,
accepts operator responses via CLI or control-plane API, and writes approval
markers when responses are complete.

Exports:
    HITL_FORM_FILE — filename for the machine-readable questionnaire.
    HITL_RESPONSES_FILE — filename for operator answers.
    PRE0_APPROVED_MARKER — Pre-0 clearance marker filename.
    REVIEW_GATE_PENDING_MARKER — review-gate pause marker filename.
    REVIEW_GATE_APPROVED_MARKER — review-gate clearance marker filename.
    GateKind — ``pre0`` or ``review_gate``.
    HitlOption — one multiple-choice answer.
    HitlQuestion — one gate question (multiple_choice or confirm).
    HitlForm — full questionnaire for one pause.
    HitlResponses — operator answers payload.
    load_run_hitl_context — resolve run dir, gates, plan decisions.
    build_form — build a :class:`HitlForm` from gates and plan context.
    write_form — persist ``hitl-form.json`` under the run directory.
    load_form — read ``hitl-form.json``.
    load_responses — read ``hitl-responses.json`` (or empty draft).
    save_responses — write ``hitl-responses.json``.
    validate_responses — return validation errors (empty when ok).
    responses_complete — True when all required answers are present.
    write_decisions_sheet — regenerate ``pre0-decisions.md`` from responses.
    detect_pending_gate — return pending gate kind and wave id, if any.
    approve_gate — write the correct approval marker after validating responses.
    is_gate_approved — True when no pending gate remains for the kind.
    gate_poll_ready — True when responses are complete (for ``--wait-for-hitl``).
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tripll.parse.markdown import find_table_rows, strip_md

if TYPE_CHECKING:
    from tripll.graph import RunGraph

HITL_FORM_FILE = "hitl-form.json"
HITL_RESPONSES_FILE = "hitl-responses.json"
PRE0_APPROVED_MARKER = "pre0-approved"
REVIEW_GATE_PENDING_MARKER = "review-gate-pending.md"
REVIEW_GATE_APPROVED_MARKER = "review-gate-approved"
HITL_FORM_VERSION = 1


class GateKind(StrEnum):
    """Kind of human gate pausing a run."""

    PRE0 = "pre0"
    REVIEW_GATE = "review_gate"


@dataclass(frozen=True)
class HitlOption:
    """One multiple-choice option."""

    id: str
    label: str
    value: str
    explanation: str = ""
    recommended: bool = False
    allow_free_text: bool = False


@dataclass
class HitlQuestion:
    """One HITL question."""

    id: str
    type: str  # multiple_choice | confirm
    prompt: str
    gate_text: str = ""
    options: list[HitlOption] = field(default_factory=list)
    checkbox_label: str = ""
    notes_optional: bool = True


@dataclass
class HitlForm:
    """Machine-readable questionnaire for one gate pause."""

    form_id: str
    gate_kind: str
    run_id: str
    wave_id: str | None = None
    gate_label: str | None = None
    version: int = HITL_FORM_VERSION
    questions: list[HitlQuestion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "version": self.version,
            "form_id": self.form_id,
            "gate_kind": self.gate_kind,
            "run_id": self.run_id,
            "wave_id": self.wave_id,
            "gate_label": self.gate_label,
            "questions": [
                {
                    "id": q.id,
                    "type": q.type,
                    "prompt": q.prompt,
                    "gate_text": q.gate_text,
                    "notes_optional": q.notes_optional,
                    **(
                        {
                            "options": [
                                {
                                    "id": o.id,
                                    "label": o.label,
                                    "value": o.value,
                                    "explanation": o.explanation,
                                    "recommended": o.recommended,
                                    "allow_free_text": o.allow_free_text,
                                }
                                for o in q.options
                            ]
                        }
                        if q.type == "multiple_choice"
                        else {"checkbox_label": q.checkbox_label}
                    ),
                }
                for q in self.questions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HitlForm:
        """Parse a form dict."""
        questions: list[HitlQuestion] = []
        for raw in data.get("questions") or []:
            if not isinstance(raw, dict):
                continue
            qtype = str(raw.get("type") or "multiple_choice")
            options: list[HitlOption] = []
            if qtype == "multiple_choice":
                for opt in raw.get("options") or []:
                    if not isinstance(opt, dict):
                        continue
                    options.append(
                        HitlOption(
                            id=str(opt.get("id") or ""),
                            label=str(opt.get("label") or ""),
                            value=str(opt.get("value") or ""),
                            explanation=str(opt.get("explanation") or ""),
                            recommended=bool(opt.get("recommended")),
                            allow_free_text=bool(opt.get("allow_free_text")),
                        )
                    )
            questions.append(
                HitlQuestion(
                    id=str(raw.get("id") or ""),
                    type=qtype,
                    prompt=str(raw.get("prompt") or ""),
                    gate_text=str(raw.get("gate_text") or ""),
                    options=options,
                    checkbox_label=str(raw.get("checkbox_label") or ""),
                    notes_optional=bool(raw.get("notes_optional", True)),
                )
            )
        return cls(
            form_id=str(data.get("form_id") or "gate"),
            gate_kind=str(data.get("gate_kind") or GateKind.PRE0.value),
            run_id=str(data.get("run_id") or ""),
            wave_id=data.get("wave_id"),
            gate_label=data.get("gate_label"),
            version=int(data.get("version") or HITL_FORM_VERSION),
            questions=questions,
        )


@dataclass
class HitlAnswer:
    """One recorded answer."""

    question_id: str
    option_id: str | None = None
    checked: bool | None = None
    notes: str = ""


@dataclass
class HitlResponses:
    """Operator response payload."""

    run_id: str
    form_id: str
    gate_kind: str
    status: str = "draft"  # draft | submitted
    answers: list[HitlAnswer] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "run_id": self.run_id,
            "form_id": self.form_id,
            "gate_kind": self.gate_kind,
            "status": self.status,
            "answers": [asdict(a) for a in self.answers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HitlResponses:
        """Parse a responses dict."""
        answers: list[HitlAnswer] = []
        for raw in data.get("answers") or []:
            if not isinstance(raw, dict):
                continue
            answers.append(
                HitlAnswer(
                    question_id=str(raw.get("question_id") or ""),
                    option_id=raw.get("option_id"),
                    checked=raw.get("checked"),
                    notes=str(raw.get("notes") or ""),
                )
            )
        return cls(
            run_id=str(data.get("run_id") or ""),
            form_id=str(data.get("form_id") or ""),
            gate_kind=str(data.get("gate_kind") or GateKind.PRE0.value),
            status=str(data.get("status") or "draft"),
            answers=answers,
        )


@dataclass
class RunHitlContext:
    """Paths and metadata for HITL on a run."""

    run_id: str
    run_dir: Path
    gates: list[str]
    plan_path: Path | None = None
    decisions: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingGate:
    """A gate awaiting operator input."""

    kind: GateKind
    wave_id: str | None = None
    gate_label: str | None = None


def _runs_root_default() -> Path:
    import os

    raw = os.environ.get("TRIPLL_RUNS", "runs")
    return Path(raw).resolve()


def _display_gate(gate: str) -> str:
    text = gate.strip()
    return re.sub(r"^-\s*\[[ xX]\]\s*", "", text)


def _gates_from_decisions_md(text: str) -> list[str]:
    gates: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\d+\.\s+\[[ xX]\]\s+(.+)$", line.strip())
        if m:
            gates.append(m.group(1).strip())
    return gates


def parse_decisions_table(plan_path: Path) -> dict[str, tuple[str, str]]:
    """Return ``{D1: (topic, decision_text), ...}`` from the plan decisions table."""
    text = plan_path.read_text()
    rows: dict[str, tuple[str, str]] = {}
    for cells in find_table_rows(text, ["#", "Topic", "Decision"]):
        if len(cells) < 3:
            continue
        key = strip_md(cells[0])
        if not re.match(r"D\d+", key):
            continue
        rows[key] = (strip_md(cells[1]), strip_md(cells[2]))
    return rows


def _decision_refs(gate: str) -> list[str]:
    refs = re.findall(r"\bD(\d+)\b", gate)
    if "D1" in gate or "D1-D16" in gate or "D1\u2013D16" in gate:
        return sorted(set(refs), key=int) if refs else ["1"]
    return sorted(set(refs), key=int)


def _slug_option_id(label: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]
    return slug or f"opt-{index}"


def _append_other_option(options: list[HitlOption]) -> list[HitlOption]:
    return [
        *options,
        HitlOption(
            id="other",
            label="Other — describe your answer in the notes field",
            value="Custom answer — see operator notes.",
            allow_free_text=True,
        ),
    ]


def build_options_for_gate(gate: str, decisions: dict[str, tuple[str, str]]) -> list[HitlOption]:
    """Build multiple-choice options for one Pre-0 gate (legacy-compatible)."""
    gate_l = gate.lower()
    refs = _decision_refs(gate)

    if any(k in gate for k in ("D1-D16", "D1\u2013D16")) or (
        "d1" in gate_l and ("renderer" in gate_l or "design note" in gate_l)
    ):
        d1 = decisions.get("D1")
        if d1:
            _topic, decision = d1
            return _append_other_option(
                [
                    HitlOption(
                        id="confirm-d1-d16",
                        label="Confirm D1-D16 as written - structured InputRichMessage tree "
                        "+ Rich Markdown fast path",
                        value=decision,
                        explanation=decision[:240],
                        recommended=True,
                    ),
                    HitlOption(
                        id="override-d1",
                        label="Override D1 - Rich Markdown strings only; re-scope R2-R4 (D1 prime)",
                        value="Override D1: Rich Markdown strings only; re-scope R2-R4 per plan footnote.",
                        explanation="Reject structured tree; re-scope rich waves before R2.",
                    ),
                    HitlOption(
                        id="partial-override",
                        label="Override specific decisions — describe in notes",
                        value="Partial override — see operator notes.",
                        explanation="Keep most decisions; document exceptions in notes.",
                    ),
                    HitlOption(
                        id="defer",
                        label="Defer — need more research before W0 sign-off",
                        value="Deferred — do not proceed to R1 until operator re-approves.",
                        explanation="Pause until operator re-approves after more research.",
                    ),
                ]
            )

    if "D1" in decisions and ("d1" in gate_l or "renderer" in gate_l or "1" in refs):
        _topic, decision = decisions["D1"]
        return _append_other_option(
            [
                HitlOption(
                    id="confirm-d1",
                    label="Structured InputRichMessage tree + Markdown fast path (D1)",
                    value=decision,
                    explanation=decision[:240],
                    recommended=True,
                ),
                HitlOption(
                    id="override-d1-markdown",
                    label="Rich Markdown strings only (reject structured tree - D1 prime)",
                    value="Override D1: Rich Markdown strings only.",
                    explanation="Use Rich Markdown strings only; re-scope R2-R4.",
                ),
                HitlOption(
                    id="defer",
                    label="Defer decision",
                    value="Deferred.",
                    explanation="Revisit before implementation waves.",
                ),
            ]
        )

    if refs:
        primary = f"D{refs[0]}"
        if primary in decisions:
            topic, decision = decisions[primary]
            short = topic if len(topic) <= 72 else topic[:69] + "…"
            return _append_other_option(
                [
                    HitlOption(
                        id=f"confirm-{primary.lower()}",
                        label=f"Confirm {primary} - {short}",
                        value=decision,
                        explanation=decision[:240],
                        recommended=True,
                    ),
                    HitlOption(
                        id=f"override-{primary.lower()}",
                        label=f"Override {primary} — describe alternative in notes",
                        value=f"Override {primary} — see operator notes.",
                        explanation="Document the alternative in notes.",
                    ),
                    HitlOption(
                        id="defer",
                        label="Defer this gate",
                        value="Deferred.",
                        explanation="Do not proceed until re-approved.",
                    ),
                ]
            )

    return _append_other_option(
        [
            HitlOption(
                id="approve",
                label="Approve - proceed as documented",
                value="Approved as documented.",
                explanation="Proceed with the plan as written.",
                recommended=True,
            ),
            HitlOption(
                id="approve-caveats",
                label="Approve with caveats — describe in notes",
                value="Approved with caveats — see operator notes.",
                explanation="Proceed but document caveats in notes.",
            ),
            HitlOption(
                id="defer",
                label="Defer — revisit before next wave",
                value="Deferred.",
                explanation="Pause until operator re-approves.",
            ),
            HitlOption(
                id="block",
                label="Block — do not proceed until resolved",
                value="Blocked.",
                explanation="Stop the run until the blocker is resolved.",
            ),
        ]
    )


def _question_from_gate(
    gate: str,
    *,
    index: int,
    decisions: dict[str, tuple[str, str]],
) -> HitlQuestion:
    prompt = _display_gate(gate)
    options = build_options_for_gate(gate, decisions)
    return HitlQuestion(
        id=f"gate-{index}",
        type="multiple_choice",
        prompt=prompt,
        gate_text=gate,
        options=options,
        notes_optional=True,
    )


def _parse_plan_hitl_overrides(plan_path: Path | None) -> dict[str, dict[str, Any]]:
    """Parse optional ``## tripll hitl`` JSON block from a wave plan."""
    if plan_path is None or not plan_path.is_file():
        return {}
    text = plan_path.read_text()
    match = re.search(
        r"^##\s+tripll hitl\s*$(.*?)(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        return {}
    block = match.group(1).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", block, re.DOTALL)
    payload = fence.group(1).strip() if fence else block
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    overrides: dict[str, dict[str, Any]] = {}
    for item in data.get("questions") or []:
        if isinstance(item, dict) and item.get("id"):
            overrides[str(item["id"])] = item
    return overrides


def _apply_override(question: HitlQuestion, override: dict[str, Any]) -> HitlQuestion:
    qtype = str(override.get("type") or question.type)
    options = question.options
    if qtype == "multiple_choice" and override.get("options"):
        options = []
        for i, opt in enumerate(override["options"], 1):
            if not isinstance(opt, dict):
                continue
            options.append(
                HitlOption(
                    id=str(opt.get("id") or _slug_option_id(str(opt.get("label")), i)),
                    label=str(opt.get("label") or ""),
                    value=str(opt.get("value") or opt.get("label") or ""),
                    explanation=str(opt.get("explanation") or ""),
                    recommended=bool(opt.get("recommended")),
                    allow_free_text=bool(opt.get("allow_free_text")),
                )
            )
    return HitlQuestion(
        id=str(override.get("id") or question.id),
        type=qtype,
        prompt=str(override.get("prompt") or question.prompt),
        gate_text=question.gate_text,
        options=options if qtype == "multiple_choice" else [],
        checkbox_label=str(override.get("checkbox_label") or question.checkbox_label),
        notes_optional=bool(override.get("notes_optional", question.notes_optional)),
    )


def build_form(
    ctx: RunHitlContext,
    *,
    gate_kind: GateKind = GateKind.PRE0,
    wave_id: str | None = None,
    gate_label: str | None = None,
    gates: list[str] | None = None,
) -> HitlForm:
    """Build a HITL form from run context and gate metadata."""
    gate_list = gates if gates is not None else ctx.gates
    overrides = _parse_plan_hitl_overrides(ctx.plan_path)
    questions: list[HitlQuestion] = []
    for i, gate in enumerate(gate_list, 1):
        q = _question_from_gate(gate, index=i, decisions=ctx.decisions)
        oid = f"gate-{i}"
        if oid in overrides:
            q = _apply_override(q, overrides[oid])
        questions.append(q)

    if gate_kind == GateKind.REVIEW_GATE and wave_id:
        label = gate_label or f"{wave_id} review gate"
        mc = _question_from_gate(
            f"{wave_id}: {label} — confirm plan decisions",
            index=2,
            decisions=ctx.decisions,
        )
        mc.id = f"review-mc-{wave_id.lower()}"
        questions = [
            HitlQuestion(
                id=f"review-{wave_id.lower()}",
                type="confirm",
                prompt=f"Review gate: {label}",
                gate_text=label,
                checkbox_label=f"I approve continuing past {wave_id}",
                notes_optional=True,
            ),
            mc,
        ]

    form_id = "pre0" if gate_kind == GateKind.PRE0 else f"review-{wave_id or 'gate'}"
    return HitlForm(
        form_id=form_id,
        gate_kind=gate_kind.value,
        run_id=ctx.run_id,
        wave_id=wave_id,
        gate_label=gate_label,
        questions=questions,
    )


def load_run_hitl_context(
    run_id: str,
    *,
    runs_root: Path | None = None,
    run_dir: Path | None = None,
) -> RunHitlContext:
    """Load gates and plan decisions from a run directory."""
    if run_dir is None:
        root = (runs_root or _runs_root_default()).resolve()
        for folder in ("processing", "processed", "failed"):
            candidate = root / folder / run_id
            if candidate.is_dir():
                run_dir = candidate
                break
        if run_dir is None:
            msg = f"Run not found: {run_id}"
            raise FileNotFoundError(msg)

    graph_path = run_dir / "graph.json"
    gates: list[str] = []
    if graph_path.is_file():
        data = json.loads(graph_path.read_text())
        gates = list(data.get("pre0_gates") or [])

    if not gates and (run_dir / "pre0-decisions.md").is_file():
        gates = _gates_from_decisions_md((run_dir / "pre0-decisions.md").read_text())

    plan_files = sorted(run_dir.glob("*-wave-plan.md"))
    plan_path = plan_files[0] if plan_files else None
    decisions = parse_decisions_table(plan_path) if plan_path else {}

    return RunHitlContext(
        run_id=run_id,
        run_dir=run_dir,
        gates=gates,
        plan_path=plan_path,
        decisions=decisions,
    )


def write_form(run_dir: Path, form: HitlForm) -> Path:
    """Write ``hitl-form.json`` under *run_dir*."""
    path = run_dir / HITL_FORM_FILE
    path.write_text(json.dumps(form.to_dict(), indent=2) + "\n")
    return path


def load_form(run_dir: Path) -> HitlForm | None:
    """Read ``hitl-form.json`` when present."""
    path = run_dir / HITL_FORM_FILE
    if not path.is_file():
        return None
    return HitlForm.from_dict(json.loads(path.read_text()))


def load_responses(run_dir: Path) -> HitlResponses | None:
    """Read ``hitl-responses.json`` when present."""
    path = run_dir / HITL_RESPONSES_FILE
    if not path.is_file():
        return None
    return HitlResponses.from_dict(json.loads(path.read_text()))


def save_responses(run_dir: Path, responses: HitlResponses) -> Path:
    """Write ``hitl-responses.json``."""
    path = run_dir / HITL_RESPONSES_FILE
    path.write_text(json.dumps(responses.to_dict(), indent=2) + "\n")
    return path


def _answer_for_question(form: HitlForm, responses: HitlResponses, qid: str) -> HitlAnswer | None:
    for ans in responses.answers:
        if ans.question_id == qid:
            return ans
    return None


def validate_responses(form: HitlForm, responses: HitlResponses) -> list[str]:
    """Return validation errors; empty list means responses are complete."""
    errors: list[str] = []
    if responses.form_id and responses.form_id != form.form_id:
        errors.append(f"form_id mismatch: expected {form.form_id}, got {responses.form_id}")
    for q in form.questions:
        ans = _answer_for_question(form, responses, q.id)
        if ans is None:
            errors.append(f"Missing answer for question {q.id}")
            continue
        if q.type == "confirm":
            if not ans.checked:
                errors.append(f"Question {q.id} requires confirmation")
        elif q.type == "multiple_choice":
            if not ans.option_id:
                errors.append(f"Question {q.id} requires a selected option")
                continue
            opt = next((o for o in q.options if o.id == ans.option_id), None)
            if opt is None:
                errors.append(f"Question {q.id} has unknown option {ans.option_id}")
                continue
            if opt.allow_free_text and not ans.notes.strip():
                errors.append(f"Question {q.id} requires notes for free-text option")
    return errors


def responses_complete(run_dir: Path) -> bool:
    """True when ``hitl-form.json`` exists and responses validate."""
    form = load_form(run_dir)
    if form is None:
        return False
    responses = load_responses(run_dir)
    if responses is None:
        return False
    return not validate_responses(form, responses)


def _choice_label(form: HitlForm, q: HitlQuestion, ans: HitlAnswer) -> tuple[str, str]:
    if q.type == "confirm":
        label = q.checkbox_label or "Confirmed"
        value = "Confirmed." if ans.checked else "Not confirmed"
        return label, value
    opt = next((o for o in q.options if o.id == ans.option_id), None)
    if opt is None:
        return ans.option_id or "", ans.notes or ""
    return opt.label, opt.value


def write_decisions_sheet(run_dir: Path, form: HitlForm, responses: HitlResponses) -> Path:
    """Regenerate ``pre0-decisions.md`` from validated responses."""
    errors = validate_responses(form, responses)
    if errors:
        msg = "; ".join(errors)
        raise ValueError(msg)

    path = run_dir / "pre0-decisions.md"
    lines = [
        f"# Pre-0 decisions — {form.run_id}\n",
        "\n",
        f"Recorded via HITL form `{form.form_id}`.\n",
        "\n",
    ]
    for i, q in enumerate(form.questions, 1):
        ans = _answer_for_question(form, responses, q.id)
        if ans is None:
            continue
        gate_text = q.gate_text or q.prompt
        lines.append(f"{i}. [x] {gate_text}\n")
        if q.type == "confirm":
            lines.append(f"   - **Choice:** {q.checkbox_label}\n")
            lines.append("   - **Recorded:** Confirmed.\n")
        else:
            choice_label, choice_value = _choice_label(form, q, ans)
            lines.append(f"   - **Choice:** {choice_label}\n")
            if ans.notes:
                lines.append(f"   - **Notes:** {ans.notes}\n")
            elif "Custom answer" in choice_value:
                lines.append("   - **Notes:** _(none — add notes if using Other)_\n")
            else:
                lines.append(f"   - **Recorded:** {choice_value}\n")
        lines.append("\n")
    path.write_text("".join(lines))
    return path


def detect_pending_gate(run_dir: Path) -> PendingGate | None:
    """Return the pending gate kind, if any."""
    if (run_dir / REVIEW_GATE_PENDING_MARKER).is_file():
        wave_id: str | None = None
        gate_label: str | None = None
        text = (run_dir / REVIEW_GATE_PENDING_MARKER).read_text()
        wm = re.search(r"Wave \*\*(\w+)\*\*", text)
        if wm:
            wave_id = wm.group(1)
        lm = re.search(r"AWAITING REVIEW\*\* \(([^)]+)\)", text)
        if lm:
            gate_label = lm.group(1)
        if not (run_dir / REVIEW_GATE_APPROVED_MARKER).is_file():
            return PendingGate(
                kind=GateKind.REVIEW_GATE,
                wave_id=wave_id,
                gate_label=gate_label,
            )
    if (run_dir / PRE0_APPROVED_MARKER).is_file():
        return None
    ctx = None
    with contextlib.suppress(FileNotFoundError):
        ctx = load_run_hitl_context("", run_dir=run_dir)
    if ctx and ctx.gates:
        return PendingGate(kind=GateKind.PRE0)
    if (run_dir / "pre0-decisions.md").is_file():
        unchecked = "[ ]" in (run_dir / "pre0-decisions.md").read_text()
        if unchecked or not (run_dir / PRE0_APPROVED_MARKER).is_file():
            return PendingGate(kind=GateKind.PRE0)
    return None


def approve_gate(run_dir: Path, *, run_id: str | None = None) -> GateKind:
    """Validate responses and write the appropriate approval marker.

    Raises:
        ValueError: When no pending gate or responses incomplete.

    Returns:
        GateKind: The gate kind that was approved.
    """
    pending = detect_pending_gate(run_dir)
    if pending is None:
        msg = "No pending gate to approve"
        raise ValueError(msg)

    form = load_form(run_dir)
    responses = load_responses(run_dir)
    if form is None or responses is None:
        msg = "HITL form and responses required before approve"
        raise ValueError(msg)

    errors = validate_responses(form, responses)
    if errors:
        raise ValueError("; ".join(errors))

    if pending.kind == GateKind.PRE0:
        write_decisions_sheet(run_dir, form, responses)
        (run_dir / PRE0_APPROVED_MARKER).write_text("approved\n")
    else:
        (run_dir / REVIEW_GATE_APPROVED_MARKER).write_text(f"{pending.wave_id or 'gate'}\n")
        (run_dir / REVIEW_GATE_PENDING_MARKER).unlink(missing_ok=True)

    responses.status = "submitted"
    save_responses(run_dir, responses)
    return pending.kind


def write_form_for_run(
    run_dir: Path,
    graph: RunGraph,
    *,
    gate_kind: GateKind = GateKind.PRE0,
    wave_id: str | None = None,
    gate_label: str | None = None,
) -> Path:
    """Build and write HITL form for a paused run."""
    ctx = load_run_hitl_context(graph.run_id, run_dir=run_dir)
    if gate_kind == GateKind.PRE0:
        gates = list(graph.pre0_gates) or ctx.gates
    else:
        gates = ctx.gates[:1] if ctx.gates else [gate_label or f"{wave_id} review gate"]
    form = build_form(
        ctx,
        gate_kind=gate_kind,
        wave_id=wave_id,
        gate_label=gate_label,
        gates=gates,
    )
    return write_form(run_dir, form)


def gate_poll_ready(run_dir: Path) -> bool:
    """True when responses are complete and gate can be auto-approved."""
    pending = detect_pending_gate(run_dir)
    if pending is None:
        return True
    return responses_complete(run_dir)


def hitl_status(run_dir: Path) -> dict[str, Any]:
    """Summary for API/dashboard."""
    form = load_form(run_dir)
    responses = load_responses(run_dir)
    pending = detect_pending_gate(run_dir)
    complete = bool(form and responses and not validate_responses(form, responses))
    return {
        "pending": pending is not None,
        "gate_kind": pending.kind.value if pending else None,
        "wave_id": pending.wave_id if pending else None,
        "form": form.to_dict() if form else None,
        "responses": responses.to_dict() if responses else None,
        "complete": complete,
        "approved_pre0": (run_dir / PRE0_APPROVED_MARKER).is_file(),
    }
