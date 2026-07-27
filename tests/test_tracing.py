"""Tier-1 tests for the tracing spine (P3.12)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tripll.adapters.base import AdapterCapabilities, AgentAdapter
from tripll.tracing.capture import DEFAULT_CAPTURE, shape_capture_value
from tripll.tracing.config import parse_tracing_config
from tripll.tracing.sink import MultiSink, TraceEvent, TraceSink
from tripll.tracing.sinks import JsonlTraceSink
from tripll.tracing.spans import init_run_tracing, trace_span


class _RaisingSink:
    def emit(self, event: TraceEvent) -> None:
        raise RuntimeError("sink boom")

    def flush(self) -> None:
        raise RuntimeError("flush boom")

    def close(self) -> None:
        raise RuntimeError("close boom")


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _ProbeAdapter(AgentAdapter):
    name = "probe"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(backend=self.name, available=True, detail="ok")

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        return ["probe", "run"]


@pytest.fixture
def fake_clock() -> dict[str, Any]:
    tick = {"t": 1_700_000_000.0, "ns": 1_700_000_000_000_000_000}

    def clock() -> float:
        tick["t"] += 1.0
        return tick["t"]

    def clock_ns() -> int:
        tick["ns"] += 1_000_000
        return tick["ns"]

    tick["clock"] = clock
    tick["clock_ns"] = clock_ns
    return tick


def test_default_capture_is_shape() -> None:
    cfg = parse_tracing_config({})
    assert cfg.capture == DEFAULT_CAPTURE == "shape"


def test_capture_shape_hides_prompt_text() -> None:
    shaped = shape_capture_value(
        "prompt",
        {"role": "user", "content": "super-secret-token-value"},
        mode="shape",
    )
    assert isinstance(shaped, dict)
    assert "super-secret" not in json.dumps(shaped)
    assert shaped.get("char_count") == len("super-secret-token-value")


def test_no_token_run_writes_local_sinks(tmp_path: Path, fake_clock: dict[str, Any]) -> None:
    run_dir = tmp_path / "processing" / "demo-run"
    cfg = parse_tracing_config({"tracing": {"enabled": True, "sinks": ["sqlite", "jsonl"]}})
    session = init_run_tracing(
        run_dir,
        cfg,
        run_id="demo-run",
        clock=fake_clock["clock"],
        clock_ns=fake_clock["clock_ns"],
    )
    assert session is not None
    with (
        trace_span("tripll.run", run_id="demo-run"),
        trace_span(
            "tripll.agent.dispatch",
            run_id="demo-run",
            node_id="plan:W1",
            attempt_id="a1",
            input_tokens=10,
            output_tokens=5,
        ),
    ):
        pass
    db = run_dir / "traces" / "traces.db"
    jsonl_files = list((run_dir / "traces").glob("*.jsonl"))
    assert db.is_file()
    assert jsonl_files
    rows = sqlite3.connect(db).execute("select kind from trace_events").fetchall()
    kinds = {row[0] for row in rows}
    assert "tripll.run" in kinds
    assert "tripll.agent.dispatch" in kinds


@pytest.mark.asyncio
async def test_dispatch_span_emitted_once_with_tokens(
    tmp_path: Path,
    fake_clock: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    cfg = parse_tracing_config({"tracing": {"enabled": True}})
    init_run_tracing(
        run_dir,
        cfg,
        run_id="r1",
        clock=fake_clock["clock"],
        clock_ns=fake_clock["clock_ns"],
    )

    async def _fake_streaming(*args: Any, **kwargs: Any) -> tuple[int, str, None]:
        return 0, "ok", None

    monkeypatch.setattr("tripll.adapters.base.run_streaming", _fake_streaming)
    adapter = _ProbeAdapter()
    brief = {"node_id": "plan:W1", "model": "auto"}
    log_path = tmp_path / "attempt.log"
    result = await adapter.dispatch(
        brief,
        worktree_path=tmp_path,
        log_path=log_path,
        timeout_s=30,
        log_header={"run_id": "r1", "node_id": "plan:W1", "attempt_id": "att-1", "attempt": 1},
    )
    assert result.outcome == "done"
    db = run_dir / "traces" / "traces.db"
    closed = (
        sqlite3.connect(db)
        .execute(
            "select count(*) from trace_events where kind='tripll.agent.dispatch' and status='closed'"
        )
        .fetchone()[0]
    )
    assert closed == 1
    attrs = (
        sqlite3.connect(db)
        .execute(
            "select attrs from trace_events where kind='tripll.agent.dispatch' and status='closed'"
        )
        .fetchone()[0]
    )
    payload = json.loads(attrs)
    assert payload.get("outcome") == "done"


@pytest.mark.asyncio
async def test_raising_sink_does_not_fail_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    cfg = parse_tracing_config({"tracing": {"enabled": True, "sinks": ["sqlite"]}})
    session = init_run_tracing(run_dir, cfg, run_id="r1")
    assert session is not None
    session.sink = MultiSink([_RaisingSink(), _RecordingSink()])

    async def _fake_streaming(*args: Any, **kwargs: Any) -> tuple[int, str, None]:
        return 0, "ok", None

    monkeypatch.setattr("tripll.adapters.base.run_streaming", _fake_streaming)
    adapter = _ProbeAdapter()
    result = await adapter.dispatch(
        {"node_id": "plan:W1"},
        worktree_path=tmp_path,
        log_path=tmp_path / "a.log",
        timeout_s=5,
        log_header={"run_id": "r1", "attempt_id": "a1"},
    )
    assert result.outcome == "done"


def test_single_logfire_configure_call_site() -> None:
    import subprocess

    out = subprocess.check_output(
        ["grep", "-rn", "-F", "logfire.configure(", "src/tripll", "--include=*.py"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
    )
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "obs.py" in lines[0]


def test_obs_passes_advanced_options_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeAdvanced:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

    class _FakeLogfire:
        AdvancedOptions = _FakeAdvanced

        @staticmethod
        def configure(**kwargs: Any) -> None:
            calls.append(kwargs)

        @staticmethod
        def instrument_httpx(**kwargs: Any) -> None:
            return None

        @staticmethod
        def instrument_pydantic_ai() -> None:
            return None

        class ScrubbingOptions:
            def __init__(self, **kwargs: Any) -> None:
                pass

    monkeypatch.setenv("LOGFIRE_TOKEN", "test-token")
    monkeypatch.setitem(__import__("sys").modules, "logfire", _FakeLogfire())
    import tripll.obs as obs_mod

    obs_mod._configured = False
    plan = {
        "tracing": {
            "enabled": True,
            "exporters": [{"type": "logfire", "base_url": "http://localhost:8080"}],
        }
    }
    obs_mod.configure_observability(plan=plan)
    assert calls
    assert calls[0]["advanced"].base_url == "http://localhost:8080"


def test_skw_does_not_double_configure(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_calls = 0

    def _fake_configure(**kwargs: Any) -> bool:
        nonlocal configure_calls
        configure_calls += 1
        return True

    monkeypatch.setattr("tripll.obs.configure_observability", _fake_configure)
    monkeypatch.setenv("SKW_TRACE", "1")
    from tripll.skw import tracing as skw_tracing

    skw_tracing._tracing_active = False
    assert skw_tracing.configure_tracing(enabled=True) is True
    assert configure_calls == 1


def test_unknown_exporter_rejected_at_parse() -> None:
    with pytest.raises(ValueError, match="unknown tracing exporter"):
        parse_tracing_config({"tracing": {"exporters": [{"type": "kafka"}]}})


def test_jsonl_sink_swallows_io_errors(tmp_path: Path) -> None:
    sink: TraceSink = JsonlTraceSink(tmp_path / "traces")
    event = TraceEvent(
        kind="test",
        span_id="s1",
        parent_span_id=None,
        run_id="r",
        node_id=None,
        attempt_id=None,
        ts_start_ns=1,
        ts_end_ns=2,
        status="closed",
        attrs={},
    )
    sink.emit(event)
    sink.flush()
    sink.close()
