"""tripll.api._orchestrator_ui — dashboard orchestrator panel context (W5).

Parses ``orchestrator-status.md`` and builds template-ready context for the
Multitask-style orchestrator panel and turn feed on run detail pages.

Exports:
    ORCHESTRATOR_POLL_INTERVAL_S — htmx poll interval while run is live.
    OrchestratorFeedEntry — one turn in the scrollable feed.
    OrchestratorPanelView — panel + feed snapshot for templates.
    build_orchestrator_view — build view from run dir and wave rows.
    parse_wave_node_from_turn — extract wave/node ids from turn text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import quote

from tripll.orchestrator_status import (
    OrchestratorSnapshot,
    OrchestratorTurn,
    StatusRow,
    read_latest,
)

if TYPE_CHECKING:
    from pathlib import Path

ORCHESTRATOR_POLL_INTERVAL_S = 2.0
_FEED_LIMIT = 20
_WAVE_ID_RE = re.compile(r"\*\*([^*]+)\*\*")
_NODE_ID_RE = re.compile(r"`([^`]+:[^`]+)`")
_GATE_TURN_TYPES = frozenset({"review_gate", "stop"})


@dataclass
class OrchestratorFeedEntry:
    """One turn row in the orchestrator feed partial."""

    turn_n: int | None
    turn_type: str
    timestamp: str
    summary: str
    node_id: str | None = None
    log_url: str | None = None


@dataclass
class OrchestratorPanelView:
    """Orchestrator panel + feed snapshot for dashboard templates."""

    enabled: bool = False
    rows: list[StatusRow] = field(default_factory=list)
    current_wave: str | None = None
    gate_notice: str | None = None
    gate_kind: str | None = None
    next_action: str | None = None
    wave_summary: str | None = None
    feed: list[OrchestratorFeedEntry] = field(default_factory=list)
    poll_orchestrator: bool = False
    orchestrator_poll_s: float = ORCHESTRATOR_POLL_INTERVAL_S


def parse_wave_node_from_turn(
    turn: OrchestratorTurn,
    wave_to_node: dict[str, str],
) -> tuple[str | None, str | None]:
    """Extract wave id and ledger node id from a turn summary/body.

    Args:
        turn (OrchestratorTurn): Parsed turn from ``orchestrator-status.md``.
        wave_to_node (dict[str, str]): Map ``wave_id`` → ``node_id``.

    Returns:
        tuple[str | None, str | None]: ``(wave_id, node_id)`` when resolved.

    Examples:
        >>> from tripll.orchestrator_status import OrchestratorTurn
        >>> t = OrchestratorTurn("wave_dispatched", "Dispatching **W1** (`p:W1`)")
        >>> parse_wave_node_from_turn(t, {"W1": "p:W1"})
        ('W1', 'p:W1')
    """
    text = f"{turn.summary}\n{turn.body}"
    node_id: str | None = None
    node_m = _NODE_ID_RE.search(text)
    if node_m:
        node_id = node_m.group(1)
    wave_id: str | None = None
    wave_m = _WAVE_ID_RE.search(turn.summary)
    if wave_m:
        wave_id = wave_m.group(1).strip()
    if node_id is None and wave_id and wave_id in wave_to_node:
        node_id = wave_to_node[wave_id]
    return wave_id, node_id


def _current_wave_from_rows(rows: list[StatusRow]) -> str | None:
    for row in rows:
        if "progress" in row.status.lower():
            return str(row.wave)
    for row in reversed(rows):
        if row.status.lower() in {"done", "complete", "completed"}:
            continue
        if row.status.lower() not in {"pending", "—", "-"}:
            return str(row.wave)
    return str(rows[0].wave) if rows else None


def _current_wave_from_turns(turns: list[OrchestratorTurn]) -> str | None:
    for turn in reversed(turns):
        if turn.turn_type == "wave_dispatched":
            wave_m = _WAVE_ID_RE.search(turn.summary)
            if wave_m:
                return wave_m.group(1).strip()
    return None


def _latest_gate(turns: list[OrchestratorTurn]) -> OrchestratorTurn | None:
    for turn in reversed(turns):
        if turn.turn_type in _GATE_TURN_TYPES:
            return turn
    return None


def _next_action(latest: OrchestratorTurn | None, gate: OrchestratorTurn | None) -> str | None:
    if gate is not None:
        return gate.summary.strip() or gate.turn_type.replace("_", " ").upper()
    if latest is None:
        return None
    if latest.turn_type == "wave_dispatched":
        return "Waiting for wave-runner to complete verify and commit."
    if latest.turn_type == "wave_complete":
        return "Ready to dispatch next wave."
    summary = latest.summary.strip()
    return summary or None


def _wave_summary_for_header(
    turns: list[OrchestratorTurn],
    rows: list[StatusRow],
) -> str | None:
    """Return latest wave_summary when no wave is in progress (W5.5)."""
    in_progress = any("progress" in row.status.lower() for row in rows)
    if in_progress:
        return None
    for turn in reversed(turns):
        if turn.turn_type == "wave_complete" and turn.wave_summary.strip():
            return turn.wave_summary.strip()
    return None


def _log_fragment_url(run_id: str, node_id: str, *, api_token: str = "") -> str:
    path = f"/runs/{run_id}/waves/{quote(node_id, safe='')}/log"
    if api_token:
        return f"{path}?token={quote(api_token, safe='')}"
    return path


def _feed_entries(
    snap: OrchestratorSnapshot,
    *,
    run_id: str,
    wave_to_node: dict[str, str],
    api_token: str = "",
) -> list[OrchestratorFeedEntry]:
    entries: list[OrchestratorFeedEntry] = []
    for turn in snap.turns[-_FEED_LIMIT:]:
        _, node_id = parse_wave_node_from_turn(turn, wave_to_node)
        log_url = _log_fragment_url(run_id, node_id, api_token=api_token) if node_id else None
        ts = turn.timestamp or ""
        summary = turn.summary.strip() or turn.turn_type.replace("_", " ")
        entries.append(
            OrchestratorFeedEntry(
                turn_n=turn.turn_n,
                turn_type=turn.turn_type,
                timestamp=ts,
                summary=summary,
                node_id=node_id,
                log_url=log_url,
            )
        )
    return list(reversed(entries))


def build_orchestrator_view(
    run_dir: Path | None,
    *,
    run_id: str,
    wave_to_node: dict[str, str] | None = None,
    is_live: bool = False,
    api_token: str = "",
) -> OrchestratorPanelView:
    """Build orchestrator panel context from ``orchestrator-status.md``.

    Args:
        run_dir (Path | None): Run directory; ``None`` when run is missing.
        run_id (str): Run identifier for log fragment URLs.
        wave_to_node (dict[str, str] | None): ``wave_id`` → ``node_id`` map.
        is_live (bool): Whether the engine process is still running.
        api_token (str): Optional API token for fragment auth query params.

    Returns:
        OrchestratorPanelView: Template-ready snapshot; ``enabled=False`` when
        no orchestrator status file exists.

    Examples:
        >>> build_orchestrator_view(None, run_id="r1")
        OrchestratorPanelView(enabled=False, rows=[], current_wave=None, ...)
    """
    if run_dir is None:
        return OrchestratorPanelView()
    status_path = run_dir / "orchestrator-status.md"
    if not status_path.is_file():
        return OrchestratorPanelView()

    snap = read_latest(run_dir)
    if not snap.rows and not snap.turns:
        return OrchestratorPanelView(enabled=True)

    mapping = wave_to_node or {}
    current = _current_wave_from_rows(snap.rows) or _current_wave_from_turns(snap.turns)
    gate = _latest_gate(snap.turns)
    latest = snap.turns[-1] if snap.turns else None

    return OrchestratorPanelView(
        enabled=True,
        rows=snap.rows,
        current_wave=current,
        gate_notice=gate.summary.strip() if gate else None,
        gate_kind=gate.turn_type if gate else None,
        next_action=_next_action(latest, gate),
        wave_summary=_wave_summary_for_header(snap.turns, snap.rows),
        feed=_feed_entries(snap, run_id=run_id, wave_to_node=mapping, api_token=api_token),
        poll_orchestrator=is_live,
        orchestrator_poll_s=ORCHESTRATOR_POLL_INTERVAL_S,
    )
