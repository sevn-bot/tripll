"""Markdown wave-section helpers for wave-file bodies.

Exports:
    section_bullets — task bullet lines under one ``## Wave`` heading.
    wave_heading_tasks — joined task bullets for one wave id.
    wave_complete — True when all task bullets under a wave are checked.
    wave_heading_map — wave id → heading regex match.
"""

from __future__ import annotations

import re

__all__: list[str] = [
    "section_bullets",
    "wave_complete",
    "wave_heading_map",
    "wave_heading_tasks",
]

WAVE_HEADING_RE = re.compile(r"^##\s+Wave\s+(\S+)\s+(?:—|-)", re.MULTILINE)
TASK_BULLET_RE = re.compile(r"^-\s+\[[ xX]\]")
_CHECKED_BULLET_RE = re.compile(r"^-\s+\[[xX]\]")


def section_bullets(text: str, heading_match: re.Match[str]) -> list[str]:
    """Return task bullet lines under one ``## Wave`` heading match.

    Args:
        text (str): Full wave-file markdown body.
        heading_match (re.Match[str]): Match from ``WAVE_HEADING_RE``.

    Returns:
        list[str]: Lines matching the task-bullet pattern.

    Examples:
        >>> import re
        >>> body = "## Wave W0 — t\\n- [ ] task\\n"
        >>> m = WAVE_HEADING_RE.search(body)
        >>> section_bullets(body, m)
        ['- [ ] task']
    """
    start = heading_match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    section = text[start:end]
    return [line for line in section.splitlines() if TASK_BULLET_RE.match(line)]


def wave_heading_map(text: str) -> dict[str, re.Match[str]]:
    """Return wave id → heading match for each ``## Wave`` section.

    Args:
        text (str): Full wave-file markdown body.

    Returns:
        dict[str, re.Match[str]]: Map of wave id to heading match.

    Examples:
        >>> wave_heading_map("## Wave W0 — t\\n- [ ] x\\n")["W0"].group(1)
        'W0'
    """
    headings: dict[str, re.Match[str]] = {}
    for match in WAVE_HEADING_RE.finditer(text):
        hid = match.group(1).strip()
        headings[hid] = match
    return headings


def wave_heading_tasks(text: str, wave_id: str) -> str:
    """Return joined task bullets for *wave_id*, or a placeholder when missing.

    Args:
        text (str): Full wave-file markdown body.
        wave_id (str): Target wave id.

    Returns:
        str: Newline-joined bullets or ``(no tasks)``.

    Examples:
        >>> wave_heading_tasks("## Wave W0 — t\\n- [ ] a\\n", "W0")
        '- [ ] a'
    """
    for match in WAVE_HEADING_RE.finditer(text):
        if match.group(1).strip() == wave_id:
            bullets = section_bullets(text, match)
            return "\n".join(bullets) if bullets else "(no tasks)"
    return "(no tasks)"


def wave_complete(text: str, wave_id: str) -> bool:
    """Return True when every task bullet under *wave_id* is checked.

    Args:
        text (str): Full wave-file markdown body.
        wave_id (str): Target wave id.

    Returns:
        bool: True when all bullets are checked or the section has no bullets.

    Examples:
        >>> wave_complete("## Wave W0 — t\\n- [x] done\\n", "W0")
        True
    """
    for match in WAVE_HEADING_RE.finditer(text):
        if match.group(1).strip() != wave_id:
            continue
        bullets = section_bullets(text, match)
        if not bullets:
            return True
        return all(_CHECKED_BULLET_RE.match(line) for line in bullets)
    return True
