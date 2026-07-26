"""Run-scoped span helpers writing to local sinks (TRACE-01).

Exports:
    RunTraceSession — per-run sink bundle and parent stack.
    init_run_tracing — create sinks under ``runs/.../traces/``.
    get_run_session — active session for the current task.
    trace_span — context manager emitting ``TraceEvent`` records.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — runtime run_dir paths
from typing import Any

from tripll.tracing.capture import CaptureMode, shape_capture_value
from tripll.tracing.config import TracingConfig  # noqa: TC001 — runtime dataclass
from tripll.tracing.redact import RedactingSink
from tripll.tracing.sink import MultiSink, NullTraceSink, TraceEvent, TraceSink
from tripll.tracing.sinks import JsonlTraceSink, SqliteTraceSink

ClockNsFn = Callable[[], int]

_run_session: contextvars.ContextVar[RunTraceSession | None] = contextvars.ContextVar(
    "tripll_run_trace_session",
    default=None,
)


def _default_clock_ns() -> int:
    return time.time_ns()


@dataclass
class RunTraceSession:
    """Active run trace session bound to one ``traces/`` directory.

    Args:
        run_id (str): Run identifier.
        config (TracingConfig): Tracing settings for this run.
        sink (TraceSink): Composite local sink (possibly redacted).
        capture (CaptureMode): Prompt capture policy.
    """

    run_id: str
    config: TracingConfig
    sink: TraceSink
    capture: CaptureMode
    clock_ns: ClockNsFn = field(default=_default_clock_ns)
    _stack: list[str] = field(default_factory=list)
    _span_seq: int = 0

    def next_span_id(self) -> str:
        """Return a unique span id."""
        self._span_seq += 1
        return f"{self.run_id}:{self._span_seq}:{uuid.uuid4().hex[:8]}"

    @property
    def parent_span_id(self) -> str | None:
        """Current parent span id."""
        return self._stack[-1] if self._stack else None


def build_local_sink(
    traces_dir: Path,
    config: TracingConfig,
    *,
    clock: Callable[[], float] | None = None,
) -> TraceSink:
    """Build the configured local sink bundle for *traces_dir*."""
    sinks: list[TraceSink] = []
    for name in config.sinks:
        if name == "jsonl":
            sinks.append(JsonlTraceSink(traces_dir, clock=clock))
        elif name == "sqlite":
            sinks.append(
                SqliteTraceSink(traces_dir, retention_days=config.retention_days, clock=clock)
            )
    if not sinks:
        return NullTraceSink()
    composite: TraceSink = MultiSink(sinks)
    return RedactingSink(composite)


def init_run_tracing(
    run_dir: Path,
    config: TracingConfig,
    *,
    run_id: str | None = None,
    clock: Callable[[], float] | None = None,
    clock_ns: ClockNsFn | None = None,
) -> RunTraceSession | None:
    """Create local sinks under *run_dir/traces* and bind the run session."""
    if not config.enabled or not config.has_local_sinks:
        _run_session.set(None)
        return None
    rid = run_id or run_dir.name
    traces_dir = run_dir / "traces"
    sink = build_local_sink(traces_dir, config, clock=clock)
    session = RunTraceSession(
        run_id=rid,
        config=config,
        sink=sink,
        capture=config.capture,
        clock_ns=clock_ns or _default_clock_ns,
    )
    _run_session.set(session)
    return session


def get_run_session() -> RunTraceSession | None:
    """Return the active :class:`RunTraceSession`, if any."""
    return _run_session.get()


def close_run_tracing() -> None:
    """Flush and close the active run session sinks."""
    session = _run_session.get()
    if session is None:
        return
    try:
        session.sink.flush()
        session.sink.close()
    except Exception:
        pass
    _run_session.set(None)


def _apply_capture(attrs: dict[str, Any], mode: CaptureMode) -> dict[str, Any]:
    shaped: dict[str, Any] = {}
    for key, value in attrs.items():
        shaped_val = shape_capture_value(key, value, mode=mode)
        if shaped_val is not None:
            shaped[key] = shaped_val
    return shaped


@contextmanager
def trace_span(
    kind: str,
    *,
    run_id: str | None = None,
    node_id: str | None = None,
    attempt_id: str | None = None,
    session: RunTraceSession | None = None,
    **attrs: Any,
) -> Iterator[dict[str, Any]]:
    """Emit open/close :class:`TraceEvent` records for a span."""
    bag: dict[str, Any] = {}
    active = session or get_run_session()
    if active is None:
        yield bag
        return

    span_id = active.next_span_id()
    parent = active.parent_span_id
    open_attrs = _apply_capture(dict(attrs), active.capture)
    ts_start = active.clock_ns()
    open_event = TraceEvent(
        kind=kind,
        span_id=span_id,
        parent_span_id=parent,
        run_id=run_id or active.run_id,
        node_id=node_id,
        attempt_id=attempt_id,
        ts_start_ns=ts_start,
        ts_end_ns=None,
        status="open",
        attrs=open_attrs,
    )
    active.sink.emit(open_event)
    active._stack.append(span_id)
    close_attrs = dict(open_attrs)

    try:
        try:
            import logfire

            with logfire.span(kind, **open_attrs) as lf_span:
                yield bag
                close_attrs = _apply_capture({**open_attrs, **bag}, active.capture)
                extra = {k: v for k, v in close_attrs.items() if k not in open_attrs}
                if extra:
                    lf_span.set_attributes(extra)
        except ImportError:
            yield bag
            close_attrs = _apply_capture({**open_attrs, **bag}, active.capture)
    finally:
        active._stack.pop()
        ts_end = active.clock_ns()
        close_event = TraceEvent(
            kind=kind,
            span_id=span_id,
            parent_span_id=parent,
            run_id=run_id or active.run_id,
            node_id=node_id,
            attempt_id=attempt_id,
            ts_start_ns=ts_start,
            ts_end_ns=ts_end,
            status="closed",
            attrs=close_attrs,
        )
        active.sink.emit(close_event)
