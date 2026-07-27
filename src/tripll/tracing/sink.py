"""Trace event model and sink protocol (TRACE-04).

Exports:
    TraceEvent — frozen span record.
    TraceSink — emit / flush / close protocol.
    NullTraceSink — no-op sink.
    MultiSink — ordered fan-out; ``emit`` never raises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

MAX_ATTRS_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One span lifecycle record persisted to local sinks.

    Args:
        kind (str): Span name (for example ``tripll.agent.dispatch``).
        span_id (str): Unique span identifier.
        parent_span_id (str | None): Parent span, when nested.
        run_id (str | None): Owning run id for ledger correlation.
        node_id (str | None): Wave node id.
        attempt_id (str | None): Ledger attempt id (join key).
        ts_start_ns (int): Open timestamp (nanoseconds).
        ts_end_ns (int | None): Close timestamp (nanoseconds).
        status (str): ``open`` or ``closed``.
        attrs (dict[str, Any]): Span attributes (serialized with a size cap).
    """

    kind: str
    span_id: str
    parent_span_id: str | None
    run_id: str | None
    node_id: str | None
    attempt_id: str | None
    ts_start_ns: int
    ts_end_ns: int | None
    status: str
    attrs: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TraceSink(Protocol):
    """Local trace writer invoked by the span spine."""

    def emit(self, event: TraceEvent) -> None:
        """Persist *event*; implementations must not raise."""

    def flush(self) -> None:
        """Flush buffered records; implementations must not raise."""

    def close(self) -> None:
        """Release resources; implementations must not raise."""


class NullTraceSink:
    """No-op sink used when tracing is disabled."""

    def emit(self, event: TraceEvent) -> None:
        """Ignore *event*."""

    def flush(self) -> None:
        """No-op."""

    def close(self) -> None:
        """No-op."""


class MultiSink:
    """Fan-out sink that swallows per-sink I/O errors (sevn invariant)."""

    def __init__(self, sinks: list[TraceSink]) -> None:
        """Wrap *sinks* in emission order."""
        self._sinks = list(sinks)

    def emit(self, event: TraceEvent) -> None:
        """Forward *event* to every child sink."""
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:
                continue

    def flush(self) -> None:
        """Flush every child sink."""
        for sink in self._sinks:
            try:
                sink.flush()
            except Exception:
                continue

    def close(self) -> None:
        """Close every child sink."""
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:
                continue


def cap_attrs(attrs: dict[str, Any], *, limit: int = MAX_ATTRS_BYTES) -> dict[str, Any]:
    """Return *attrs* truncated so JSON serialization stays under *limit* bytes.

    Args:
        attrs (dict[str, Any]): Span attributes.
        limit (int): Maximum serialized byte length.

    Returns:
        dict[str, Any]: Possibly truncated attributes with a ``_truncated`` marker.
    """
    try:
        encoded = json.dumps(attrs, default=str, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return {"_error": "attrs_not_serializable"}
    if len(encoded) <= limit:
        return dict(attrs)
    trimmed = dict(attrs)
    trimmed["_truncated"] = True
    while trimmed and len(json.dumps(trimmed, default=str, separators=(",", ":")).encode()) > limit:
        if len(trimmed) <= 1:
            return {"_truncated": True}
        key = next(iter(trimmed))
        if key != "_truncated":
            del trimmed[key]
        else:
            break
    return trimmed
