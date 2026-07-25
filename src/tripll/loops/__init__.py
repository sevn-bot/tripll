"""LangGraph control-plane loops (optional ``graph`` extra).

Probes ``langgraph`` at import time mirroring ``adapters/cursor_cloud.py``.
When absent, tripll keeps the linear batch engine path; plans that require
cyclic control flow must call :func:`require_graph` and fail fast.

Exports:
    graph_available — True when the ``graph`` extra is installed.
    require_graph — raise with install hint when cyclic control is required.
"""

from __future__ import annotations

import importlib.util

__all__ = ["graph_available", "require_graph"]


def graph_available() -> bool:
    """Return True when LangGraph is importable (``tripll[graph]`` installed).

    Returns:
        bool: True when ``langgraph`` is on the path.

    Examples:
        >>> isinstance(graph_available(), bool)
        True
    """
    try:
        return importlib.util.find_spec("langgraph") is not None
    except ModuleNotFoundError:
        return False


def require_graph(*, feature: str = "cyclic control flow") -> None:
    """Fail fast when a plan needs LangGraph but the extra is missing.

    Args:
        feature (str): Human-readable feature name for the error message.

    Raises:
        RuntimeError: When ``langgraph`` is not installed.

    Examples:
        >>> require_graph.__name__
        'require_graph'
    """
    if not graph_available():
        msg = f"{feature} requires the optional [graph] extra — install with: uv sync --extra graph"
        raise RuntimeError(msg)
