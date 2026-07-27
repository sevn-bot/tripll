"""Observability configurator contract — OBS-01, TRACE-04 (W1.5).

Distinct from ``tests/test_tracing.py`` (P3 spine). This module covers
``tripll.obs.configure_observability`` only.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tripll.obs import configure_observability, get_tracing_config
from tripll.tracing.sink import TraceEvent
from tripll.tracing.sinks import JsonlTraceSink


@pytest.fixture(autouse=True)
def _reset_obs_module() -> None:
    import tripll.obs as obs_mod

    obs_mod._configured = False
    yield
    obs_mod._configured = False


@pytest.mark.tier1
def test_configure_observability_never_raises_on_logfire_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OBS-01: logfire import failure must not break callers."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setenv("TRIPLL_TRACE", "1")
    with patch.dict(sys.modules, {"logfire": None}):
        assert configure_observability() in (False, True)


@pytest.mark.tier1
def test_httpx_instrumentation_does_not_capture_all() -> None:
    """OBS-01: enabled httpx instrumentation must not capture headers/bodies."""
    import inspect

    import tripll.obs as obs_mod

    source = inspect.getsource(obs_mod.configure_observability)
    assert "instrument_httpx(capture_all=False)" in source


@pytest.mark.tier1
def test_no_exporter_without_logfire_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TRACE-04: without ``LOGFIRE_TOKEN`` there is no remote exporter."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setenv("TRIPLL_TRACE", "1")
    configured = configure_observability()
    cfg = get_tracing_config()
    assert configured is False or not cfg.wants_logfire


@pytest.mark.tier1
def test_local_sinks_still_write_without_logfire_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TRACE-04: local sinks write even when no exporter is configured."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setenv("TRIPLL_TRACE", "1")
    configure_observability(plan={"tracing": {"sinks": ["jsonl"]}})
    sink = JsonlTraceSink(tmp_path / "trace.jsonl")
    sink.emit(
        TraceEvent(
            kind="test.span",
            span_id="s1",
            parent_span_id=None,
            run_id="r1",
            node_id="p:W1",
            attempt_id=None,
            ts_start_ns=1,
            ts_end_ns=2,
            status="closed",
            attrs={"phase": "test"},
        )
    )
    sink.flush()
    assert (tmp_path / "trace.jsonl").stat().st_size > 0


@pytest.mark.tier1
def test_cli_starts_when_logfire_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """OBS-01: CLI import path survives missing logfire."""
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    with patch.dict(sys.modules, {"logfire": None}):
        cli = importlib.import_module("tripll.cli")
        assert hasattr(cli, "main")


@pytest.mark.tier1
def test_configurator_distinct_from_tracing_spine() -> None:
    """Configurator lives in obs.py; spine lives in tracing/ — no duplicate ownership."""
    import tripll.obs as obs_mod
    import tripll.tracing as tracing_mod

    assert obs_mod.configure_observability.__module__ == "tripll.obs"
    assert hasattr(tracing_mod, "init_run_tracing")
    assert not hasattr(tracing_mod, "configure_observability")
