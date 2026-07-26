"""Logfire tracing for pipeline nodes and agent calls — thin forwarder to ``tripll.obs``.

``SKW_TRACE=1`` or ``skw.toml [tracing].enabled`` gate SKW spans; configuration is
delegated to :func:`tripll.obs.configure_observability` (R22 / TRACE-03).

Exports:
    configure_tracing — optional Logfire setup (forwarder).
    is_tracing_enabled — resolve tracing gate from env + config.
    span — context manager for traced operations.
    trace_node — wrap a pipeline node callable in a span.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from tripll.skw.validate import load_skw_config

__all__: list[str] = ["configure_tracing", "is_tracing_enabled", "span", "trace_node"]

_T = TypeVar("_T")

_tracing_active = False


def is_tracing_enabled(*, kit_root: Path | None = None) -> bool:
    """Return whether tracing is enabled via env or ``skw.toml``.

    Args:
        kit_root (Path | None): Kit root for ``skw.toml`` lookup; defaults to cwd.

    Returns:
        bool: ``True`` when ``SKW_TRACE=1`` or ``[tracing].enabled`` is set.
    """
    if os.environ.get("SKW_TRACE") == "1":
        return True
    root = kit_root or Path.cwd()
    cfg = load_skw_config(root)
    tracing = cfg.get("tracing", {})
    if isinstance(tracing, dict):
        return bool(tracing.get("enabled", False))
    return False


def configure_tracing(*, enabled: bool = False, kit_root: Path | None = None) -> bool:
    """Enable tracing via the shared :mod:`tripll.obs` configurator.

    Args:
        enabled (bool): Explicit enable flag (typically from ``is_tracing_enabled``).
        kit_root (Path | None): Kit root for config lookup (unused for SDK setup).

    Returns:
        bool: ``True`` when tracing is active for SKW spans.
    """
    global _tracing_active

    active = enabled or is_tracing_enabled(kit_root=kit_root)
    if not active:
        _tracing_active = False
        return False

    from tripll.obs import configure_observability

    configure_observability()
    _tracing_active = True
    return True


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    """Context manager for a traced operation; no-op when tracing is disabled."""
    bag: dict[str, Any] = {}
    if not _tracing_active:
        yield bag
        return

    try:
        import logfire
    except ImportError:
        yield bag
        return

    start = time.perf_counter()
    with logfire.span(name, **attrs) as lf_span:
        yield bag
        duration = time.perf_counter() - start
        bag.setdefault("duration_s", duration)
        extra_attrs = {
            key: bag[key]
            for key in (
                "output",
                "duration_s",
                "verdict",
                "verify_targets",
                "verify_results",
                "tool_calls",
                "argv",
                "exit_code",
                "subject",
            )
            if key in bag
        }
        if extra_attrs:
            lf_span.set_attributes(extra_attrs)


def trace_node(
    name: str,
    fn: Callable[[], _T],
    **attrs: Any,
) -> _T:
    """Run *fn* inside a tracing span (pipeline graph nodes)."""
    with span(name, **attrs):
        return fn()
