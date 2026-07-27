"""Tests for tripll.parse.plan_files — Mode B manifest generation + round-trip."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.parse import build_graph_from_dir, detect_mode
from tripll.parse.plan_files import (
    build_graph_mode_b,
    cluster_lanes,
    parse_plan_file,
    read_review_hints,
)

if TYPE_CHECKING:
    from pathlib import Path

_PLAN_A = """# Provider Telemetry

**Status:** pending — effort: M

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Adapters | `src/sevn/agent/adapters/` |

## Wave W0 — gate
"""

_PLAN_B = """# Self Improve Proposer

**Status:** pending — effort: L

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Jobs | `src/sevn/self_improve/` |
"""

_PLAN_C = """# Trajectory Ingest

depends on: #2

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Jobs | `src/sevn/self_improve/jobs/store.py` |
"""


def _seed(tmp_path: Path) -> Path:
    (tmp_path / "provider-telemetry-wave-plan.md").write_text(_PLAN_A)
    (tmp_path / "self-improve-proposer-wave-plan.md").write_text(_PLAN_B)
    (tmp_path / "trajectory-ingest-wave-plan.md").write_text(_PLAN_C)
    return tmp_path


def test_parse_plan_file_extracts_owned_paths(tmp_path: Path) -> None:
    f = tmp_path / "x-wave-plan.md"
    f.write_text(_PLAN_A)
    meta = parse_plan_file(f)
    assert meta.plan_id == "x"
    assert "src/sevn/agent/adapters/" in meta.owned_paths


def test_cluster_lanes_groups_overlapping(tmp_path: Path) -> None:
    _seed(tmp_path)
    plans = [
        parse_plan_file(tmp_path / "provider-telemetry-wave-plan.md"),
        parse_plan_file(tmp_path / "self-improve-proposer-wave-plan.md"),
        parse_plan_file(tmp_path / "trajectory-ingest-wave-plan.md"),
    ]
    lanes = cluster_lanes(plans)
    # B and C overlap on src/sevn/self_improve → one lane; A is separate.
    assert len(lanes) == 2


def test_detect_mode_b(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert detect_mode(tmp_path) == "B"


def test_build_graph_mode_b_generates_manifest(tmp_path: Path) -> None:
    _seed(tmp_path)
    graph = build_graph_mode_b(tmp_path, run_id="mode-b-test")
    assert graph.source_mode == "B"
    assert (tmp_path / "parallel-wave.md").exists()
    assert len(graph.lanes) == 2
    assert graph.batch_order()[0] == "Pre-0"
    assert graph.batch_order()[-1] == "Final"
    assert graph.validate() == []


def test_build_graph_from_dir_dispatches_to_mode_b(tmp_path: Path) -> None:
    _seed(tmp_path)
    graph = build_graph_from_dir(tmp_path, run_id="r")
    # After manifest generation, detect_mode would flip to A; build_graph_mode_b
    # is invoked here directly via detect_mode (no parallel-wave.md yet).
    assert graph.source_mode == "B"


def test_read_review_hints_absent(tmp_path: Path) -> None:
    assert read_review_hints(tmp_path) == {}


def test_review_hints_cw_owner_excludes_hotspot(tmp_path: Path, legacy_cw_hotspots: None) -> None:
    _seed(tmp_path)
    # First pass to discover a lane id.
    graph = build_graph_mode_b(tmp_path, run_id="r1")
    owner_lane = next(iter(graph.lanes))
    (tmp_path / "review-hints.yaml").write_text(f"cw_owners:\n  CW-1: {owner_lane}\n")

    graph2 = build_graph_mode_b(tmp_path, run_id="r2")
    owner_node = graph2.nodes[f"{owner_lane}:all-waves"]
    assert "src/sevn/gateway/agent_turn.py" not in owner_node.forbidden_paths

    other_lane = next(lid for lid in graph2.lanes if lid != owner_lane)
    other_node = graph2.nodes[f"{other_lane}:all-waves"]
    assert "src/sevn/gateway/agent_turn.py" in other_node.forbidden_paths


_TELEGRAM_W0_PLAN = """# Telegram Rich

**Status:** Draft — effort: M

## Decisions baked into this plan

| # | Topic | Decision |
|---|-------|----------|
| D1 | Rich payload | Build structured tree (confirm at W0 review gate). |

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Telegram | `src/sevn/channels/telegram.py` |

## Wave W0 — design (review gate)

- [ ] **W0.7** **Review gate:** operator confirms D1 before R2.
"""


_TELEGRAM_FILES_ROW = (
    "| Telegram adapter (send/edit/capability/updates) | "
    "`src/sevn/channels/telegram.py` (`_send_text`, `_edit_message_text_body`, "
    "`edit_message_text`, `_dispatch_update`, `_poll`/`allowed_updates`, "
    "`getMe`/`_api`) |\n"
)


def test_parse_files_in_scope_ignores_paren_symbols(tmp_path: Path) -> None:
    text = (
        "# Telegram Rich\n\n## Files in scope\n\n| Subsystem | Paths |\n"
        "|-----------|-------|\n" + _TELEGRAM_FILES_ROW
    )
    f = tmp_path / "telegram-rich-inline-miniapps-wave-plan.md"
    f.write_text(text)
    meta = parse_plan_file(f)
    assert meta.owned_paths == ["src/sevn/channels/telegram.py"]


def test_mode_b_single_plan_uses_plan_pre0_not_dev_eval(tmp_path: Path) -> None:
    (tmp_path / "telegram-rich-inline-miniapps-wave-plan.md").write_text(_TELEGRAM_W0_PLAN)
    graph = build_graph_mode_b(tmp_path, run_id="tg-test")
    assert graph.batch_order() == ["Pre-0", "A", "Final"]
    assert len(graph.pre0_gates) >= 1
    assert "Provider attr contract" not in graph.pre0_gates[0]
    assert any("D1" in g or "W0" in g for g in graph.pre0_gates)
    assert graph.batches[1].lanes == ["telegram-rich-inline-miniapps"]


def test_detect_mode_stays_b_for_generated_manifest(tmp_path: Path) -> None:
    _seed(tmp_path)
    build_graph_mode_b(tmp_path, run_id="r")
    assert detect_mode(tmp_path) == "B"
