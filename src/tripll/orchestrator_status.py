"""tripll.orchestrator_status — ``orchestrator-status.md`` read/write (D3, D4).

Renders Multitask-style status tables and append-only turn logs. Engine hooks
call :func:`sync_orchestrator_status` on each transition (W2); W1 ships the
formatter module and atomic rewrite helper.

Exports:
    StatusRow — one row in the status table.
    OrchestratorTurn — one append-only turn log entry.
    OrchestratorSnapshot — parsed on-disk state.
    render_status_table — Markdown table from rows.
    append_turn — append a turn and rewrite the status file.
    read_latest — parse ``orchestrator-status.md`` from a run dir.
    sync_orchestrator_status — rebuild file from graph + turn context.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.graph import OrchestratorConfig, RunGraph

_STATUS_COLUMNS = ("Wave", "Status", "Branch", "Commit", "Evidence / blockers")
_STATUS_SEP = "|------|--------|--------|--------|---------------------|"
_TURN_HEADER = re.compile(r"^### Turn (\d+) — (\S+)", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\| (.+?) \|$")


@dataclass
class StatusRow:
    """One row in the orchestrator status table."""

    wave: str
    status: str = "pending"
    branch: str = "—"
    commit: str = "—"
    evidence: str = ""


@dataclass
class OrchestratorTurn:
    """One append-only turn in the orchestrator log."""

    turn_type: str
    summary: str
    body: str = ""
    turn_n: int | None = None
    timestamp: str | None = None
    wave_summary: str = ""


@dataclass
class OrchestratorSnapshot:
    """Parsed ``orchestrator-status.md`` snapshot."""

    run_id: str
    updated_at: str = ""
    feature_branch: str | None = None
    mode: str = "serial"
    rows: list[StatusRow] = field(default_factory=list)
    turns: list[OrchestratorTurn] = field(default_factory=list)


def _iso_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def render_status_table(rows: list[StatusRow]) -> str:
    """Render the ``## Status table`` Markdown block (D4).

    Args:
        rows (list[StatusRow]): Table body rows.

    Returns:
        str: Markdown table with header and separator.

    Examples:
        >>> md = render_status_table([StatusRow("W0", status="done")])
        >>> "| Wave | Status |" in md
        True
    """
    header = "| " + " | ".join(_STATUS_COLUMNS) + " |"
    sep = _STATUS_SEP
    body_lines: list[str] = []
    for row in rows:
        branch = row.branch if row.branch.startswith("`") else f"`{row.branch}`"
        commit = row.commit if row.commit in {"—", "-"} else f"`{row.commit}`"
        body_lines.append(f"| {row.wave} | {row.status} | {branch} | {commit} | {row.evidence} |")
    return "\n".join([header, sep, *body_lines])


def _render_turn_section(turn: OrchestratorTurn) -> str:
    ts = turn.timestamp or _iso_now()
    lines = [f"### Turn {turn.turn_n} — {turn.turn_type}", "", f"{ts} — {turn.summary}", ""]
    if turn.body.strip():
        lines.append(turn.body.strip())
        lines.append("")
    if turn.wave_summary.strip():
        lines.append(f"**Summary:** {turn.wave_summary.strip()}")
        lines.append("")
    return "\n".join(lines)


def _render_document(
    *,
    run_id: str,
    rows: list[StatusRow],
    turns: list[OrchestratorTurn],
    feature_branch: str | None,
    mode: str,
    updated_at: str | None = None,
) -> str:
    ts = updated_at or _iso_now()
    branch_line = feature_branch or "—"
    parts = [
        f"# Orchestrator status — {run_id}",
        "",
        f"**Updated:** {ts}",
        f"**Feature branch:** `{branch_line}` | **Mode:** {mode}",
        "",
        "## Status table",
        "",
        render_status_table(rows),
        "",
        "## Turn log",
        "",
    ]
    for turn in turns:
        parts.append(_render_turn_section(turn))
    return "\n".join(parts).rstrip() + "\n"


def _parse_status_rows(table_text: str) -> list[StatusRow]:
    rows: list[StatusRow] = []
    in_table = False
    for line in table_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if "Wave" in line and "Status" in line:
            in_table = True
            continue
        if in_table and line.strip().startswith("|---"):
            continue
        if not in_table:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        rows.append(
            StatusRow(
                wave=strip_backticks(cells[0]),
                status=cells[1],
                branch=strip_backticks(cells[2]),
                commit=strip_backticks(cells[3]),
                evidence=cells[4],
            )
        )
    return rows


def strip_backticks(value: str) -> str:
    """Remove surrounding backticks from *value*.

    Args:
        value (str): Raw cell text.

    Returns:
        str: Cleaned value.

    Examples:
        >>> strip_backticks("`feature/foo`")
        'feature/foo'
    """
    return value.strip().strip("`")


def read_latest(run_dir: Path) -> OrchestratorSnapshot:
    """Parse ``orchestrator-status.md`` from *run_dir*.

    Args:
        run_dir (Path): Run directory containing the status file.

    Returns:
        OrchestratorSnapshot: Parsed snapshot; empty when file is absent.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     snap = read_latest(Path(d))
        ...     snap.run_id
        ''
    """
    path = run_dir / "orchestrator-status.md"
    if not path.is_file():
        return OrchestratorSnapshot(run_id=run_dir.name)
    text = path.read_text()
    run_m = re.search(r"^# Orchestrator status — (\S+)", text, re.MULTILINE)
    updated_m = re.search(r"\*\*Updated:\*\* (.+)", text)
    branch_m = re.search(r"\*\*Feature branch:\*\* `([^`]*)`", text)
    mode_m = re.search(r"\*\*Mode:\*\* (\S+)", text)
    table_section = ""
    if "## Status table" in text:
        after = text.split("## Status table", 1)[1]
        table_section = after.split("## Turn log", 1)[0]
    turns: list[OrchestratorTurn] = []
    for m in _TURN_HEADER.finditer(text):
        turn_n = int(m.group(1))
        turn_type = m.group(2)
        start = m.end()
        next_m = _TURN_HEADER.search(text, start)
        chunk = text[start : next_m.start() if next_m else len(text)].strip()
        summary = ""
        body = chunk
        if chunk:
            first = chunk.splitlines()[0].strip()
            if " — " in first:
                summary = first.split(" — ", 1)[1]
                body = "\n".join(chunk.splitlines()[1:]).strip()
        wave_summary = ""
        sm = re.search(r"\*\*Summary:\*\* (.+)", chunk, re.DOTALL)
        if sm:
            wave_summary = sm.group(1).strip()
        turns.append(
            OrchestratorTurn(
                turn_n=turn_n,
                turn_type=turn_type,
                summary=summary,
                body=body,
                wave_summary=wave_summary,
            )
        )
    return OrchestratorSnapshot(
        run_id=run_m.group(1) if run_m else run_dir.name,
        updated_at=updated_m.group(1).strip() if updated_m else "",
        feature_branch=branch_m.group(1) if branch_m else None,
        mode=mode_m.group(1) if mode_m else "serial",
        rows=_parse_status_rows(table_section),
        turns=turns,
    )


def append_turn(run_dir: Path, turn: OrchestratorTurn) -> Path:
    """Append one turn and rewrite ``orchestrator-status.md`` atomically.

    Args:
        run_dir (Path): Run directory.
        turn (OrchestratorTurn): Turn to append.

    Returns:
        Path: Written status file path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     run = Path(d)
        ...     p = append_turn(run, OrchestratorTurn("bootstrap", "Run started"))
        ...     p.name
        'orchestrator-status.md'
    """
    snap = read_latest(run_dir)
    if not turn.timestamp:
        turn.timestamp = _iso_now()
    if turn.turn_n is None:
        turn.turn_n = len(snap.turns) + 1
    snap.turns.append(turn)
    path = run_dir / "orchestrator-status.md"
    doc = _render_document(
        run_id=snap.run_id or run_dir.name,
        rows=snap.rows,
        turns=snap.turns,
        feature_branch=snap.feature_branch,
        mode=snap.mode,
    )
    _atomic_write_text(path, doc)
    return path


def sync_orchestrator_status(
    run_dir: Path,
    graph: RunGraph,
    *,
    rows: list[StatusRow] | None = None,
    turns: list[OrchestratorTurn] | None = None,
    turn: OrchestratorTurn | None = None,
    run_id: str | None = None,
) -> Path:
    """Rebuild ``orchestrator-status.md`` from graph config and optional turn.

    Called from engine hooks on transitions (W2). When *turn* is supplied it is
    appended; otherwise the existing turn log is preserved.

    When both *rows* and *turns* are supplied the on-disk file is not read back
    (engine hot loop keeps authoritative in-memory state).

    Args:
        run_dir (Path): Run directory.
        graph (RunGraph): Parsed run graph (may carry ``orchestrator`` config).
        rows (list[StatusRow] | None): Status rows; keeps existing when ``None``.
        turns (list[OrchestratorTurn] | None): In-memory turn log; skips disk read
            when supplied together with *rows*.
        turn (OrchestratorTurn | None): Optional new turn to append.
        run_id (str | None): Override run id in the header.

    Returns:
        Path: Written status file path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from tripll.graph import OrchestratorConfig, RunGraph
        >>> with tempfile.TemporaryDirectory() as d:
        ...     run = Path(d)
        ...     g = RunGraph(
        ...         run_id="r1",
        ...         orchestrator=OrchestratorConfig(True, "p.md", "feature/x"),
        ...     )
        ...     p = sync_orchestrator_status(run, g, rows=[StatusRow("W0")])
        ...     p.exists()
        True
    """
    cfg: OrchestratorConfig | None = graph.orchestrator
    if rows is not None and turns is not None:
        feature_branch = cfg.feature_branch if cfg else None
        mode = "serial"
        rid = run_id or graph.run_id or run_dir.name
        table_rows = list(rows)
        turn_list = turns
    else:
        snap = read_latest(run_dir)
        feature_branch = cfg.feature_branch if cfg else snap.feature_branch
        mode = "serial" if cfg and cfg.enabled else snap.mode
        rid = run_id or graph.run_id or snap.run_id or run_dir.name
        table_rows = list(rows) if rows is not None else list(snap.rows)
        turn_list = list(snap.turns) if turns is None else turns
    if not table_rows and cfg and cfg.serial_waves:
        branch = feature_branch or "—"
        table_rows = [StatusRow(w, branch=branch) for w in cfg.serial_waves]
    if turn is not None:
        if not turn.timestamp:
            turn.timestamp = _iso_now()
        if turn.turn_n is None:
            turn.turn_n = len(turn_list) + 1
        turn_list.append(turn)
    path = run_dir / "orchestrator-status.md"
    doc = _render_document(
        run_id=rid,
        rows=table_rows,
        turns=turn_list,
        feature_branch=feature_branch,
        mode=mode,
    )
    _atomic_write_text(path, doc)
    return path
