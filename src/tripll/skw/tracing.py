"""Logfire tracing for pipeline nodes and agent calls (Wave W4, D7).

``logfire.configure()`` when ``SKW_TRACE=1`` or ``skw.toml [tracing].enabled``;
spans wrap every graph node and driver call. Clean no-op when disabled.

Exports:
    configure_tracing — optional Logfire setup (W4).
    is_tracing_enabled — resolve tracing gate from env + config.
    span — context manager for traced operations (W4).
    trace_node — wrap a pipeline node callable in a span (W4).
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
_configured = False


def is_tracing_enabled(*, kit_root: Path | None = None) -> bool:
    """Return whether tracing is enabled via env or ``skw.toml``.

    Args:
        kit_root (Path | None): Kit root for ``skw.toml`` lookup; defaults to cwd.

    Returns:
        bool: ``True`` when ``SKW_TRACE=1`` or ``[tracing].enabled`` is set.

    Examples:
        >>> is_tracing_enabled()  # doctest: +SKIP
        False
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
    """Configure Logfire when tracing is enabled (D7).

    Token resolution: ``LOGFIRE_TOKEN`` env, then ``skw.toml [tracing].token``.

    Args:
        enabled (bool): Explicit enable flag (typically from ``is_tracing_enabled``).
        kit_root (Path | None): Kit root for config lookup.

    Returns:
        bool: ``True`` when Logfire was configured; ``False`` when tracing is off.

    Examples:
        >>> configure_tracing(enabled=False)
        False
    """
    global _tracing_active, _configured

    active = enabled or is_tracing_enabled(kit_root=kit_root)
    if not active:
        _tracing_active = False
        return False

    if not _configured:
        import logfire

        token = os.environ.get("LOGFIRE_TOKEN", "").strip()
        if not token and kit_root is not None:
            cfg = load_skw_config(kit_root)
            tracing = cfg.get("tracing", {})
            if isinstance(tracing, dict):
                cfg_token = tracing.get("token")
                if isinstance(cfg_token, str) and cfg_token.strip():
                    token = cfg_token.strip()

        logfire.configure(
            send_to_logfire="if-token-present",
            token=token or None,
            inspect_arguments=False,
        )
        _configured = True

    _tracing_active = True
    return True


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    """Context manager for a traced operation; no-op when tracing is disabled.

    Args:
        name (str): Span name (e.g. ``pipeline.validate``, ``driver.run_agent``).
        **attrs: Span attributes (agent, wave_id, role, prompt, …).

    Yields:
        dict[str, Any]: Mutable bag for callers to set ``output``, ``duration_s``, etc.

    Examples:
        >>> with span("pipeline.validate", wave_id="W1") as bag:
        ...     bag["output"] = "ok"
    """
    bag: dict[str, Any] = {}
    if not _tracing_active:
        yield bag
        return

    import logfire

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
    """Run *fn* inside a tracing span (pipeline graph nodes).

    Args:
        name (str): Span name (typically the graph node id).
        fn (Callable[[], _T]): Node body to execute.
        **attrs: Span attributes forwarded to :func:`span`.

    Returns:
        _T: Return value from *fn*.

    Examples:
        >>> trace_node("validate", lambda: 1)
        1
    """
    with span(name, **attrs):
        return fn()
