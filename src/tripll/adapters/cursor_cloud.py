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
        """Map a wave to a Cursor Cloud issue via ``sevn.evolution.router``.

        Args:
            brief (dict[str, object]): Dispatch brief.
            worktree_path (Path): Worktree (unused for cloud dispatch).
            log_path (Path): Per-attempt log file (unused for cloud dispatch).
            timeout_s (int): Wall-clock timeout (poll budget).
            log_header (dict[str, object] | None): Unused for cloud dispatch.
            on_event (Callable[..., Awaitable[None]] | None): Unused for cloud dispatch.

        Returns:
            DispatchResult: ``failed`` when the extra is absent; otherwise the
            dispatch result. Live cloud dispatch is deferred to manual smoke.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CursorCloudAdapter.dispatch)
            True
        """
        caps = self.capabilities()
        if not caps.available:
            return DispatchResult(outcome="failed", result_text=caps.detail)
        # Live dispatch/poll via sevn.evolution.router is deferred to manual
        # smoke (design-note §7.3); the import gate above proves wiring.
        return DispatchResult(
            outcome="failed",
            result_text="cloud dispatch deferred to manual smoke (design-note §7.3)",
        )
