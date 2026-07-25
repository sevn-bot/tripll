"""LangGraph pipeline shared state (Wave W2).

W0 design lock — ``PipelineState`` is the typed graph state passed between nodes.

Required after ``validate`` (turn open):

- ``wave_file`` — absolute path to active wave markdown file
- ``wave_order`` — topo-sorted wave ids from compiled pipeline states
- ``waves_before`` — relative wave plan paths snapshotted at turn open

Optional / populated by later nodes (checkpoint resume may supply any subset):

- ``turn`` — review/generate loop counter (default 1; ``max_turns`` cap)
- ``current_wave`` — id of the wave under execution
- ``verdict`` — last review verdict (``pass`` | ``changes_required``); cleared on validate_new
- ``new_wave_files`` — relative paths written by post-review generator
- ``history`` — append-only log of completed node actions

Exports:
    PipelineState — TypedDict graph state.
"""

from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Shared LangGraph state for the SKW pipeline graph."""

    wave_file: str
    wave_order: list[str]
    current_wave: str
    turn: int
    waves_before: list[str]
    verdict: str
    new_wave_files: list[str]
    history: list[dict[str, Any]]
