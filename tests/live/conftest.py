"""Shared helpers for live adapter E2E probes (issue #18)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tripll.adapters.base import AgentAdapter, DispatchResult

LIVE_PROMPT = "Reply with exactly: LIVE_OK (no tools, no explanation)."

_DEFAULT_TIMEOUT_S = 120


def live_timeout_s() -> int:
    """Wall-clock timeout for live adapter probes."""
    raw = os.environ.get("TRIPLL_LIVE_ADAPTER_TIMEOUT_S", str(_DEFAULT_TIMEOUT_S))
    try:
        return max(30, int(raw))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def requested_backends() -> set[str] | None:
    """Optional subset from ``TRIPLL_LIVE_ADAPTER_BACKENDS`` (comma-separated)."""
    raw = os.environ.get("TRIPLL_LIVE_ADAPTER_BACKENDS", "").strip()
    if not raw:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def skip_unless_backend_requested(backend: str) -> None:
    """Skip when *backend* is excluded by ``TRIPLL_LIVE_ADAPTER_BACKENDS``."""
    allowed = requested_backends()
    if allowed is not None and backend not in allowed:
        pytest.skip(f"{backend} not in TRIPLL_LIVE_ADAPTER_BACKENDS={sorted(allowed)!r}")


def minimal_live_brief(backend: str) -> dict[str, object]:
    """Return a tiny dispatch brief for live adapter smoke."""
    brief: dict[str, object] = {
        "wave_id": "LIVE",
        "node_id": f"live:{backend}",
        "run_id": "live-probe",
        "_prompt_override": LIVE_PROMPT,
        "workspace_scope": [],
        "agent_directives": ["Do not use tools."],
    }
    model = os.environ.get("TRIPLL_LIVE_ADAPTER_MODEL", "").strip()
    if model:
        brief["model"] = model
    return brief


def skip_if_unavailable(adapter: AgentAdapter) -> None:
    """Skip when the adapter reports unavailable."""
    caps = adapter.capabilities()
    if not caps.available:
        pytest.skip(f"{adapter.name}: {caps.detail}")


def skip_if_infra_or_auth(result: DispatchResult, *, output: str = "") -> None:
    """Skip (not fail) when dispatch failed for auth/infra reasons."""
    from tripll.adapters.failure_class import classify_dispatch

    if classify_dispatch(result, output=output) == "infra":
        detail = (result.result_text or output)[:300]
        pytest.skip(f"{result.outcome}: {detail}")


async def assert_live_dispatch_ok(
    adapter: AgentAdapter,
    result: DispatchResult,
    *,
    log_path: Path,
) -> None:
    """Assert a live probe succeeded or skip on infra/auth/timeout."""
    output = log_path.read_text(encoding="utf-8") if log_path.is_file() else result.result_text
    if result.outcome == "timed_out":
        pytest.skip(f"{adapter.name} timed out after {live_timeout_s()}s")
    skip_if_infra_or_auth(result, output=output)
    assert result.outcome == "done", (result.result_text or output)[:500]


async def run_live_probe(adapter: AgentAdapter, worktree: Path) -> DispatchResult:
    """Dispatch a minimal live prompt through *adapter*."""
    skip_if_unavailable(adapter)
    log_path = worktree / "logs" / f"{adapter.name}.live.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    brief = minimal_live_brief(adapter.name)
    result = await adapter.dispatch(
        brief,
        worktree_path=worktree,
        log_path=log_path,
        timeout_s=live_timeout_s(),
        log_header={
            "run_id": "live-probe",
            "node_id": f"live:{adapter.name}",
            "attempt": 1,
            "attempt_id": f"live-{adapter.name}-1",
        },
    )
    await assert_live_dispatch_ok(adapter, result, log_path=log_path)
    return result


@pytest.fixture
def live_worktree(tmp_path: Path) -> Path:
    """Minimal git-free worktree root for adapter probes."""
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "README.md").write_text("# live adapter probe\n", encoding="utf-8")
    return wt


@pytest.fixture(autouse=True)
def _clear_runaway_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live probes use provider defaults — disable runaway guards."""
    monkeypatch.delenv("TRIPLL_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("TRIPLL_MAX_TOOL_USES", raising=False)
