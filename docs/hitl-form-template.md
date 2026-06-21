# HITL form template (tripll)

When a run pauses at **Pre-0** or a **review gate**, tripll writes
`hitl-form.json` under `runs/processing/<run-id>/`. Operators complete the
questionnaire via the dashboard modal, the control-plane API, or
`make pre0-interview`. Answers are stored in `hitl-responses.json`; on submit
tripll regenerates `pre0-decisions.md` (Pre-0) and writes the gate marker
(`pre0-approved` or `review-gate-approved`).

## Artefacts

| File | Purpose |
|------|---------|
| `hitl-form.json` | Machine-readable questionnaire (generated on pause) |
| `hitl-responses.json` | Operator answers (draft or submitted) |
| `pre0-decisions.md` | Human-readable audit trail (regenerated on submit for Pre-0) |
| `pre0-approved` / `review-gate-approved` | Gate clearance markers |

## Form schema (v1)

```json
{
  "form_version": 1,
  "form_id": "pre0",
  "gate_kind": "pre0",
  "run_id": "my-set-20260618-120000",
  "questions": [
    {
      "id": "gate-1",
      "type": "multiple_choice",
      "prompt": "W0.7 Review gate: confirm renderer model…",
      "gate_text": "Original gate line from the plan",
      "options": [
        {
          "id": "confirm-d1",
          "label": "Confirm D1–D16 as written…",
          "explanation": "Structured InputRichMessage tree + Markdown fast path.",
          "recommended": true,
          "value": "…"
        },
        {
          "id": "other",
          "label": "Other",
          "allow_free_text": true
        }
      ],
      "notes_optional": true
    },
    {
      "id": "gate-2",
      "type": "confirm",
      "prompt": "Acknowledge scope / branch / base constraints",
      "checkbox_label": "I confirm the run may proceed under these constraints",
      "notes_optional": true
    }
  ]
}
```

### Question types

| `type` | UI | Validation |
|--------|-----|------------|
| `multiple_choice` | Radio list with optional explanation and **Recommended** badge; one option may set `allow_free_text: true` (notes required when selected) | Requires `option_id` |
| `confirm` | Checkbox + optional notes | Requires `checked: true` |

## Form generation (priority)

1. Optional **`## tripll hitl`** JSON block in a `*-wave-plan.md` (per-question overrides).
2. Auto-generation from Pre-0 gate text + the plan **Decisions** table (`build_options_for_gate`).
3. Review-gate forms from `review-gate-pending.md` when orchestrator mode is enabled.

## Responses payload

```json
{
  "run_id": "my-set-20260618-120000",
  "form_id": "pre0",
  "gate_kind": "pre0",
  "status": "draft",
  "answers": [
    {
      "question_id": "gate-1",
      "option_id": "confirm-d1",
      "notes": ""
    },
    {
      "question_id": "gate-2",
      "checked": true,
      "notes": "Proceed on feature branch"
    }
  ]
}
```

Set `status` to `submitted` before approve. Incomplete responses block
`POST /api/runs/{id}/approve` and `tripll approve`.

## CLI wait mode

Block the terminal until HITL is complete (auto-approve + resume):

```bash
tripll run runs/input/my-set --wait-for-hitl
# or
WAIT_FOR_HITL=1 make run-set SET=my-set
```

Poll interval: `TRIPLL_HITL_POLL_S` (default `2`).

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/runs/{id}/hitl` | Form + responses + completion status |
| `PUT` | `/api/runs/{id}/hitl/responses` | Save draft or final responses |
| `POST` | `/api/runs/{id}/hitl/submit` | Validate all answers; rewrite `pre0-decisions.md` |
| `POST` | `/api/runs/{id}/hitl/approve` | Submit (optional body) + write gate marker |

`POST /api/runs/{id}/approve` remains an alias when no HITL form exists; when
`hitl-form.json` is present it returns **409** until responses are complete.

## Plan overrides (`## tripll hitl`)

See [`wave-plan-template.md`](wave-plan-template.md) for an optional JSON block
that replaces auto-generated questions for matching gate ids.
