"""Redact span attributes using the shared hide-list (R22).

Exports:
    RedactingSink — ``TraceSink`` wrapper applying ``log_redact.load_hide_keys``.
"""

from __future__ import annotations

import re
from typing import Any

from tripll.log_redact import load_hide_keys
from tripll.tracing.sink import TraceEvent, TraceSink, cap_attrs


class RedactingSink:
    """Wrap a sink and redact sensitive attribute keys before write."""

    def __init__(self, inner: TraceSink, *, hide_keys: frozenset[str] | None = None) -> None:
        """Wrap *inner* with hide-key redaction."""
        self._inner = inner
        self._hide_keys = hide_keys if hide_keys is not None else load_hide_keys()
        self._patterns = [re.compile(rf"(?i){re.escape(key)}") for key in self._hide_keys]

    def emit(self, event: TraceEvent) -> None:
        """Redact and forward *event*."""
        try:
            redacted = TraceEvent(
                kind=event.kind,
                span_id=event.span_id,
                parent_span_id=event.parent_span_id,
                run_id=event.run_id,
                node_id=event.node_id,
                attempt_id=event.attempt_id,
                ts_start_ns=event.ts_start_ns,
                ts_end_ns=event.ts_end_ns,
                status=event.status,
                attrs=cap_attrs(_redact_attrs(event.attrs, self._patterns)),
            )
            self._inner.emit(redacted)
        except Exception:
            return

    def flush(self) -> None:
        """Flush the inner sink."""
        try:
            self._inner.flush()
        except Exception:
            return

    def close(self) -> None:
        """Close the inner sink."""
        try:
            self._inner.close()
        except Exception:
            return


def _redact_attrs(attrs: dict[str, Any], patterns: list[re.Pattern[str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if any(p.search(key) for p in patterns):
            out[key] = "[redacted]"
        elif isinstance(value, dict):
            out[key] = _redact_mapping(value, patterns)
        elif isinstance(value, list):
            out[key] = [_redact_item(item, patterns) for item in value]
        else:
            out[key] = value
    return out


def _redact_mapping(value: dict[str, Any], patterns: list[re.Pattern[str]]) -> dict[str, Any]:
    return {
        k: ("[redacted]" if any(p.search(k) for p in patterns) else v) for k, v in value.items()
    }


def _redact_item(value: Any, patterns: list[re.Pattern[str]]) -> Any:
    if isinstance(value, dict):
        return _redact_mapping(value, patterns)
    return value
