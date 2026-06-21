"""Tests for ``role`` column parsing in the tripll execution graph.

Covers W1.1 of the test-creator-tests-first wave plan: the ``role`` field on
``WaveSpec`` and ``WaveNode`` (values ``impl`` / ``test-author``; default
``impl``; backward-compatible when absent).

Coverage matrix (W1.6):
  Unit:        WaveSpec defaults, parse_wave_plan_v1 with/without role column.
  Edge cases:  Missing column, empty cell, unknown role value.
  Error:       Invalid role value rejected by validation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.parse.wave_plan_v1 import (
    WaveSpec,
    build_graph_from_v1_dir,
    parse_wave_plan_v1,
    validate_wave_plan_v1,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Plan fixtures — Markdown tables with and without the role column
# ---------------------------------------------------------------------------

_PLAN_WITH_ROLE_COLUMN = """\
# Test Feature — with role

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `src/demo/` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets | model | role |
|---------|-------|------------|-------------|--------|----------------|-------|------|
| W0 | Design | | yes | M | make lint | | impl |
| W1 | Tests | W0 | | L | make lint | | test-author |
| W2 | Implement | W1 | | M | make check | | impl |
| Final | Gate | W2 | | L | make ci | | impl |
"""

_PLAN_WITHOUT_ROLE_COLUMN = """\
# Test Feature — no role

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `src/demo/` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets | model |
|---------|-------|------------|-------------|--------|----------------|-------|
| W0 | Design | | yes | M | make lint | |
| W1 | Implement | W0 | | M | make check | |
| Final | Gate | W1 | | L | make ci | |
"""

_PLAN_ROLE_EMPTY_CELLS = """\
# Test Feature — empty role cells

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `src/demo/` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets | model | role |
|---------|-------|------------|-------------|--------|----------------|-------|------|
| W0 | Design | | yes | M | make lint | | |
| W1 | Tests | W0 | | L | make lint | | test-author |
| W2 | Implement | W1 | | M | make check | | |
| Final | Gate | W2 | | L | make ci | | |
"""


def _write_plan(tmp_path: Path, text: str, name: str = "demo-wave-plan.md") -> Path:
    f = tmp_path / name
    f.write_text(text)
    return f


# ---------------------------------------------------------------------------
# W1.1 — Unit: WaveSpec default role
# ---------------------------------------------------------------------------


class TestWaveSpecRoleDefault:
    """WaveSpec dataclass default role value."""

    def test_default_role_is_impl(self) -> None:
        spec = WaveSpec(wave_id="W1")
        assert spec.role == "impl"

    def test_explicit_impl_role(self) -> None:
        spec = WaveSpec(wave_id="W1", role="impl")
        assert spec.role == "impl"

    def test_explicit_test_author_role(self) -> None:
        spec = WaveSpec(wave_id="W1", role="test-author")
        assert spec.role == "test-author"


# ---------------------------------------------------------------------------
# W1.1 — Unit: role column parsed from plan table
# ---------------------------------------------------------------------------


class TestRoleColumnParsing:
    """Parser reads the 8th column (role) from the execution graph table."""

    def test_role_present_parsed_correctly(self, tmp_path: Path) -> None:
        """When the role column is present, each wave gets its role value."""
        f = _write_plan(tmp_path, _PLAN_WITH_ROLE_COLUMN)
        plan = parse_wave_plan_v1(f)
        roles = {w.wave_id: w.role for w in plan.waves}
        assert roles["W0"] == "impl"
        assert roles["W1"] == "test-author"
        assert roles["W2"] == "impl"
        assert roles["Final"] == "impl"

    def test_role_absent_defaults_to_impl(self, tmp_path: Path) -> None:
        """When the role column is absent (7-col table), all waves default to impl."""
        f = _write_plan(tmp_path, _PLAN_WITHOUT_ROLE_COLUMN)
        plan = parse_wave_plan_v1(f)
        for wave in plan.waves:
            assert wave.role == "impl", f"{wave.wave_id} should default to impl"

    def test_empty_role_cell_defaults_to_impl(self, tmp_path: Path) -> None:
        """Empty role cells (8th col present but blank) default to impl."""
        f = _write_plan(tmp_path, _PLAN_ROLE_EMPTY_CELLS)
        plan = parse_wave_plan_v1(f)
        roles = {w.wave_id: w.role for w in plan.waves}
        assert roles["W0"] == "impl"
        assert roles["W1"] == "test-author"
        assert roles["W2"] == "impl"
        assert roles["Final"] == "impl"


# ---------------------------------------------------------------------------
# W1.1 — Integration: role propagates to WaveNode via build_graph_from_v1_dir
# ---------------------------------------------------------------------------


class TestRolePropagation:
    """Role column propagates from WaveSpec through to WaveNode in the RunGraph."""

    def test_graph_nodes_carry_role(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, _PLAN_WITH_ROLE_COLUMN)
        graph = build_graph_from_v1_dir(tmp_path, run_id="role-test")
        # WaveNode should carry a `role` attribute matching the parsed WaveSpec
        for node in graph.nodes.values():
            assert hasattr(node, "role"), f"WaveNode {node.node_id} missing role attr"

    def test_test_author_node_has_correct_role(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, _PLAN_WITH_ROLE_COLUMN)
        graph = build_graph_from_v1_dir(tmp_path, run_id="role-test")
        w1_node = next(n for n in graph.nodes.values() if n.wave_id == "W1")
        assert w1_node.role == "test-author"

    def test_impl_node_has_correct_role(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, _PLAN_WITH_ROLE_COLUMN)
        graph = build_graph_from_v1_dir(tmp_path, run_id="role-test")
        w2_node = next(n for n in graph.nodes.values() if n.wave_id == "W2")
        assert w2_node.role == "impl"


# ---------------------------------------------------------------------------
# W1.6 — Edge: backward compatibility (no role column = identical parse)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Plans without the role column parse identically to today."""

    def test_parse_without_role_unchanged(self, tmp_path: Path) -> None:
        """A 7-column plan still produces valid WaveSpec objects."""
        f = _write_plan(tmp_path, _PLAN_WITHOUT_ROLE_COLUMN)
        plan = parse_wave_plan_v1(f)
        assert len(plan.waves) == 3
        assert plan.waves[0].wave_id == "W0"
        assert plan.waves[0].review_gate is True
        assert plan.waves[1].wave_id == "W1"
        assert plan.waves[1].depends_on == ["W0"]

    def test_graph_build_without_role_succeeds(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, _PLAN_WITHOUT_ROLE_COLUMN)
        graph = build_graph_from_v1_dir(tmp_path, run_id="compat-test")
        assert len(graph.nodes) == 3
        assert graph.validate() == []

    def test_validation_passes_without_role(self, tmp_path: Path) -> None:
        f = _write_plan(tmp_path, _PLAN_WITHOUT_ROLE_COLUMN)
        assert validate_wave_plan_v1(f) == []


# ---------------------------------------------------------------------------
# W1.6 — Edge: invalid role value
# ---------------------------------------------------------------------------


class TestInvalidRoleValue:
    """Invalid role values should be caught by validation."""

    def test_unknown_role_value_flagged(self, tmp_path: Path) -> None:
        """A role value that is not 'impl' or 'test-author' is a validation error."""
        plan_text = _PLAN_WITH_ROLE_COLUMN.replace("| test-author |", "| reviewer |")
        f = _write_plan(tmp_path, plan_text)
        errors = validate_wave_plan_v1(f)
        assert any("role" in e.lower() for e in errors), (
            f"Expected a validation error mentioning 'role', got: {errors}"
        )
