"""Tests for ``TEST_PATHS`` forbidden-path derivation with node-level overlay.

Covers W1.2 of the test-creator-tests-first wave plan: ``derive_forbidden_paths``
adds ``TEST_PATHS`` (``["tests/", "wave-orchestrator/tests/"]``) to impl nodes'
forbidden sets, and excludes them from ``test-author`` nodes.

Coverage matrix (W1.6):
  Unit:        TEST_PATHS constant, paths_overlap with test dirs.
  Integration: derive_forbidden_paths node-level overlay wired to WaveNode.
  Edge cases:  Empty TEST_PATHS, overlapping TEST_PATHS with owned_paths,
               single-lane single-node graph.
  Error:       scope breach (impl node touches tests/).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.graph import (
    Lane,
    WaveNode,
    derive_forbidden_paths,
    paths_overlap,
)
from tripll.parse.wave_plan_v1 import build_graph_from_v1_dir

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Constants — the locked TEST_PATHS from design-note §9.2
# ---------------------------------------------------------------------------

EXPECTED_TEST_PATHS = ["tests/", "wave-orchestrator/tests/"]


# ---------------------------------------------------------------------------
# W1.2 — Unit: TEST_PATHS constant exists in graph module
# ---------------------------------------------------------------------------


class TestTestPathsConstant:
    """TEST_PATHS constant defined in graph.py per design-note §9.2."""

    def test_test_paths_exists(self) -> None:
        from tripll.graph import TEST_PATHS

        assert isinstance(TEST_PATHS, list)

    def test_test_paths_contains_expected_roots(self) -> None:
        from tripll.graph import TEST_PATHS

        for expected in EXPECTED_TEST_PATHS:
            assert expected in TEST_PATHS, f"{expected!r} missing from TEST_PATHS"


# ---------------------------------------------------------------------------
# W1.2 — Unit: paths_overlap recognises test directories
# ---------------------------------------------------------------------------


class TestPathsOverlapWithTestDirs:
    """Existing paths_overlap helper correctly detects test path nesting."""

    def test_tests_dir_overlaps_subpath(self) -> None:
        assert paths_overlap(["tests/"], ["tests/unit/test_foo.py"]) is True

    def test_tests_dir_exact_match(self) -> None:
        assert paths_overlap(["tests/"], ["tests/"]) is True

    def test_tests_dir_no_overlap_with_unrelated(self) -> None:
        assert paths_overlap(["tests/"], ["src/demo/"]) is False

    def test_wave_orchestrator_tests_overlap(self) -> None:
        assert (
            paths_overlap(["wave-orchestrator/tests/"], ["wave-orchestrator/tests/test_foo.py"])
            is True
        )


# ---------------------------------------------------------------------------
# W1.2 — Integration: derive_forbidden_paths adds TEST_PATHS for impl nodes
# ---------------------------------------------------------------------------


class TestDeriveForbiddenWithTestPaths:
    """derive_forbidden_paths node-level overlay for test-path forbidding."""

    def test_impl_node_forbids_test_paths(self) -> None:
        """An impl node should have TEST_PATHS in its forbidden set."""
        lanes = {"demo": Lane("demo", owned_paths=["src/demo/"])}
        impl_node = WaveNode(
            "demo:W2",
            "demo",
            "x.md",
            "W2",
            "demo",
            owned_paths=["src/demo/"],
            role="impl",
        )
        forbidden = derive_forbidden_paths("demo", lanes, node=impl_node)
        for test_path in EXPECTED_TEST_PATHS:
            assert test_path in forbidden, f"impl node should forbid {test_path!r}"

    def test_test_author_node_does_not_forbid_test_paths(self) -> None:
        """A test-author node should NOT have TEST_PATHS in its forbidden set."""
        lanes = {"demo": Lane("demo", owned_paths=["src/demo/"])}
        ta_node = WaveNode(
            "demo:W1",
            "demo",
            "x.md",
            "W1",
            "demo",
            owned_paths=["src/demo/"],
            role="test-author",
        )
        forbidden = derive_forbidden_paths("demo", lanes, node=ta_node)
        for test_path in EXPECTED_TEST_PATHS:
            assert test_path not in forbidden, f"test-author node should NOT forbid {test_path!r}"

    def test_impl_node_default_role_forbids_test_paths(self) -> None:
        """A node with default role (no explicit role) should forbid test paths."""
        lanes = {"demo": Lane("demo", owned_paths=["src/demo/"])}
        default_node = WaveNode(
            "demo:W3",
            "demo",
            "x.md",
            "W3",
            "demo",
            owned_paths=["src/demo/"],
        )
        # Default role should be "impl" — TEST_PATHS should be forbidden
        forbidden = derive_forbidden_paths("demo", lanes, node=default_node)
        for test_path in EXPECTED_TEST_PATHS:
            assert test_path in forbidden


# ---------------------------------------------------------------------------
# W1.2 — Integration: full graph build applies node-level overlay
# ---------------------------------------------------------------------------

_PLAN_WITH_ROLES = """\
# Test Paths Plan

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


class TestGraphBuildTestPathOverlay:
    """build_graph_from_v1_dir applies the node-level TEST_PATHS overlay."""

    def test_impl_nodes_have_test_paths_forbidden(self, tmp_path: Path) -> None:
        (tmp_path / "demo-wave-plan.md").write_text(_PLAN_WITH_ROLES)
        graph = build_graph_from_v1_dir(tmp_path, run_id="tp-test")
        impl_nodes = [n for n in graph.nodes.values() if n.wave_id in ("W0", "W2", "Final")]
        for node in impl_nodes:
            for test_path in EXPECTED_TEST_PATHS:
                assert test_path in node.forbidden_paths, (
                    f"impl node {node.node_id} should forbid {test_path!r}"
                )

    def test_asymmetry_impl_forbids_but_test_author_does_not(self, tmp_path: Path) -> None:
        """Impl nodes forbid TEST_PATHS while the test-author node does not."""
        (tmp_path / "demo-wave-plan.md").write_text(_PLAN_WITH_ROLES)
        graph = build_graph_from_v1_dir(tmp_path, run_id="tp-test")
        # impl W2 must have TEST_PATHS forbidden
        w2_node = next(n for n in graph.nodes.values() if n.wave_id == "W2")
        for test_path in EXPECTED_TEST_PATHS:
            assert test_path in w2_node.forbidden_paths, (
                f"impl node {w2_node.node_id} should forbid {test_path!r}"
            )
        # test-author W1 must NOT have TEST_PATHS forbidden
        w1_node = next(n for n in graph.nodes.values() if n.wave_id == "W1")
        for test_path in EXPECTED_TEST_PATHS:
            assert test_path not in w1_node.forbidden_paths, (
                f"test-author node should not forbid {test_path!r}"
            )


# ---------------------------------------------------------------------------
# W1.6 — Edge: empty TEST_PATHS
# ---------------------------------------------------------------------------


class TestEmptyTestPaths:
    """When TEST_PATHS is empty, no test-path overlay is applied."""

    def test_empty_test_paths_no_extra_forbidden(self) -> None:
        """If TEST_PATHS were empty, impl nodes should not get test path entries."""
        from tripll import graph as graph_mod

        original = getattr(graph_mod, "TEST_PATHS", None)
        try:
            graph_mod.TEST_PATHS = []  # type: ignore[attr-defined]
            lanes = {"demo": Lane("demo", owned_paths=["src/demo/"])}
            impl_node = WaveNode(
                "demo:W2",
                "demo",
                "x.md",
                "W2",
                "demo",
                owned_paths=["src/demo/"],
                role="impl",
            )
            forbidden = derive_forbidden_paths("demo", lanes, node=impl_node)
            for test_path in EXPECTED_TEST_PATHS:
                assert test_path not in forbidden
        finally:
            if original is not None:
                graph_mod.TEST_PATHS = original  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# W1.6 — Edge: TEST_PATHS overlap with owned_paths
# ---------------------------------------------------------------------------


class TestTestPathsOverlapWithOwned:
    """When owned_paths overlap TEST_PATHS, paths_overlap semantics apply."""

    def test_owned_tests_dir_not_double_forbidden_for_test_author(self) -> None:
        """A test-author whose owned_paths includes tests/ should not be forbidden."""
        lanes = {"demo": Lane("demo", owned_paths=["src/demo/", "tests/"])}
        ta_node = WaveNode(
            "demo:W1",
            "demo",
            "x.md",
            "W1",
            "demo",
            owned_paths=["src/demo/", "tests/"],
            role="test-author",
        )
        forbidden = derive_forbidden_paths("demo", lanes, node=ta_node)
        assert "tests/" not in forbidden

    def test_impl_node_skips_test_root_forbidden_when_owned(self) -> None:
        """An impl node that owns paths under tests/ should not forbid tests/."""
        lanes = {"demo": Lane("demo", owned_paths=["src/demo/", "tests/channels/test_foo.py"])}
        impl_node = WaveNode(
            "demo:W2",
            "demo",
            "x.md",
            "W2",
            "demo",
            owned_paths=["src/demo/", "tests/channels/test_foo.py"],
            role="impl",
        )
        forbidden = derive_forbidden_paths("demo", lanes, node=impl_node)
        assert "tests/" not in forbidden


# ---------------------------------------------------------------------------
# W1.6 — Existing derive_forbidden_paths still works (regression guard)
# ---------------------------------------------------------------------------


class TestDeriveForbiddenRegressionGuard:
    """Existing lane-level derive_forbidden_paths behaviour is unchanged."""

    def test_other_lane_paths_still_forbidden(self) -> None:
        lanes = {
            "a": Lane("a", owned_paths=["src/a/"]),
            "b": Lane("b", owned_paths=["src/b/"]),
        }
        forbidden = derive_forbidden_paths("a", lanes)
        assert "src/b/" in forbidden

    def test_cw_hotspots_still_forbidden(self, legacy_cw_hotspots: None) -> None:
        lanes = {"a": Lane("a", owned_paths=["src/a/"])}
        forbidden = derive_forbidden_paths("a", lanes)
        assert "src/sevn/gateway/agent_turn.py" in forbidden

    def test_cw_owner_exclusion_still_works(self, legacy_cw_hotspots: None) -> None:
        lanes = {"a": Lane("a", owned_paths=["src/a/"])}
        forbidden = derive_forbidden_paths("a", lanes, cw_owners={"CW-1": "a"})
        assert "src/sevn/gateway/agent_turn.py" not in forbidden
