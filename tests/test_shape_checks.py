"""Shape checks — fake edges, stop rule, one-writer (W1.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import require_module

_XFAIL = pytest.mark.xfail(reason="green after W4: shape_checks", strict=False)

_FIXTURES = Path(__file__).parent / "fixtures" / "plans"


@_XFAIL
def test_reasonless_depends_on_dropped_and_reported() -> None:
    check_fake_edges = require_module("tripll.plan.shape_checks", attr="check_fake_edges")
    report = check_fake_edges(
        [
            {
                "id": "W2",
                "depends_on": [{"wave": "W1"}],  # missing reason
            }
        ]
    )
    assert report.dropped
    assert report.parallelised_waves >= 2


@_XFAIL
def test_parallel_waves_same_file_fail_compile() -> None:
    compile_plan = require_module("tripll.plan.shape_checks", attr="compile_plan")
    with pytest.raises(ValueError, match=r"same file|one-writer|writer"):
        compile_plan(
            {
                "waves": [
                    {"id": "W1", "targets": ["src/a.py"]},
                    {"id": "W2", "targets": ["src/a.py"]},
                ],
                "depends_on": [],
            }
        )


@_XFAIL
def test_parallel_waves_calls_path_refused() -> None:
    check_stop_rule = require_module("tripll.plan.shape_checks", attr="check_stop_rule")
    with pytest.raises(ValueError, match=r"sequential|stop|CALLS"):
        check_stop_rule(
            waves=[
                {"id": "W1", "targets": ["src/a.py"]},
                {"id": "W2", "targets": ["src/b.py"]},
            ],
            code_graph={"calls_path_len": 1, "parallel": True},
        )


@_XFAIL
def test_cross_cutting_refactor_refused() -> None:
    check_stop_rule = require_module("tripll.plan.shape_checks", attr="check_stop_rule")
    with pytest.raises(ValueError, match=r"cross-cutting|refactor|sequential"):
        check_stop_rule(
            waves=[
                {"id": "W1", "targets": ["src/a.py", "src/b.py", "src/c.py"]},
                {"id": "W2", "targets": ["src/d.py", "src/e.py", "src/f.py"]},
            ],
            requirement_span={"modules": 6, "parallel": True},
        )


@_XFAIL
def test_cw_hotspots_reproduced_by_derivation() -> None:
    from tripll.graph import CW_HOTSPOTS

    derive_one_writer_map = require_module("tripll.plan.shape_checks", attr="derive_one_writer_map")
    derived = derive_one_writer_map(_FIXTURES)
    assert set(derived.keys()) == set(CW_HOTSPOTS.keys())
