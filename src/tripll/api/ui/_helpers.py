"""tripll.api.ui._helpers — shared dashboard template and context helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import Request  # noqa: TC002

from tripll.api._artefacts import (
    TIMELINE_EVENT_LIMIT,
    build_batch_timeline,
    parse_escalation_reasons,
    read_pause_banners,
)
from tripll.api._csrf import ensure_csrf_token
from tripll.api._inject import list_run_injects
from tripll.api._l1_panels import build_l1_panels
from tripll.api._orchestrator_ui import build_orchestrator_view
from tripll.api._pr_panel import build_pr_panel
from tripll.api._runs import _find_ledger, _is_run_live
from tripll.api._worktree_status import (
    WORKTREE_POLL_INTERVAL_S,
    WorktreeStatusError,
    load_wave_plan_text_for_node,
    should_poll_worktree,
)
from tripll.ledger import (
    EventRow,
    WaveRow,
    get_run,
    get_run_cost,
    get_run_cost_by_provider,
    latest_events_by_node,
    list_attempts,
    list_events,
    list_fired_exit_ids,
    list_waves,
    open_ledger,
)
from tripll.profiles import ProfileRow  # noqa: TC001
from tripll.wave_task import WaveTaskResult, infer_active_task

if TYPE_CHECKING:
    from tripll.ledger import LedgerConnection
    from tripll.pipeline import RunsRoot


def fragment_url(run_id: str, node_id: str, suffix: str, *, api_token: str = "") -> str:
    """Build an htmx-safe fragment URL for *node_id* (auth via ``hx-headers``)."""
    _ = api_token  # callers pass token for template symmetry; auth is header-based (R6)
    return f"/runs/{run_id}/waves/{quote(node_id, safe='')}/{suffix}"


def log_full_page_url(
    run_id: str,
    node_id: str,
    attempt_n: int,
    *,
    api_token: str = "",
) -> str:
    """Build URL for the full-page attempt log viewer."""
    _ = api_token
    return f"/runs/{run_id}/waves/{quote(node_id, safe='')}/log/full?attempt={attempt_n}"


def log_append_url(run_id: str, node_id: str, *, api_token: str = "") -> str:
    """Build append-only log poll URL for *node_id*."""
    return fragment_url(run_id, node_id, "log/append", api_token=api_token)


def log_fragment_url(run_id: str, node_id: str, *, api_token: str = "") -> str:
    """Build an htmx-safe log fragment URL for *node_id*."""
    return fragment_url(run_id, node_id, "log", api_token=api_token)


def _get_token() -> str:
    """Return the configured API token, or empty string in dev mode.

    Returns:
        str: The ``TRIPLL_API_TOKEN`` value, or ``""`` when unset.
    """
    return os.environ.get("TRIPLL_API_TOKEN", "").strip()


def _ui_context(request: Request, *, nav_section: str, **extra: Any) -> dict[str, Any]:
    """Build common template context with nav chrome (W2.1 + W3 CSRF).

    Args:
        request (Request): Active request (CSRF token + cookie pairing).
        nav_section (str): Active nav item (``runs``, ``agents``, ``settings``).
        **extra: Additional template variables.

    Returns:
        dict[str, Any]: Context dict including ``api_token``, ``csrf_token``, and
        ``nav_section``.
    """
    ctx: dict[str, Any] = {"api_token": _get_token(), "nav_section": nav_section}
    if _get_token():
        ctx["csrf_token"] = ensure_csrf_token(request)
    ctx.update(extra)
    return ctx


def _backend_names() -> list[str]:
    """Return sorted registered backend names for form selects.

    Returns:
        list[str]: Backend identifiers.
    """
    from tripll.adapters import BACKENDS

    return sorted(BACKENDS)


def _empty_profile_form() -> dict[str, str]:
    """Default field values for a new agent profile form.

    Returns:
        dict[str, str]: Template-ready profile dict.
    """
    return {
        "profile_id": "",
        "name": "",
        "backend": "claude_code",
        "model": "claude-sonnet-5",
        "agent": "wave-plan-executor",
        "skills_text": "[]",
    }


def _profile_form_from_row(row: ProfileRow) -> dict[str, str]:
    """Convert a profile row to agent form field dict.

    Args:
        row (ProfileRow): Stored profile.

    Returns:
        dict[str, str]: Template-ready profile dict.
    """
    return {
        "profile_id": row.profile_id,
        "name": row.name,
        "backend": row.backend,
        "model": row.model,
        "agent": row.agent,
        "skills_text": json.dumps(row.skills),
    }


def _parse_skills(raw: str) -> list[str]:
    """Parse skills from JSON array or comma-separated text.

    Args:
        raw (str): Raw form field value.

    Returns:
        list[str]: Parsed skill names.
    """
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _parse_agent_form(form: Any) -> dict[str, Any] | None:
    """Parse agent profile fields from a submitted form.

    Args:
        form: Starlette form data.

    Returns:
        dict[str, Any] | None: Fields for :func:`~tripll.profiles.upsert_profile`,
        or ``None`` when required fields are missing.
    """
    name = str(form.get("name", "")).strip()
    backend = str(form.get("backend", "")).strip()
    model = str(form.get("model", "")).strip()
    agent = str(form.get("agent", "")).strip()
    if not name or not backend or not model or not agent:
        return None
    return {
        "name": name,
        "backend": backend,
        "model": model,
        "agent": agent,
        "skills": _parse_skills(str(form.get("skills", ""))),
    }


def _timeline_events(lc: LedgerConnection, run_id: str) -> list[EventRow]:
    """Return the last :data:`TIMELINE_EVENT_LIMIT` events for *run_id*.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        list[EventRow]: Events ordered by ``event_id`` ascending.
    """
    events = list_events(lc, run_id)
    if len(events) > TIMELINE_EVENT_LIMIT:
        return events[-TIMELINE_EVENT_LIMIT:]
    return events


def _brief_field_from_path(brief_path: str | None, field: str) -> str | None:
    """Read one string field from a dispatch brief JSON file when present."""
    if not brief_path:
        return None
    try:
        data = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    value = str(data.get(field) or "").strip()
    return value or None


def _model_from_brief_path(brief_path: str | None) -> str | None:
    """Read ``model`` from a dispatch brief JSON file when present."""
    return _brief_field_from_path(brief_path, "model")


def _format_attempt_started(started_at: str | None) -> str:
    if not started_at:
        return "—"
    text = started_at.replace("T", " ").replace("Z", "")
    return text[:19] if len(text) >= 19 else text


def _attempt_display_rows(attempts: list[Any]) -> list[dict[str, Any]]:
    """Template-ready attempt rows with model, tokens, and timestamps."""
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        model = _model_from_brief_path(getattr(attempt, "brief_path", None)) or "—"
        inp = getattr(attempt, "input_tokens", None)
        out = getattr(attempt, "output_tokens", None)
        if inp is not None and out is not None:
            tokens = f"{inp}→{out}"
        elif inp is not None or out is not None:
            tokens = f"{inp or 0}→{out or 0}"
        else:
            tokens = "—"
        rows.append(
            {
                "attempt_n": attempt.attempt_n,
                "attempt_id": attempt.attempt_id,
                "started_at": _format_attempt_started(getattr(attempt, "started_at", None)),
                "outcome": attempt.outcome or "—",
                "evidence": attempt.evidence or "—",
                "cost_usd": attempt.cost_usd,
                "model": model,
                "backend": getattr(attempt, "backend", "") or "—",
                "tokens": tokens,
            }
        )
    return rows


def _wave_model_label(attempts: list[Any]) -> str:
    for attempt in reversed(attempts):
        model = _model_from_brief_path(getattr(attempt, "brief_path", None))
        if model:
            return model
    return "—"


def _wave_backend_label(attempts: list[Any]) -> str:
    for attempt in reversed(attempts):
        backend = str(getattr(attempt, "backend", "") or "").strip()
        if backend:
            return backend
    return "—"


def _wave_effort_label(attempts: list[Any]) -> str:
    for attempt in reversed(attempts):
        effort = _brief_field_from_path(getattr(attempt, "brief_path", None), "reasoning_effort")
        if effort:
            return effort
    return "—"


def _is_human_gate_done(*, wave_id: str, phase: str, has_attempts: bool) -> bool:
    """True when a human-gate wave finished without agent dispatch."""
    return phase == "done" and not has_attempts and wave_id in ("W0", "Pre-0")


def _wave_status_detail(
    *,
    node_id: str,
    wave_id: str,
    phase: str,
    last_action: str,
    attempts: list[Any],
    escalation_reasons: dict[str, str],
) -> str | None:
    """Return a human-readable status or failure reason for dashboard panels."""
    if _is_human_gate_done(wave_id=wave_id, phase=phase, has_attempts=bool(attempts)):
        return "Human gate completed — no agent dispatch required."

    if phase == "gate_pending":
        return "Awaiting human gate approval before dispatch."

    for attempt in reversed(attempts):
        evidence = getattr(attempt, "evidence", None)
        if evidence:
            return str(evidence)

    if last_action:
        return last_action

    reason = escalation_reasons.get(node_id)
    if reason:
        return reason

    if phase == "blocked":
        return "Wave blocked — see escalation.md for details."
    if phase == "failed":
        return "Wave failed — see escalation.md for details."

    return None


def _build_wave_rows(
    waves: list[WaveRow],
    latest: dict[str, EventRow],
    *,
    rr: RunsRoot,
    run_id: str,
    lc: LedgerConnection,
) -> list[dict[str, Any]]:
    """Merge wave ledger rows with collapsed event state (D2) and W3 panels.

    Args:
        waves (list[WaveRow]): Wave rows from the ledger.
        latest (dict[str, EventRow]): Collapsed events per node.
        rr (RunsRoot): Configured runs root.
        run_id (str): Parent run identifier.
        lc (LedgerConnection): Open ledger connection.

    Returns:
        list[dict[str, Any]]: Template-ready wave row dicts.
    """
    run_dir = rr.find_run_dir(run_id)
    escalation_reasons = parse_escalation_reasons(run_dir)
    rows: list[dict[str, Any]] = []
    for w in waves:
        ev = latest.get(w.node_id)
        phase = ev.phase if ev is not None else w.state
        last_action = ev.last_action if ev and ev.last_action else ""
        attempt_ctx = _attempt_panel_context(lc, run_id, w.node_id, phase, w.attempt_count)
        task_result = _infer_wave_tasks(rr, run_id, w, last_action, phase)
        poll_worktree = should_poll_worktree(phase)
        has_attempts = len(attempt_ctx["attempts"]) > 0
        is_human_gate_done = _is_human_gate_done(
            wave_id=w.wave_id,
            phase=phase,
            has_attempts=has_attempts,
        )
        is_gate_only = (
            not has_attempts and phase in ("queued", "gate_pending") and not is_human_gate_done
        )
        status_detail = _wave_status_detail(
            node_id=w.node_id,
            wave_id=w.wave_id,
            phase=phase,
            last_action=last_action,
            attempts=attempt_ctx["attempts"],
            escalation_reasons=escalation_reasons,
        )
        show_log_panel = has_attempts or phase in (
            "running",
            "verifying",
            "done",
            "failed",
            "blocked",
            "dispatched",
        )
        rows.append(
            {
                "node_id": w.node_id,
                "plan_id": w.plan_id,
                "is_hotfix": w.plan_id == "hotfix",
                "lane": w.lane,
                "wave_id": w.wave_id,
                "phase": phase,
                "last_action": last_action,
                "display_action": last_action or status_detail or "—",
                "status_detail": status_detail,
                "model": _wave_model_label(attempt_ctx["attempts"]),
                "backend": _wave_backend_label(attempt_ctx["attempts"]),
                "provider": _wave_backend_label(attempt_ctx["attempts"]),
                "reasoning_effort": _wave_effort_label(attempt_ctx["attempts"]),
                "input_tokens": ev.input_tokens if ev else None,
                "output_tokens": ev.output_tokens if ev else None,
                "cost_usd": ev.cost_usd if ev else None,
                "poll_worktree": poll_worktree,
                "poll_log": phase in ("running", "verifying", "dispatched"),
                "log_poll_s": 3,
                "worktree_poll_s": WORKTREE_POLL_INTERVAL_S,
                "has_attempts": has_attempts,
                "is_gate_only": is_gate_only,
                "is_human_gate_done": is_human_gate_done,
                "show_log_panel": show_log_panel,
                **attempt_ctx,
                "task_result": task_result,
            }
        )
    return rows


def _build_run_detail_context(rr: RunsRoot, run_id: str) -> dict[str, Any] | None:
    """Build template context for ``run_detail.html``.

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier.

    Returns:
        dict[str, Any] | None: Context dict, or ``None`` when the run is missing.
    """
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None

    run_dir = rr.find_run_dir(run_id)
    is_live = _is_run_live(run_dir)
    logs_dir = run_dir / "logs" if run_dir is not None else None
    log_file_count = 0
    if logs_dir is not None and logs_dir.is_dir():
        log_file_count = sum(1 for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".log")
    report_exists = run_dir is not None and (run_dir / "report.md").is_file()
    pause_banners = read_pause_banners(run_dir)

    with open_ledger(ledger_path) as lc:
        run_row = get_run(lc, run_id)
        waves = list_waves(lc, run_id)
        latest = latest_events_by_node(lc, run_id)
        timeline_events = _timeline_events(lc, run_id)
        run_cost = get_run_cost(lc, run_id)
        cost_by_provider = get_run_cost_by_provider(lc, run_id)
        fired_exit_ids = list_fired_exit_ids(lc, run_id)
        wave_rows = _build_wave_rows(waves, latest, rr=rr, run_id=run_id, lc=lc)
        ledger_node_ids = [w.node_id for w in waves]
        batch_timeline = build_batch_timeline(
            run_dir,
            latest=latest,
            ledger_node_ids=ledger_node_ids,
        )
        wave_to_node = {w.wave_id: w.node_id for w in waves}
        orch = build_orchestrator_view(
            run_dir,
            run_id=run_id,
            wave_to_node=wave_to_node,
            is_live=is_live,
            api_token=_get_token(),
        )

    from tripll import hitl
    from tripll.repo_root import resolve_repo_root

    hitl_info = hitl.hitl_status(run_dir) if run_dir is not None else {"pending": False}
    l1 = build_l1_panels(
        run_dir=run_dir,
        waves=waves,
        run_cost=run_cost,
        repo_root=resolve_repo_root(),
        fired_exit_ids=fired_exit_ids,
    )
    pr = build_pr_panel(run_dir=run_dir)

    inject_after_options = [
        {"node_id": w["node_id"], "phase": w["phase"]} for w in wave_rows if w["phase"] == "done"
    ]
    inject_data = list_run_injects(rr, run_id)

    return {
        "run_id": run_id,
        "run_state": run_row.state,
        "run_cost": run_cost,
        "cost_by_provider": cost_by_provider,
        "is_live": is_live,
        "log_file_count": log_file_count,
        "report_exists": report_exists,
        "pause_banners": pause_banners,
        "batch_timeline": batch_timeline,
        "waves": wave_rows,
        "timeline_events": timeline_events,
        "orch": orch,
        "wave_summary": orch.wave_summary,
        "hitl": hitl_info,
        "l1": l1,
        "pr": pr,
        "pr_flash": "",
        "pr_panel_open": False,
        "inject_after_options": inject_after_options,
        "inject_after_default": inject_after_options[-1]["node_id"] if inject_after_options else "",
        "inject_artefacts": inject_data["artefacts"],
        "inject_lock_held": inject_data["lock_held"],
        "inject_flash": "",
        "inject_panel_open": False,
    }


def _build_orchestrator_fragment_context(
    rr: RunsRoot,
    run_id: str,
) -> dict[str, Any] | None:
    """Build template context for ``_orchestrator.html`` (W5)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None
    run_dir = rr.find_run_dir(run_id)
    is_live = _is_run_live(run_dir)
    with open_ledger(ledger_path) as lc:
        waves = list_waves(lc, run_id)
        wave_to_node = {w.wave_id: w.node_id for w in waves}
    orch = build_orchestrator_view(
        run_dir,
        run_id=run_id,
        wave_to_node=wave_to_node,
        is_live=is_live,
        api_token=_get_token(),
    )
    return {"orch": orch, "run_id": run_id}


def _build_batch_timeline_context(rr: RunsRoot, run_id: str) -> dict[str, Any] | None:
    """Build template context for ``_batch_timeline.html`` (W4.1)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None
    run_dir = rr.find_run_dir(run_id)
    with open_ledger(ledger_path) as lc:
        waves = list_waves(lc, run_id)
        latest = latest_events_by_node(lc, run_id)
        batch_timeline = build_batch_timeline(
            run_dir,
            latest=latest,
            ledger_node_ids=[w.node_id for w in waves],
        )
    return {"batch_timeline": batch_timeline}


def _attempt_panel_context(
    lc: LedgerConnection,
    run_id: str,
    node_id: str,
    phase: str,
    attempt_count: int,
) -> dict[str, Any]:
    """Build attempt-history context for one wave row (W3.1)."""
    attempts = list_attempts(lc, run_id, node_id)
    attempt_rows = _attempt_display_rows(attempts)
    current_attempt_n = max((a.attempt_n for a in attempts), default=0) or max(attempt_count, 0)
    starting_new_attempt = (
        phase == "dispatched"
        and len(attempts) >= 2
        and attempts[-1].outcome is None
        and attempts[-2].outcome in ("failed", "timed_out", "scope_breach", "quota_exhausted")
    )
    return {
        "attempts": attempts,
        "attempt_rows": attempt_rows,
        "current_attempt_n": current_attempt_n,
        "starting_new_attempt": starting_new_attempt,
    }


def _infer_wave_tasks(
    rr: RunsRoot,
    run_id: str,
    wave: WaveRow,
    last_action: str,
    phase: str,
) -> WaveTaskResult | None:
    """Infer wave-task checklist for one wave when a staged plan slice exists (D6)."""
    plan_text = load_wave_plan_text_for_node(
        rr,
        run_id,
        wave_id=wave.wave_id,
        lane=wave.lane,
        plan_id=wave.plan_id,
    )
    if not plan_text:
        return None
    return infer_active_task(
        plan_text,
        last_action=last_action or None,
        phase=phase,
    )


def _get_wave_row(lc: LedgerConnection, run_id: str, node_id: str) -> WaveRow | None:
    """Return the ledger wave row for *node_id*, or ``None`` when missing."""
    for w in list_waves(lc, run_id):
        if w.node_id == node_id:
            return w
    return None


def _build_worktree_fragment_context(
    rr: RunsRoot,
    run_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Build template context for ``_worktree_panel.html`` (W3.4)."""
    from tripll.api._worktree_status import collect_worktree_status, resolve_wave_worktree_path

    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None

    run_dir = rr.find_run_dir(run_id)
    escalation_reasons = parse_escalation_reasons(run_dir)

    with open_ledger(ledger_path) as lc:
        wave = _get_wave_row(lc, run_id, node_id)
        if wave is None:
            return {
                "status": None,
                "worktree_error": f"Unknown wave node: {node_id}",
                "status_detail": None,
            }
        latest = latest_events_by_node(lc, run_id).get(node_id)
        phase = latest.phase if latest is not None else wave.state
        last_action = latest.last_action if latest and latest.last_action else ""
        attempts = list_attempts(lc, run_id, node_id)
        status_detail = _wave_status_detail(
            node_id=node_id,
            wave_id=wave.wave_id,
            phase=phase,
            last_action=last_action,
            attempts=attempts,
            escalation_reasons=escalation_reasons,
        )
        wt_path = resolve_wave_worktree_path(
            rr,
            run_id,
            lane=wave.lane,
            wave_id=wave.wave_id,
            plan_id=wave.plan_id,
        )

    if wt_path is None:
        return {"status": None, "worktree_error": None, "status_detail": status_detail}

    try:
        status = collect_worktree_status(wt_path)
    except WorktreeStatusError as exc:
        return {"status": None, "worktree_error": str(exc), "status_detail": status_detail}

    return {"status": status, "worktree_error": None, "status_detail": status_detail}


def _build_tasks_fragment_context(
    rr: RunsRoot,
    run_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Build template context for ``_wave_tasks.html`` (W3.3)."""
    ledger_path = _find_ledger(rr, run_id)
    if ledger_path is None:
        return None

    run_dir = rr.find_run_dir(run_id)
    escalation_reasons = parse_escalation_reasons(run_dir)

    with open_ledger(ledger_path) as lc:
        wave = _get_wave_row(lc, run_id, node_id)
        if wave is None:
            return {"task_result": None, "status_detail": None}
        latest = latest_events_by_node(lc, run_id).get(node_id)
        phase = latest.phase if latest is not None else wave.state
        last_action = latest.last_action if latest and latest.last_action else ""
        attempts = list_attempts(lc, run_id, node_id)
        status_detail = _wave_status_detail(
            node_id=node_id,
            wave_id=wave.wave_id,
            phase=phase,
            last_action=last_action,
            attempts=attempts,
            escalation_reasons=escalation_reasons,
        )
        task_result = _infer_wave_tasks(rr, run_id, wave, last_action, phase)

    return {"task_result": task_result, "status_detail": status_detail}
