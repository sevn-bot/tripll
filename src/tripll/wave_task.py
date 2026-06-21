"""tripll.wave_task — wave-plan checklist parsing and active-task inference (D6).

Parses staged wave-section bullets (``- [ ] **Wn.m** …``) and infers which
task is active from optional ``last_action`` text or running-phase fallback.

Exports:
    WaveTaskBullet — one checklist row.
    WaveTaskResult — parser output with inferred active task id.
    parse_wave_tasks — extract bullets from staged plan markdown.
    infer_active_task — mark active bullet and return inferred task id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BULLET_RE = re.compile(
    r"^-\s+\[(?P<checked>[ xX])\]\s+\*\*(?P<id>[A-Za-z][A-Za-z0-9.-]*)\*\*\s*(?P<text>.*)$",
    re.MULTILINE,
)
_ACTION_WORD_RE = re.compile(r"[a-z0-9]{4,}")


@dataclass(frozen=True, slots=True)
class WaveTaskBullet:
    """One wave-plan checklist bullet.

    Args:
        id (str): Task id (e.g. ``W0.1``, ``W1``).
        text (str): Remainder of the bullet line after the bold id.
        checked (bool): True when the markdown checkbox is ``[x]``.
        active (bool): True when this bullet is the inferred active task.
    """

    id: str
    text: str
    checked: bool
    active: bool


@dataclass(frozen=True, slots=True)
class WaveTaskResult:
    """Output of :func:`infer_active_task`.

    Args:
        bullets (list[WaveTaskBullet]): Parsed checklist rows in document order.
        inferred_task_id (str | None): Active task id, or ``None`` when unknown.
    """

    bullets: list[WaveTaskBullet]
    inferred_task_id: str | None


def parse_wave_tasks(plan_markdown: str) -> list[WaveTaskBullet]:
    """Parse ``- [ ] **Wn.m** …`` bullets from staged plan markdown (D6).

    Args:
        plan_markdown (str): Staged wave-plan slice text.

    Returns:
        list[WaveTaskBullet]: Bullets in document order (``active=False``).

    Examples:
        >>> parse_wave_tasks("- [ ] **W1** Do work")[0].id
        'W1'
    """
    bullets: list[WaveTaskBullet] = []
    for match in _BULLET_RE.finditer(plan_markdown):
        checked = match.group("checked").lower() == "x"
        bullets.append(
            WaveTaskBullet(
                id=match.group("id"),
                text=match.group("text").strip(),
                checked=checked,
                active=False,
            )
        )
    return bullets


def infer_active_task(
    plan_markdown: str,
    *,
    last_action: str | None = None,
    phase: str | None = None,
) -> WaveTaskResult:
    """Infer the active checklist bullet from plan text and optional context (D6).

    When *last_action* is set, the bullet whose text shares the longest
    case-insensitive substring with *last_action* wins.  When no match and
    *phase* is ``running``, the first unchecked bullet is active.  Otherwise
    no bullet is marked active.

    Args:
        plan_markdown (str): Staged wave-plan slice text.
        last_action (str | None): Latest operator summary from the ledger/SSE.
        phase (str | None): Current wave phase (used for running fallback).

    Returns:
        WaveTaskResult: Bullets with at most one ``active=True`` row.

    Examples:
        >>> md = "- [ ] **W0.1** alpha\\n- [ ] **W0.2** beta ledger"
        >>> infer_active_task(md, last_action="beta ledger", phase="running").inferred_task_id
        'W0.2'
    """
    base = parse_wave_tasks(plan_markdown)
    if not base:
        return WaveTaskResult(bullets=[], inferred_task_id=None)

    active_id: str | None = None
    action = (last_action or "").strip().lower()

    if action:
        words = sorted(set(_ACTION_WORD_RE.findall(action)), key=len, reverse=True)
        for word in words:
            for b in base:
                if word in b.text.lower():
                    active_id = b.id
                    break
            if active_id is not None:
                break

    if active_id is None and phase == "running":
        for b in base:
            if not b.checked:
                active_id = b.id
                break

    marked = [
        WaveTaskBullet(id=b.id, text=b.text, checked=b.checked, active=(b.id == active_id))
        for b in base
    ]
    return WaveTaskResult(bullets=marked, inferred_task_id=active_id)
