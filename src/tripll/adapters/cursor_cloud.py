"""tripll.adapters.cursor_cloud — Cursor web/background backend (cloud).

Reuses ``sevn.evolution.router`` (Cursor Cloud dispatch/poll) under the
``tripll[cloud]`` extra (D1, D9: import-only, no edits to sevn). When the
extra is not installed the adapter reports unavailable and never dispatches.
Live cloud dispatch + poll are deferred to manual smoke (design-note §7.3).

Exports:
    CursorCloudAdapter — Cursor Cloud adapter (import-gated on the [cloud] extra).
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from tripll.adapters.base import AdapterCapabilities, AgentAdapter, DispatchResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path


def _cloud_available() -> bool:
    """Return True when ``sevn.evolution.router`` is importable.

    Returns:
        bool: True if the ``[cloud]`` extra (sevn) is installed.

    Examples:
        >>> isinstance(_cloud_available(), bool)
        True
    """
    try:
        return importlib.util.find_spec("sevn.evolution.router") is not None
    except ModuleNotFoundError:
        return False


class CursorCloudAdapter(AgentAdapter):
    """Cursor Cloud adapter — dispatches a wave to a cloud issue (import-gated).

    Examples:
        >>> CursorCloudAdapter().name
        'cursor_cloud'
    """

    name = "cursor_cloud"

    def capabilities(self) -> AdapterCapabilities:
        """Return availability based on the ``[cloud]`` extra (sevn).

        Returns:
            AdapterCapabilities: ``available`` when ``sevn.evolution.router`` imports.

        Examples:
            >>> isinstance(CursorCloudAdapter().capabilities().available, bool)
            True
        """
        found = _cloud_available()
        return AdapterCapabilities(
            backend=self.name,
            available=found,
            detail=(
                "sevn.evolution.router importable"
                if found
                else "cloud extra not installed — `uv sync --extra cloud` to enable"
            ),
            streaming=False,
        )

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        """Cloud dispatch is API-based; there is no subprocess argv.

        Args:
            brief (dict[str, object]): Dispatch brief (unused; cloud is API).
            worktree_path (Path): Worktree (unused for cloud dispatch).

        Returns:
            list[str]: Always empty.

        Examples:
            >>> from pathlib import Path
            >>> CursorCloudAdapter().build_argv({}, Path("/wt"))
            []
        """
        return []

    async def dispatch(
        self,
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: Callable[..., Awaitable[None]] | None = None,
    ) -> DispatchResult:
        """Map a wave to a Cursor Cloud issue via ``sevn.evolution.router``."""
        import time

        from tripll.tracing.spans import trace_span

        header = log_header or {}
        run_id = str(header.get("run_id") or brief.get("run_id") or "")
        node_id = str(header.get("node_id") or brief.get("node_id") or "")
        attempt_id = str(header.get("attempt_id") or "")
        started = time.perf_counter()
        with trace_span(
            "tripll.agent.dispatch",
            run_id=run_id or None,
            node_id=node_id or None,
            attempt_id=attempt_id or None,
            backend=self.name,
            model=str(brief.get("model") or getattr(self, "model", "") or ""),
            worktree=str(worktree_path),
            timeout_s=timeout_s,
        ) as span_bag:
            caps = self.capabilities()
            if not caps.available:
                result = DispatchResult(outcome="failed", result_text=caps.detail)
                span_bag.update(
                    outcome=result.outcome,
                    duration_s=time.perf_counter() - started,
                    stop_reason="backend_unavailable",
                )
                return result
            result = DispatchResult(
                outcome="failed",
                result_text="cloud dispatch deferred to manual smoke (design-note §7.3)",
            )
            span_bag.update(
                outcome=result.outcome,
                duration_s=time.perf_counter() - started,
                stop_reason=result.result_text,
            )
            return result
