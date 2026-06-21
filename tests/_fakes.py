"""Shared test fakes for tripll — a no-subprocess FakeAdapter.

Used by the adapter tests (W4) and the engine tests (W5) so neither needs a
real backend binary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.adapters.base import (
    AdapterCapabilities,
    AgentAdapter,
    DispatchOutcome,
    DispatchResult,
)
from tripll.worktrees import Worktree, branch_name

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.adapters.base import StreamEventCallback


class FakeAdapter(AgentAdapter):
    """In-memory adapter that records calls and returns scripted outcomes.

    Args:
        fail_times (int): Number of leading attempts to fail before succeeding.
        final_outcome (DispatchOutcome): Outcome once past ``fail_times``.
        available (bool): Capability availability.
    """

    name = "fake"

    def __init__(
        self,
        *,
        fail_times: int = 0,
        final_outcome: DispatchOutcome = "done",
        available: bool = True,
    ) -> None:
        self.fail_times = fail_times
        self.final_outcome = final_outcome
        self.available = available
        self.calls = 0
        self.dispatched: list[str] = []

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            backend=self.name, available=self.available, detail="fake", streaming=False
        )

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        return ["fake", str(brief.get("node_id", "?")), str(worktree_path)]

    async def dispatch(
        self,
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: StreamEventCallback | None = None,
    ) -> DispatchResult:
        self.calls += 1
        self.dispatched.append(str(brief.get("node_id", "?")))
        argv = self.build_argv(brief, worktree_path)
        if self.calls <= self.fail_times:
            return DispatchResult(
                outcome="failed",
                result_text=f"scripted failure {self.calls}",
                returncode=1,
                log_path=str(log_path),
                argv=argv,
            )
        return DispatchResult(
            outcome=self.final_outcome,
            result_text="ok",
            returncode=0,
            log_path=str(log_path),
            argv=argv,
        )


class FakeWorktreeManager:
    """No-git worktree manager — creates plain directories.

    Args:
        base_dir (Path): Root under which fake worktrees are created.
        breaches (list[str] | None): Paths to report as breached (default none).
    """

    def __init__(self, base_dir: Path, *, breaches: list[str] | None = None) -> None:
        self.base_dir = base_dir
        self.breaches = breaches or []
        self.allocated: list[str] = []

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        safe = f"{lane_id}-{wave_id}".replace(":", "_").replace("/", "_").replace(">", "")
        path = self.base_dir / safe
        path.mkdir(parents=True, exist_ok=True)
        self.allocated.append(safe)
        return Worktree(
            path=path,
            branch=branch_name(run_id, lane_id, wave_id),
            lane_id=lane_id,
            wave_id=wave_id,
        )

    def checkpoint(
        self,
        worktree: Worktree,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
    ) -> str | None:
        return None

    def recover(self, worktree: Worktree, *, run_id: str, node_id: str) -> str | None:
        return None

    def cleanup(self, worktree: Worktree) -> None:
        return None

    def scope_breach(
        self,
        worktree: Worktree,
        forbidden: list[str],
        *,
        owned_paths: list[str] | None = None,
    ) -> list[str]:
        return list(self.breaches)

    def revert(self, worktree: Worktree, files: list[str]) -> None:
        return None


class AlwaysPassVerifier:
    """Verifier that always reports success."""

    def verify(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        return True, "ok"


class AlwaysFailVerifier:
    """Verifier that always reports failure."""

    def verify(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        return False, "verify failed"
