"""Tests for tripll.parse.wave_plan_v1 — execution graph + deterministic manifest."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.parse import build_graph_from_dir
from tripll.parse.manifest import write_parallel_wave_manifest
from tripll.parse.wave_plan_v1 import (
    build_graph_from_v1_dir,
    parse_wave_plan_v1,
    validate_wave_plan_v1,
)

if TYPE_CHECKING:
    from pathlib import Path

_V1_PLAN = """# Demo Feature

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `src/sevn/demo/module.py` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets |
|---------|-------|------------|-------------|--------|----------------|
| W0 | Design | | yes | M | make lint |
| W1 | Implement | W0 | | M | make ci-affected |
| Final | Gate | W1 | | L | make ci |

## Wave W0 — review gate

- [ ] **W0.1** Review gate: confirm scope.
"""


def _write_v1(tmp_path: Path) -> Path:
    f = tmp_path / "demo-feature-wave-plan.md"
    f.write_text(_V1_PLAN)
    return f


def test_validate_v1_ok(tmp_path: Path) -> None:
    f = _write_v1(tmp_path)
    assert validate_wave_plan_v1(f) == []


def test_validate_v1_missing_section(tmp_path: Path) -> None:
    f = tmp_path / "x-wave-plan.md"
    f.write_text("# X\n\n## Files in scope\n\n| S | P |\n|--|--|\n| a | `src/a/` |\n")
    errs = validate_wave_plan_v1(f)
    assert any("execution graph" in e for e in errs)


def test_build_graph_v1_serial_batches(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    graph = build_graph_from_v1_dir(tmp_path, run_id="v1-test")
    assert len(graph.nodes) == 3
    assert graph.batch_order()[0] == "Pre-0"
    assert graph.batch_order()[-1] == "Final"
    assert "demo-feature:W0" in graph.nodes
    assert graph.nodes["demo-feature:W1"].depends_on == ["demo-feature:W0"]


def test_manifest_deterministic(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    graph = build_graph_from_dir(tmp_path, run_id="seed-run")
    out = tmp_path / "parallel-wave.md"
    t1 = write_parallel_wave_manifest(graph, out)
    t2 = write_parallel_wave_manifest(graph, out)
    assert t1 == t2
    assert "tripll v1" in t1
    assert "Phase W0" not in t1  # batch ids not wave ids in phase header


def test_build_graph_from_dir_prefers_v1(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    graph = build_graph_from_dir(tmp_path, run_id="r")
    assert len(graph.nodes) == 3


def test_parse_execution_graph_rows(tmp_path: Path) -> None:
    f = _write_v1(tmp_path)
    plan = parse_wave_plan_v1(f)
    assert plan.has_execution_graph
    assert [w.wave_id for w in plan.waves] == ["W0", "W1", "Final"]
