"""tripll.api._artefacts — safe read-only access to run artefact files.

Resolves per-attempt log paths under ``runs/<folder>/<run-id>/logs/`` with
run-directory containment checks (D4).  W4 adds graph/report readers and
pause-marker banners (D9, D10).

Exports:
    MAX_LOG_TAIL_BYTES — default tail window (200 KiB).
    TIMELINE_EVENT_LIMIT — max events replayed in the dashboard timeline (500).
    RUN_ARTEFACT_FOLDERS — allowed top-level run folders.
    LOG_FILENAME_RE — filename pattern for attempt logs.
    PAUSE_MARKER_FILES — pause / escalation marker filenames (D10).
    PAUSE_BANNER_SNIPPET_LEN — first-line truncation for banner snippets.
    sanitize_node_id_for_log — map ``node_id`` to log filename stem.
    resolve_attempt_log_path — safe resolver; raises on escape or mismatch.
    tail_log_file — read-only tail of an attempt log (D4).
    LogPathError — raised when a log path cannot be resolved safely.
    PauseBanner — one pause/escalation marker for the run header.
    BatchTimelineNode — wave node overlay for a batch swimlane.
    BatchTimelineLane — one batch row in the swimlane chart.
    BatchTimelineData — full batch-timeline model for templates.
    read_pause_banners — load D10 marker files from a run directory.
    build_batch_timeline — batch layers from graph.json or report.md (D9).
    read_report_markdown — read ``report.md`` when present.
    render_report_markdown — minimal safe Markdown → HTML for report embed.
    parse_escalation_reasons — per-node failure lines from ``escalation.md``.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tripll.log_redact import redact_log_text

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.ledger import EventRow
    from tripll.pipeline import RunsRoot

MAX_LOG_TAIL_BYTES = 200 * 1024
MAX_LOG_PANEL_BYTES = 512 * 1024
MAX_LOG_FULL_BYTES = 8 * 1024 * 1024
TIMELINE_EVENT_LIMIT = 500
RUN_ARTEFACT_FOLDERS = frozenset({"processing", "processed", "failed"})
LOG_FILENAME_RE = re.compile(r"^(?P<stem>.+)-attempt(?P<attempt>\d+)\.log$")


class LogPathError(ValueError):
    """Raised when a log path fails safety or existence checks."""


def sanitize_node_id_for_log(node_id: str) -> str:
    """Return the filename-safe form of *node_id* (matches engine log naming).

    Args:
        node_id (str): Raw wave node id (e.g. ``plan:W1``).

    Returns:
        str: Sanitised stem used in ``<stem>-attempt<N>.log``.

    Examples:
        >>> sanitize_node_id_for_log("telemetry:W0->Final")
        'telemetry_W0-Final'
    """
    return node_id.replace(":", "_").replace("/", "_").replace(">", "")


def resolve_attempt_log_path(
    rr: RunsRoot,
    run_id: str,
    node_id: str,
    attempt_n: int,
) -> Path:
    """Resolve the on-disk path for one attempt log under the run directory (D4).

    Only serves files matching
    ``runs/<folder>/<run_id>/logs/<sanitized-node-id>-attempt<N>.log`` where
    ``<folder>`` ∈ :data:`RUN_ARTEFACT_FOLDERS`.  Rejects path traversal and
    paths that resolve outside the run directory (including symlink escapes).

    Args:
        rr (RunsRoot): Configured runs root.
        run_id (str): Run identifier.
        node_id (str): Wave node id.
        attempt_n (int): 1-based attempt number.

    Returns:
        Path: Resolved absolute log file path.

    Raises:
        LogPathError: When the run, logs dir, or file is missing or unsafe.

    Examples:
        >>> callable(resolve_attempt_log_path)
        True
    """
    if attempt_n < 1:
        raise LogPathError(f"attempt_n must be >= 1, got {attempt_n}")

    run_dir = rr.find_run_dir(run_id)
    if run_dir is None:
        raise LogPathError(f"Run not found: {run_id!r}")

    folder_name = run_dir.parent.name
    if folder_name not in RUN_ARTEFACT_FOLDERS:
        raise LogPathError(f"Run folder not allowed: {folder_name!r}")

    logs_dir = run_dir / "logs"
    if not logs_dir.is_dir():
        raise LogPathError(f"Logs directory missing for run {run_id!r}")

    stem = sanitize_node_id_for_log(node_id)
    if ".." in stem or "/" in stem or "\\" in stem:
        raise LogPathError(f"Invalid node_id for log path: {node_id!r}")
    filename = f"{stem}-attempt{attempt_n}.log"
    if not LOG_FILENAME_RE.match(filename):
        raise LogPathError(f"Invalid log filename: {filename!r}")

    candidate = logs_dir / filename
    if candidate.is_symlink():
        raise LogPathError(f"Log path is a symlink: {candidate}")
    resolved = candidate.resolve(strict=False)
    run_resolved = run_dir.resolve()
    logs_resolved = logs_dir.resolve()

    if not str(resolved).startswith(str(logs_resolved) + "/") and resolved != logs_resolved:
        raise LogPathError(f"Log path escapes logs dir: {candidate}")
    if not str(resolved).startswith(str(run_resolved) + "/"):
        raise LogPathError(f"Log path escapes run dir: {candidate}")
    if not resolved.is_file():
        raise LogPathError(f"Log file not found: {resolved}")

    return resolved


def tail_log_file(path: Path, *, max_bytes: int = MAX_LOG_TAIL_BYTES) -> tuple[str, bool]:
    """Return the tail of a log file as text (read-only, D4).

    Reads at most *max_bytes* from the end of the file.  When the file is
    larger than *max_bytes*, the returned text is prefixed with a truncation
    notice and ``truncated`` is ``True``.

    Args:
        path (Path): Resolved log file path (from :func:`resolve_attempt_log_path`).
        max_bytes (int): Maximum bytes to read from the file tail.

    Returns:
        tuple[str, bool]: ``(content, truncated)``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        ...     f.write("hello\\nworld\\n")
        ...     p = Path(f.name)
        >>> text, truncated = tail_log_file(p, max_bytes=1024)
        >>> "hello" in text
        True
        >>> truncated
        False
    """
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as fh:
        if truncated:
            fh.seek(size - max_bytes)
            raw = fh.read(max_bytes)
            # Drop partial first line when tailing mid-file.
            if b"\n" in raw:
                raw = raw.split(b"\n", 1)[1]
        else:
            raw = fh.read()
    text = redact_log_text(raw.decode("utf-8", errors="replace"))
    if truncated:
        text = (
            f"[Log truncated — showing last {max_bytes // 1024} KiB of "
            f"{size // 1024} KiB total. Open full log in a new tab for the complete file.]\n"
            f"{text}"
        )
    return text, truncated


def read_log_file(path: Path, *, max_bytes: int = MAX_LOG_FULL_BYTES) -> tuple[str, bool]:
    """Read a log file from the start, capped at *max_bytes* (D4).

    Args:
        path (Path): Resolved log file path.
        max_bytes (int): Maximum bytes to read from the file.

    Returns:
        tuple[str, bool]: ``(content, truncated)``.
    """
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as fh:
        raw = fh.read(max_bytes if truncated else size)
    text = redact_log_text(raw.decode("utf-8", errors="replace"))
    if truncated:
        text += (
            f"\n\n[Log truncated at {max_bytes // 1024} KiB — "
            f"file is {size // 1024} KiB on disk.]\n"
        )
    return text, truncated


def read_log_file_from_offset(
    path: Path,
    offset: int,
    *,
    max_bytes: int = 256 * 1024,
) -> tuple[str, int, bool]:
    """Read log bytes starting at *offset* (append-only tail for live panels).

    Args:
        path (Path): Resolved log file path.
        offset (int): Byte offset from the start of the file (0-based).
        max_bytes (int): Maximum bytes to read in one poll.

    Returns:
        tuple[str, int, bool]: ``(new_text, new_offset, truncated)`` where
        *truncated* is True when more bytes remain after this read.
    """
    size = path.stat().st_size
    start = max(0, offset)
    if start >= size:
        return "", size, False
    to_read = min(max_bytes, size - start)
    with path.open("rb") as fh:
        fh.seek(start)
        raw = fh.read(to_read)
    new_offset = start + len(raw)
    truncated = new_offset < size
    text = redact_log_text(raw.decode("utf-8", errors="replace"))
    return text, new_offset, truncated


# ---------------------------------------------------------------------------
# Pause / escalation markers (D10)
# ---------------------------------------------------------------------------

PAUSE_BANNER_SNIPPET_LEN = 120

PAUSE_MARKER_FILES: tuple[tuple[str, str, str], ...] = (
    ("quota-paused.md", "quota", "banner-quota"),
    ("cost-budget-paused.md", "cost_budget", "banner-cost"),
    ("pause-requested.md", "pause_requested", "banner-pause"),
    ("escalation.md", "escalation", "banner-escalation"),
)


@dataclass(frozen=True)
class PauseBanner:
    """One pause or escalation marker surfaced in the run header (D10).

    Args:
        kind (str): Short classifier (``quota``, ``escalation``, …).
        filename (str): Marker filename in the run directory.
        snippet (str): First-line summary, truncated.
        full_text (str): Full marker file contents.
        css_class (str): Banner colour class for templates.
    """

    kind: str
    filename: str
    snippet: str
    full_text: str
    css_class: str


def _first_line_snippet(text: str, *, max_len: int = PAUSE_BANNER_SNIPPET_LEN) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "(empty marker)"
    if len(line) <= max_len:
        return line
    return line[: max_len - 1] + "…"


def read_pause_banners(run_dir: Path | None) -> list[PauseBanner]:
    """Return pause/escalation banners for marker files present in *run_dir* (D10).

    Args:
        run_dir (Path | None): Resolved run directory, or ``None`` when missing.

    Returns:
        list[PauseBanner]: Ordered banners (quota → cost → pause → escalation).

    Examples:
        >>> read_pause_banners(None)
        []
    """
    if run_dir is None or not run_dir.is_dir():
        return []
    banners: list[PauseBanner] = []
    for filename, kind, css_class in PAUSE_MARKER_FILES:
        path = run_dir / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        banners.append(
            PauseBanner(
                kind=kind,
                filename=filename,
                snippet=_first_line_snippet(text),
                full_text=text,
                css_class=css_class,
            )
        )
    return banners


# ---------------------------------------------------------------------------
# Batch timeline (D9)
# ---------------------------------------------------------------------------

_BATCH_HEADING_RE = re.compile(r"^-\s+\*\*(?P<batch_id>[^*]+)\*\*", re.MULTILINE)
_WAVES_IN_REPORT_RE = re.compile(r"waves\s+([A-Za-z0-9,\s-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class BatchTimelineNode:
    """One wave node in a batch swimlane, coloured by ledger phase.

    Args:
        node_id (str): Wave node identifier.
        wave_id (str): Wave label from the graph.
        phase (str): Latest ledger phase for this node.
    """

    node_id: str
    wave_id: str
    phase: str


@dataclass
class BatchTimelineLane:
    """Horizontal swimlane for one execution batch (D9).

    Args:
        batch_id (str): Batch identifier (``Pre-0``, ``A``, …).
        label (str): Human-readable batch label.
        is_human_gate (bool): True for Pre-0 / review-gate batches.
        nodes (list[BatchTimelineNode]): Wave nodes in this batch.
    """

    batch_id: str
    label: str
    is_human_gate: bool = False
    nodes: list[BatchTimelineNode] = field(default_factory=list)


@dataclass
class BatchTimelineData:
    """Batch swimlane chart model for dashboard templates (D9).

    Args:
        lanes (list[BatchTimelineLane]): Ordered batch rows.
        source (str): ``graph.json``, ``report.md``, or ``ledger``.
    """

    lanes: list[BatchTimelineLane] = field(default_factory=list)
    source: str = "ledger"


def _phase_for_node(node_id: str, latest: dict[str, EventRow], fallback: str = "queued") -> str:
    ev = latest.get(node_id)
    return ev.phase if ev is not None else fallback


def _nodes_in_batch_dict(graph: dict[str, Any], batch: dict[str, Any]) -> list[str]:
    nodes: dict[str, Any] = graph.get("nodes") or {}
    wave_ids: list[str] = list(batch.get("wave_ids") or [])
    lanes: list[str] = list(batch.get("lanes") or [])
    out: list[str] = []
    for wid in wave_ids:
        for nid, node in nodes.items():
            if isinstance(node, dict) and node.get("wave_id") == wid and nid not in out:
                out.append(nid)
    if not out and lanes:
        for nid, node in nodes.items():
            if isinstance(node, dict) and node.get("lane") in lanes and nid not in out:
                out.append(nid)
    return out


def _timeline_lane_from_batch(
    batch: dict[str, Any],
    graph: dict[str, Any],
    latest: dict[str, EventRow],
) -> BatchTimelineLane:
    node_ids = _nodes_in_batch_dict(graph, batch)
    nodes_dict: dict[str, Any] = graph.get("nodes") or {}
    nodes: list[BatchTimelineNode] = []
    for nid in node_ids:
        node = nodes_dict.get(nid) or {}
        wave_id = str(node.get("wave_id") or nid.split(":")[-1])
        nodes.append(
            BatchTimelineNode(
                node_id=nid,
                wave_id=wave_id,
                phase=_phase_for_node(nid, latest),
            )
        )
    return BatchTimelineLane(
        batch_id=str(batch.get("batch_id") or "?"),
        label=str(batch.get("label") or batch.get("batch_id") or "batch"),
        is_human_gate=bool(batch.get("is_human_gate")),
        nodes=nodes,
    )


def _parse_report_batch_lanes(report_text: str) -> list[tuple[str, str, list[str]]]:
    """Extract batch rows from the ``## Batches`` section of *report_text*.

    Returns:
        list[tuple[str, str, list[str]]]: ``(batch_id, label, wave_ids)`` tuples.
    """
    match = re.search(r"^##\s+Batches\s*$", report_text, re.MULTILINE | re.IGNORECASE)
    if match is None:
        return []
    section = report_text[match.end() :]
    next_heading = re.search(r"^##\s+", section, re.MULTILINE)
    if next_heading:
        section = section[: next_heading.start()]
    lanes: list[tuple[str, str, list[str]]] = []
    for line in section.splitlines():
        m = _BATCH_HEADING_RE.match(line.strip())
        if not m:
            continue
        batch_id = m.group("batch_id").strip()
        wave_ids: list[str] = []
        wm = _WAVES_IN_REPORT_RE.search(line)
        if wm:
            wave_ids = [w.strip() for w in wm.group(1).split(",") if w.strip()]
        label = line.split("):", 1)[-1].strip() if "):" in line else batch_id
        lanes.append((batch_id, label, wave_ids))
    return lanes


def _timeline_from_report(
    report_text: str,
    graph: dict[str, Any] | None,
    latest: dict[str, EventRow],
    ledger_node_ids: list[str],
) -> BatchTimelineData:
    lanes: list[BatchTimelineLane] = []
    nodes_dict: dict[str, Any] = (graph or {}).get("nodes") or {}
    for batch_id, label, wave_ids in _parse_report_batch_lanes(report_text):
        node_ids: list[str] = []
        if wave_ids and nodes_dict:
            for wid in wave_ids:
                for nid, node in nodes_dict.items():
                    if (
                        isinstance(node, dict)
                        and node.get("wave_id") == wid
                        and nid not in node_ids
                    ):
                        node_ids.append(nid)
        if not node_ids and wave_ids:
            for nid in ledger_node_ids:
                suffix = nid.split(":")[-1]
                if suffix in wave_ids and nid not in node_ids:
                    node_ids.append(nid)
        nodes = [
            BatchTimelineNode(
                node_id=nid,
                wave_id=nid.split(":")[-1],
                phase=_phase_for_node(nid, latest),
            )
            for nid in node_ids
        ]
        lanes.append(
            BatchTimelineLane(
                batch_id=batch_id,
                label=label,
                is_human_gate=batch_id.lower().startswith("pre"),
                nodes=nodes,
            )
        )
    return BatchTimelineData(lanes=lanes, source="report.md")


def _timeline_from_ledger(
    ledger_node_ids: list[str], latest: dict[str, EventRow]
) -> BatchTimelineData:
    nodes = [
        BatchTimelineNode(
            node_id=nid,
            wave_id=nid.split(":")[-1],
            phase=_phase_for_node(nid, latest),
        )
        for nid in ledger_node_ids
    ]
    return BatchTimelineData(
        lanes=[BatchTimelineLane(batch_id="waves", label="Waves", nodes=nodes)],
        source="ledger",
    )


def build_batch_timeline(
    run_dir: Path | None,
    *,
    latest: dict[str, EventRow],
    ledger_node_ids: list[str],
) -> BatchTimelineData:
    """Build batch swimlane data from ``graph.json`` with report/ledger fallbacks (D9).

    Prefers ``graph.json`` batch metadata when present; otherwise parses
    ``report.md`` phase headings; finally lists all ledger waves in one lane.

    Args:
        run_dir (Path | None): Resolved run directory.
        latest (dict[str, EventRow]): Collapsed ledger events per node (D2).
        ledger_node_ids (list[str]): Wave node ids from the ledger.

    Returns:
        BatchTimelineData: Swimlane rows for template rendering.

    Examples:
        >>> build_batch_timeline(None, latest={}, ledger_node_ids=["p:W1"]).source
        'ledger'
    """
    graph: dict[str, Any] | None = None
    if run_dir is not None:
        graph_path = run_dir / "graph.json"
        if graph_path.is_file():
            try:
                loaded = json.loads(graph_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    graph = loaded
            except json.JSONDecodeError:
                graph = None

    if graph is not None:
        batches = graph.get("batches")
        if isinstance(batches, list) and batches:
            lanes = [
                _timeline_lane_from_batch(b, graph, latest) for b in batches if isinstance(b, dict)
            ]
            if lanes:
                return BatchTimelineData(lanes=lanes, source="graph.json")

    if run_dir is not None:
        report_path = run_dir / "report.md"
        if report_path.is_file():
            report_text = report_path.read_text(encoding="utf-8", errors="replace")
            data = _timeline_from_report(report_text, graph, latest, ledger_node_ids)
            if data.lanes:
                return data

    return _timeline_from_ledger(ledger_node_ids, latest)


# ---------------------------------------------------------------------------
# Report embed (W4.3)
# ---------------------------------------------------------------------------


def read_report_markdown(run_dir: Path | None) -> str | None:
    """Read ``report.md`` from *run_dir* when the file exists.

    Args:
        run_dir (Path | None): Resolved run directory.

    Returns:
        str | None: File contents, or ``None`` when missing.
    """
    if run_dir is None:
        return None
    path = run_dir / "report.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)


def render_report_markdown(text: str) -> str:
    """Convert *text* to minimal safe HTML (headings, lists, code blocks).

    Falls back to a single escaped ``<pre>`` block when no structural elements
    are recognised.

    Args:
        text (str): Raw ``report.md`` body.

    Returns:
        str: HTML fragment safe for embedding in Jinja templates.

    Examples:
        >>> "heading" in render_report_markdown("# Title\\n\\n- item")
        True
    """
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    in_ul = False
    saw_structure = False

    for line in lines:
        if line.strip().startswith("```"):
            saw_structure = True
            if in_code:
                out.append(f"<pre><code>{html.escape(chr(10).join(code_buf))}</code></pre>")
                code_buf = []
                in_code = False
            else:
                if in_ul:
                    out.append("</ul>")
                    in_ul = False
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            saw_structure = True
            if in_ul:
                out.append("</ul>")
                in_ul = False
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue

        if line.startswith("- "):
            saw_structure = True
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_markdown(line[2:])}</li>")
            continue

        if not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue

        if in_ul:
            out.append("</ul>")
            in_ul = False
        saw_structure = True
        out.append(f"<p>{_inline_markdown(line)}</p>")

    if in_ul:
        out.append("</ul>")
    if in_code and code_buf:
        out.append(f"<pre><code>{html.escape(chr(10).join(code_buf))}</code></pre>")

    if not saw_structure:
        return f'<pre class="report-fallback">{html.escape(text)}</pre>'
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Escalation reasons (per-node failure detail)
# ---------------------------------------------------------------------------

_ESCALATION_LINE_RE = re.compile(
    r"^-\s+(?P<node_id>[^\s]+)\s+\((?P<attempts>\d+)\s+attempts?\):\s+(?P<reason>.+)$"
)


def parse_escalation_reasons(run_dir: Path | None) -> dict[str, str]:
    """Parse per-node failure reasons from ``escalation.md``.

    Args:
        run_dir (Path | None): Resolved run directory.

    Returns:
        dict[str, str]: ``node_id`` → failure reason text.

    Examples:
        >>> parse_escalation_reasons(None)
        {}
    """
    if run_dir is None:
        return {}
    path = run_dir / "escalation.md"
    if not path.is_file():
        return {}
    reasons: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _ESCALATION_LINE_RE.match(line.strip())
        if match is None:
            continue
        reasons[match.group("node_id")] = match.group("reason").strip()
    return reasons
