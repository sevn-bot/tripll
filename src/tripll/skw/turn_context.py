"""Turn context helpers for the review/generate loop (Fix-W2).

Snapshot wave plans at turn open, load review verdict JSON, and diff new files
against the turn-start baseline.

Exports:
    snapshot_waves — list ``*-wave-plan.md`` paths relative to kit root.
    load_verdict — read ``waves/<slug>.review-result.json`` verdict field.
    diff_new_waves — paths in ``after`` not present in ``before``.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__: list[str] = ["diff_new_waves", "load_verdict", "snapshot_waves"]


def snapshot_waves(kit_root: Path) -> list[str]:
    """List wave plan markdown files under ``waves/`` (sorted, kit-relative).

    Args:
        kit_root (Path): Kit root directory.

    Returns:
        list[str]: Sorted relative paths matching ``waves/*-wave-plan.md``.

    Examples:
        >>> snapshot_waves(Path("/tmp/empty-kit"))
        []
    """
    waves_dir = kit_root / "waves"
    if not waves_dir.is_dir():
        return []
    return sorted(str(p.relative_to(kit_root)) for p in waves_dir.glob("*-wave-plan.md"))


def load_verdict(kit_root: Path, slug: str) -> str:
    """Load the review verdict string from ``waves/<slug>.review-result.json``.

    Args:
        kit_root (Path): Kit root directory.
        slug (str): Pipeline slug (basename of review-result file).

    Returns:
        str: Non-empty verdict (``pass`` or ``changes_required``).

    Raises:
        FileNotFoundError: When the review-result file is missing.
        ValueError: When the verdict field is missing or empty.

    Examples:
        >>> load_verdict(Path("/nonexistent"), "missing")  # doctest: +SKIP
        'pass'
    """
    path = kit_root / "waves" / f"{slug}.review-result.json"
    if not path.is_file():
        msg = f"missing review-result file: {path}"
        raise FileNotFoundError(msg)
    payload = json.loads(path.read_text(encoding="utf-8"))
    verdict = payload.get("verdict", "")
    if not isinstance(verdict, str) or not verdict.strip():
        msg = "verdict empty or missing in review-result JSON"
        raise ValueError(msg)
    return verdict


def diff_new_waves(
    before: list[str],
    after: list[str],
    exclude: str | None = None,
) -> list[str]:
    """Return wave plan paths present in ``after`` but not in ``before``.

    Args:
        before (list[str]): Snapshot at turn open.
        after (list[str]): Current wave plan listing.
        exclude (str | None): Optional path to omit (absolute or kit-relative).

    Returns:
        list[str]: New wave plan paths (sorted).

    Examples:
        >>> diff_new_waves(["waves/a-wave-plan.md"], ["waves/a-wave-plan.md", "waves/b-wave-plan.md"])
        ['waves/b-wave-plan.md']
    """
    before_set = set(before)
    exclude_rel = _normalize_exclude(exclude)
    return sorted(p for p in after if p not in before_set and p != exclude_rel)


def _normalize_exclude(exclude: str | None) -> str | None:
    if not exclude:
        return None
    path = Path(exclude)
    parts = path.parts
    if "waves" in parts:
        idx = parts.index("waves")
        return str(Path(*parts[idx:]))
    return exclude
