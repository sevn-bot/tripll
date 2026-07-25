"""Typed LangGraph state for L1 outer and PR loops.

Each field has a single writer node; large values spill to disk when they
exceed :data:`FIELD_TOKEN_CAP` (~3k tokens per §5.2).

Exports:
    FIELD_TOKEN_CAP — per-field spill threshold in characters.
    L1OuterState — outer-loop graph state.
    spill_large_field — cap a string field and spill overflow to *run_dir*.
    merge_spilled_field — load a spilled field back into state.
"""

from __future__ import annotations

import hashlib
import json
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

FIELD_TOKEN_CAP = 12_000  # ~3k tokens at ~4 chars/token

__all__ = [
    "FIELD_TOKEN_CAP",
    "L1OuterState",
    "merge_spilled_field",
    "spill_large_field",
]


class L1OuterState(TypedDict, total=False):
    """Shared state for ``l1_outer`` and checkpoint recovery."""

    run_id: str
    thread_id: str
    step: str
    history: Annotated[list[str], add]
    turn: int
    graph_delta_hash: str
    turn_hashes: Annotated[list[str], add]
    exit_fired: int | None
    exit_name: str | None
    spill_refs: dict[str, str]
    notes: str
    paused: bool


def _spill_path(run_dir: Path, field: str, payload: str) -> Path:
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    spill_dir = run_dir / "loop-spill"
    spill_dir.mkdir(parents=True, exist_ok=True)
    path = spill_dir / f"{field}-{digest}.txt"
    path.write_text(payload, encoding="utf-8")
    return path


def spill_large_field(
    state: L1OuterState,
    *,
    field: str,
    value: str,
    run_dir: Path,
    cap: int = FIELD_TOKEN_CAP,
) -> L1OuterState:
    """Return state update with *value* capped; overflow written under *run_dir*.

    Args:
        state (L1OuterState): Current graph state (for spill ref bookkeeping).
        field (str): State field name being written.
        value (str): Raw field value from the node writer.
        run_dir (Path): Run directory for spill files.
        cap (int): Maximum inline characters before spill.

    Returns:
        L1OuterState: Partial update for the LangGraph node return value.
    """
    if len(value) <= cap:
        return cast("L1OuterState", {field: value})
    spill_path = _spill_path(run_dir, field, value)
    refs = dict(state.get("spill_refs") or {})
    refs[field] = str(spill_path)
    inline = value[:cap] + f"\n…[spilled {len(value) - cap} chars → {spill_path.name}]"
    return cast("L1OuterState", {"spill_refs": refs, field: inline})


def merge_spilled_field(state: L1OuterState, field: str) -> str:
    """Load inline + spilled content for *field* when a spill ref exists.

    Args:
        state (L1OuterState): Hydrated checkpoint state.
        field (str): Field to merge.

    Returns:
        str: Full field value (inline prefix + spill file tail when present).
    """
    inline = str(state.get(field) or "")
    ref = (state.get("spill_refs") or {}).get(field)
    if not ref:
        return inline
    path = Path(ref)
    if not path.is_file():
        return inline
    spilled = path.read_text(encoding="utf-8")
    if "[spilled " in inline:
        return spilled
    return inline + spilled


def graph_delta_hash(payload: dict[str, Any]) -> str:
    """Stable hash of a graph delta for no-progress detection (exit 5).

    Args:
        payload (dict[str, Any]): Serializable graph delta for one turn.

    Returns:
        str: Hex digest of the canonical JSON encoding.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
