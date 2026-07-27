"""Next-step hint from wave-plan checkbox state (W13.8).

Exports:
    compute_next_step — suggest the next tripll command for a plan file.
"""

from __future__ import annotations

from pathlib import Path

from tripll.skw.markdown_sections import wave_complete, wave_heading_map

__all__: list[str] = ["compute_next_step"]


def compute_next_step(*, plan_path: Path | str, wave_id: str | None = None) -> str:
    """Return the next tripll command for *plan_path*.

    Scans ``## Wave`` checklist sections via :mod:`tripll.skw.markdown_sections`
    and suggests ``tripll validate-plan`` before first dispatch, then
    ``tripll run`` while waves remain incomplete.

    Args:
        plan_path (Path | str): Path to a wave-plan markdown file.
        wave_id (str | None): When set, advance from this wave id.

    Returns:
        str: Suggested command or ``PASS`` when all waves are checked.

    Raises:
        ValueError: When *wave_id* is not present in the plan.

    Examples:
        >>> from pathlib import Path
        >>> p = Path("ignorelocal/tripll-l1-remediation-wave-plan.md")
        >>> hint = compute_next_step(plan_path=p) if p.is_file() else "tripll doctor"
        >>> isinstance(hint, str)
        True
    """
    path = Path(plan_path).resolve()
    text = path.read_text(encoding="utf-8")
    headings = wave_heading_map(text)
    order = list(headings.keys())

    if wave_id is not None:
        if wave_id not in order:
            msg = f"unknown wave id {wave_id!r}"
            raise ValueError(msg)
        start_idx = order.index(wave_id) + 1
        candidates = order[start_idx:]
    else:
        candidates = order

    for wid in candidates:
        if not wave_complete(text, wid):
            rel = path
            try:
                from tripll.repo_root import resolve_repo_root

                rel = path.relative_to(resolve_repo_root())
            except ValueError:
                rel = path
            return f"tripll validate-plan {rel} && tripll run --plan {rel}  # wave {wid} pending"

    if order and all(wave_complete(text, wid) for wid in order):
        return "PASS"

    return f"tripll validate-plan {path.name}"
