"""Idempotent plan breakdown ticket publish orchestration (PM-02, W6.4-W6.5).

Exports:
    WaveSlice — one wave row extracted from a plan file.
    PublishResult — counts and artifact paths from one publish run.
    extract_waves — parse ``## Wave`` sections from markdown.
    publish_plan_breakdown — ordered local artifact → summary → tickets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for artifact I/O

from tripll.trackers.base import Epic, Ticket, Tracker

__all__ = [
    "PublishResult",
    "WaveSlice",
    "extract_waves",
    "publish_plan_breakdown",
]

WAVE_HEADING_RE = re.compile(
    r"^##\s+Wave\s+(\S+)(?:\s+(?:—|-)\s+(.+))?\s*$",
    re.MULTILINE,
)
_WAVE_ID_RE = re.compile(r"^(W\d+)\b")


@dataclass(frozen=True)
class WaveSlice:
    """One wave section extracted from a plan markdown file."""

    wave_id: str
    title: str
    body: str


@dataclass(frozen=True)
class PublishResult:
    """Outcome of :func:`publish_plan_breakdown`."""

    created: int
    skipped: int
    artifact_path: Path
    summary_ref: str | None = None


def extract_waves(plan_text: str) -> list[WaveSlice]:
    """Parse ``## Wave`` headings and bodies from *plan_text*.

    Args:
        plan_text (str): Full plan markdown.

    Returns:
        list[WaveSlice]: Ordered wave slices.

    Examples:
        >>> extract_waves("## Wave W2 — rules\\n- [ ] task\\n")[0].wave_id
        'W2'
    """
    waves: list[WaveSlice] = []
    matches = list(WAVE_HEADING_RE.finditer(plan_text))
    for index, match in enumerate(matches):
        wave_id = match.group(1).strip()
        subtitle = (match.group(2) or "").strip()
        title = f"{wave_id} — {subtitle}" if subtitle else wave_id
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plan_text)
        body = plan_text[start:end].strip()
        waves.append(WaveSlice(wave_id=wave_id, title=title, body=body))
    return waves


def _wave_id_from_title(title: str) -> str | None:
    matched = _WAVE_ID_RE.match(title.strip())
    return matched.group(1) if matched else None


def _child_for_wave(children: list[Ticket], wave_id: str) -> Ticket | None:
    for child in children:
        child_wave = _wave_id_from_title(child.title)
        if child_wave == wave_id:
            return child
    return None


def _render_breakdown(plan_path: Path, epic: Epic, waves: list[WaveSlice]) -> str:
    lines = [
        f"# Breakdown: {epic.title}",
        "",
        f"Source: `{plan_path}`",
        "",
    ]
    for wave in waves:
        lines.append(f"## {wave.title}")
        if wave.body:
            lines.append(wave.body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _artifact_path(plan_path: Path) -> Path:
    return plan_path.with_name(f"{plan_path.stem}.breakdown.md")


def publish_plan_breakdown(
    *,
    tracker: Tracker,
    plan_path: Path,
    parent_ref: str,
    dry_run: bool = False,
) -> PublishResult:
    """Publish a plan breakdown through *tracker* with idempotent child creation.

    Side-effect order: local artifact → breakdown summary → child tickets.
    Listing existing children happens before any creation (W6.4).

    Args:
        tracker (Tracker): Tracker implementation (fake or real).
        plan_path (Path): Wave-plan markdown path.
        parent_ref (str): Parent epic ref in the tracker namespace.
        dry_run (bool, optional): When True, write the local artifact only.

    Returns:
        PublishResult: Created/skipped counts and artifact location.

    Examples:
        >>> publish_plan_breakdown  # doctest: +SKIP
    """
    plan_path = plan_path.resolve()
    plan_text = plan_path.read_text(encoding="utf-8")
    waves = extract_waves(plan_text)
    epic = tracker.fetch_epic(parent_ref)
    breakdown_md = _render_breakdown(plan_path, epic, waves)

    artifact_path = _artifact_path(plan_path)
    artifact_path.write_text(breakdown_md, encoding="utf-8")

    summary_ref: str | None = None
    if not dry_run:
        summary_ref = tracker.publish_breakdown(parent_ref, breakdown_md)

    existing = tracker.list_children(parent_ref)
    created = 0
    skipped = 0
    for wave in waves:
        if _child_for_wave(existing, wave.wave_id) is not None:
            skipped += 1
            continue
        if dry_run:
            skipped += 1
            continue
        ticket = Ticket(ref="", title=wave.title, body=wave.body)
        child_ref = tracker.create_child(parent_ref, ticket)
        created += 1
        existing.append(Ticket(ref=child_ref, title=wave.title, body=wave.body))

    return PublishResult(
        created=created,
        skipped=skipped,
        artifact_path=artifact_path,
        summary_ref=summary_ref,
    )
