"""tripll.tracing — local trace sinks and span helpers for the observability spine.

Exports:
    TraceEvent — immutable span record written to local sinks.
    TraceSink — sink protocol (emit / flush / close).
    NullTraceSink — no-op sink.
    MultiSink — ordered fan-out to multiple sinks.
    JsonlTraceSink — daily-rotated JSONL writer.
    SqliteTraceSink — SQLite trace store with retention purge.
    RedactingSink — hide-list wrapper applied once before fan-out.
    TracingConfig — parsed ``[tracing]`` settings.
    CaptureMode — prompt/completion capture policy (R21).
    parse_tracing_config — parse plan TOML + env overrides.
    RunTraceSession — per-run sink bundle and span stack.
    init_run_tracing — create sinks under ``runs/.../traces/``.
    get_run_session — active run session, if any.
    trace_span — context manager emitting ``TraceEvent`` records.
    shape_capture_value — apply the capture policy to prompt-like attrs.
"""

from __future__ import annotations

from tripll.tracing.capture import CaptureMode, shape_capture_value
from tripll.tracing.config import TracingConfig, parse_tracing_config
from tripll.tracing.redact import RedactingSink
from tripll.tracing.sink import MultiSink, NullTraceSink, TraceEvent, TraceSink
from tripll.tracing.sinks import JsonlTraceSink, SqliteTraceSink
from tripll.tracing.spans import RunTraceSession, get_run_session, init_run_tracing, trace_span

__all__ = [
    "CaptureMode",
    "JsonlTraceSink",
    "MultiSink",
    "NullTraceSink",
    "RedactingSink",
    "RunTraceSession",
    "SqliteTraceSink",
    "TraceEvent",
    "TraceSink",
    "TracingConfig",
    "get_run_session",
    "init_run_tracing",
    "parse_tracing_config",
    "shape_capture_value",
    "trace_span",
]
