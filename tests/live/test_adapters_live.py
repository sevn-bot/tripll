"""Live end-to-end adapter probes (issue #18).

Tier-2 tests that dispatch a one-line prompt through each real backend.
Collected only when ``RUN_LIVE=1``; each backend skips when the binary,
``tripll[cloud]`` extra, or credentials are absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.live.conftest import (
    live_agent,
    live_timeout_s,
    minimal_live_brief,
    run_live_probe,
    skip_if_probe_not_runnable,
    skip_if_unavailable,
    skip_unless_backend_requested,
)
from tripll.adapters.claude_code import ClaudeCodeAdapter
from tripll.adapters.cursor_cloud import CursorCloudAdapter
from tripll.adapters.cursor_local import CursorLocalAdapter

pytestmark = pytest.mark.tier2


@pytest.mark.asyncio
async def test_claude_code_live_minimal_dispatch(live_worktree: Path) -> None:
    """Probe ``claude_code`` with a minimal headless prompt."""
    skip_unless_backend_requested("claude_code")
    adapter = ClaudeCodeAdapter(agent=live_agent(), skip_permissions=True)
    await run_live_probe(adapter, live_worktree)


@pytest.mark.asyncio
async def test_cursor_local_live_minimal_dispatch(live_worktree: Path) -> None:
    """Probe ``cursor_local`` with a minimal headless prompt."""
    skip_unless_backend_requested("cursor_local")
    adapter = CursorLocalAdapter(model="auto")
    await run_live_probe(adapter, live_worktree)


@pytest.mark.asyncio
async def test_cursor_cloud_live_capabilities_probe(live_worktree: Path) -> None:
    """Probe ``cursor_cloud`` import gate; full dispatch remains deferred."""
    skip_unless_backend_requested("cursor_cloud")
    adapter = CursorCloudAdapter()
    skip_if_unavailable(adapter)
    log_path = live_worktree / "logs" / "cursor_cloud.live.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = await adapter.dispatch(
        minimal_live_brief("cursor_cloud"),
        worktree_path=live_worktree,
        log_path=log_path,
        timeout_s=live_timeout_s(),
        log_header={
            "run_id": "live-probe",
            "node_id": "live:cursor_cloud",
            "attempt": 1,
            "attempt_id": "live-cursor_cloud-1",
        },
    )
    if "deferred" in result.result_text.lower():
        pytest.skip(f"cursor_cloud live dispatch deferred: {result.result_text}")
    output = log_path.read_text(encoding="utf-8") if log_path.is_file() else result.result_text
    skip_if_probe_not_runnable(result, output=output)
    assert result.outcome == "done", (result.result_text or output)[:500]
