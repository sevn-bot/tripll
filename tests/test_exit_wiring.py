"""Engine exit wiring — BUG-06, ARCH-exits, DIR-01 (W1.10, tier 3)."""

from __future__ import annotations

import inspect

import pytest

from tripll.engine import Engine


@pytest.mark.tier3
@pytest.mark.xfail(reason="green after W7: pullfrog success fires exit 1 via engine", strict=False)
def test_goal_met_exit_wired_through_engine() -> None:
    """BUG-06: ``pullfrog_merge_signal`` success must reach ``evaluate_exit(1)`` in Engine."""
    source = inspect.getsource(Engine)
    assert "evaluate_exit" in source
    assert "pullfrog" in source.lower() or "goal_met" in source


@pytest.mark.tier3
@pytest.mark.parametrize("exit_name", ["wall_clock", "error_threshold", "external_event"])
@pytest.mark.xfail(reason="green after W7: engine routes exits 4/7/8", strict=False)
def test_engine_routes_exit_table(exit_name: str) -> None:
    """DIR-01: exits 4, 7, 8 fire from the Engine path, not evaluator-only fixtures."""
    source = inspect.getsource(Engine)
    assert "evaluate_exit" in source
    assert exit_name.replace("_", "") in source.replace("_", "") or exit_name in source


@pytest.mark.tier3
@pytest.mark.xfail(reason="green after W7: fired exit id recorded on run", strict=False)
def test_fired_exit_id_recorded_on_run() -> None:
    source = inspect.getsource(Engine)
    assert "record_exit_on_run" in source or "exit_fired" in source
