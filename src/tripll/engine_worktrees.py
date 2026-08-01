"""Worktree allocation and verification protocols/implementations for :mod:`tripll.engine`.

Exports:
    WorktreeManager — protocol for worktree allocation/checkpoint/cleanup/scope checks.
    Verifier — protocol for running verify targets.
    GitWorktreeManager — real git-backed worktree manager.
    MakeVerifier — real ``make`` verifier.
    SingleBranchWorktreeManager — reuse one integration worktree on the feature branch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Protocol

from tripll.worktrees import (
    Worktree,
    allocate_feature_branch_worktree,
    allocate_worktree,
    checkpoint_message,
    checkpoint_worktree,
    cleanup_worktree,
    detect_scope_breach,
    recover_worktree,
    revert_breach,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.pipeline import RunsRoot


class WorktreeManager(Protocol):
    """Protocol for worktree allocation, checkpoint, cleanup, and scope checks."""

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        """Allocate (or reuse) a worktree for a lane-wave.

        Args:
            run_id (str): Run identifier.
            lane_id (str): Lane id.
            wave_id (str): Wave id.

        Returns:
            Worktree: Allocated worktree handle.

        Examples:
            >>> WorktreeManager.allocate.__name__
            'allocate'
        """
        ...

    def checkpoint(
        self,
        worktree: Worktree,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
    ) -> str | None:
        """Commit all worktree changes for *attempt*; return commit SHA or None.

        Args:
            worktree (Worktree): Lane worktree.
            run_id (str): Run identifier.
            node_id (str): Wave node id.
            attempt (int): Attempt number (1-based).

        Returns:
            str | None: Commit SHA when changes were committed.

        Examples:
            >>> WorktreeManager.checkpoint.__name__
            'checkpoint'
        """
        ...

    def recover(self, worktree: Worktree, *, run_id: str, node_id: str) -> str | None:
        """Commit orphaned work in *worktree* after a crash.

        Args:
            worktree (Worktree): Lane worktree.
            run_id (str): Run identifier.
            node_id (str): Wave node id.

        Returns:
            str | None: Commit SHA when recovery committed changes.

        Examples:
            >>> WorktreeManager.recover.__name__
            'recover'
        """
        ...

    def cleanup(self, worktree: Worktree) -> None:
        """Remove the worktree after a successful wave.

        Args:
            worktree (Worktree): Lane worktree to remove.

        Examples:
            >>> WorktreeManager.cleanup.__name__
            'cleanup'
        """
        ...

    def scope_breach(
        self,
        worktree: Worktree,
        forbidden: list[str],
        *,
        owned_paths: list[str] | None = None,
    ) -> list[str]:
        """Return changed paths under any forbidden path.

        Args:
            worktree (Worktree): Lane worktree.
            forbidden (list[str]): Paths the wave may not edit.
            owned_paths (list[str] | None): Optional owned-path hint for detection.

        Returns:
            list[str]: Repo-relative breached paths (empty when clean).

        Examples:
            >>> WorktreeManager.scope_breach.__name__
            'scope_breach'
        """
        ...

    def revert(self, worktree: Worktree, files: list[str]) -> None:
        """Revert breached files in *worktree*.

        Args:
            worktree (Worktree): Lane worktree.
            files (list[str]): Repo-relative paths to revert.

        Examples:
            >>> WorktreeManager.revert.__name__
            'revert'
        """
        ...


class Verifier(Protocol):
    """Protocol for running a node's verify targets."""

    def verify(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        """Run *targets* in *worktree_path*; return ``(ok, evidence)``.

        Args:
            worktree_path (Path): Lane worktree root.
            targets (list[str]): Makefile targets (e.g. ``make lint``).

        Returns:
            tuple[bool, str]: Success flag and evidence string.

        Examples:
            >>> Verifier.verify.__name__
            'verify'
        """
        ...


class GitWorktreeManager:
    """Real git-backed worktree manager (production path).

    Args:
        repo_root (Path): The sevn.bot checkout.
        runs_root (RunsRoot): Runs root (for per-run worktree dirs).
        base_ref (str): Git ref to branch from.
    """

    def __init__(self, repo_root: Path, runs_root: RunsRoot, *, base_ref: str = "HEAD") -> None:
        """Store repo and runs-root paths for worktree allocation."""
        self.repo_root = repo_root
        self.runs_root = runs_root
        self.base_ref = base_ref

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        """Allocate a git worktree for *lane_id*:*wave_id* under the run."""
        return allocate_worktree(
            self.repo_root,
            self.runs_root.worktrees_dir(run_id),
            run_id=run_id,
            lane_id=lane_id,
            wave_id=wave_id,
            base_ref=self.base_ref,
        )

    def checkpoint(
        self,
        worktree: Worktree,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
    ) -> str | None:
        """Checkpoint *worktree* changes for attempt *attempt*."""
        msg = checkpoint_message(run_id=run_id, node_id=node_id, attempt=attempt)
        return checkpoint_worktree(worktree.path, message=msg)

    def recover(self, worktree: Worktree, *, run_id: str, node_id: str) -> str | None:
        """Recover orphaned work in *worktree* after a crash."""
        return recover_worktree(worktree.path, run_id=run_id, node_id=node_id)

    def cleanup(self, worktree: Worktree) -> None:
        """Remove *worktree* from disk and prune the git worktree entry."""
        cleanup_worktree(self.repo_root, worktree)

    def scope_breach(
        self,
        worktree: Worktree,
        forbidden: list[str],
        *,
        owned_paths: list[str] | None = None,
    ) -> list[str]:
        """Detect forbidden-path edits in *worktree*."""
        return detect_scope_breach(worktree.path, forbidden, owned_paths=owned_paths)

    def revert(self, worktree: Worktree, files: list[str]) -> None:
        """Revert *files* in *worktree* after a scope breach."""
        revert_breach(worktree.path, files)


class MakeVerifier:
    """Real verifier that runs each make target inside the worktree.

    Uses the main checkout toolchain (``UV_PROJECT``) so worktrees do not build a
    stale local ``.venv``. ``typecheck`` is scoped to ``src/sevn`` files changed
    on the lane branch (not full-repo ``mypy``).

    Args:
        repo_root (Path): sevn.bot checkout (toolchain + ``UV_PROJECT`` target).
        timeout_s (int): Per-target subprocess timeout.
    """

    def __init__(self, *, repo_root: Path, timeout_s: int = 1800) -> None:
        """Store toolchain root and per-target timeout."""
        self.repo_root = repo_root.resolve()
        self.timeout_s = timeout_s

    def _toolchain_env(self) -> dict[str, str]:
        """Return subprocess env with ``UV_PROJECT`` pointed at the main checkout."""
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_PROJECT"] = str(self.repo_root)
        return env

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Run *argv* in *cwd* with *env* and capture output."""
        return subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=self.timeout_s,
            env=env,
        )

    def _merge_base(self, worktree_path: Path, env: dict[str, str]) -> str:
        """Return a merge-base ref for diffing ``src/sevn`` changes on the lane branch."""
        refs: list[str] = []
        sym = self._run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=worktree_path,
            env=env,
        )
        if sym.returncode == 0 and sym.stdout.strip():
            refs.append(sym.stdout.strip().removeprefix("origin/"))
        refs.extend(["main", "master", "test-pre"])
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            proc = self._run(
                ["git", "merge-base", "HEAD", ref],
                cwd=worktree_path,
                env=env,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        return "HEAD~1"

    def _changed_src_sevn(self, worktree_path: Path, env: dict[str, str]) -> list[str]:
        """List changed or untracked ``src/sevn`` Python files on the lane branch."""
        base = self._merge_base(worktree_path, env)
        proc = self._run(
            ["git", "diff", "--name-only", base, "--", "src/sevn"],
            cwd=worktree_path,
            env=env,
        )
        if proc.returncode != 0:
            return []
        paths = {line.strip() for line in proc.stdout.splitlines() if line.strip().endswith(".py")}
        untracked = self._run(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                "src/sevn",
            ],
            cwd=worktree_path,
            env=env,
        )
        if untracked.returncode == 0:
            paths.update(
                line.strip()
                for line in untracked.stdout.splitlines()
                if line.strip().endswith(".py")
            )
        return sorted(paths)

    def _verify_typecheck(self, worktree_path: Path, env: dict[str, str]) -> tuple[bool, str]:
        """Run scoped ``mypy`` on changed ``src/sevn`` files only."""
        files = self._changed_src_sevn(worktree_path, env)
        if not files:
            return True, "typecheck skipped (no src/sevn changes on branch)"
        uv = shutil.which("uv") or "uv"
        proc = self._run(
            [uv, "run", "mypy", *files],
            cwd=worktree_path,
            env=env,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "")[-1000:]
            return False, f"make typecheck failed: {detail}"
        return True, f"typecheck ok ({len(files)} files)"

    def verify(self, worktree_path: Path, targets: list[str]) -> tuple[bool, str]:
        """Run each make target in *worktree_path*; return ``(ok, evidence)``."""
        make = shutil.which("make") or "make"
        env = self._toolchain_env()
        for target in targets:
            tgt = target.removeprefix("make ").strip()
            try:
                if tgt == "typecheck":
                    ok, ev = self._verify_typecheck(worktree_path, env)
                    if not ok:
                        return False, ev
                    continue
                proc = self._run([make, tgt], cwd=worktree_path, env=env)
            except subprocess.TimeoutExpired:
                return False, f"{target} timed out after {self.timeout_s}s"
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "")[-1000:]
                return False, f"{target} failed: {detail}"
        return True, "all verify targets passed"


class SingleBranchWorktreeManager(GitWorktreeManager):
    """Reuse one integration worktree on the orchestrator feature branch (D8)."""

    def __init__(
        self,
        repo_root: Path,
        runs_root: RunsRoot,
        *,
        feature_branch: str,
        base_ref: str = "HEAD",
    ) -> None:
        """Store *feature_branch* for single-worktree orchestrator mode."""
        super().__init__(repo_root, runs_root, base_ref=base_ref)
        self.feature_branch = feature_branch
        self._shared: Worktree | None = None

    def allocate(self, run_id: str, lane_id: str, wave_id: str) -> Worktree:
        """Reuse the shared integration worktree when already allocated."""
        if self._shared is not None:
            return Worktree(
                path=self._shared.path,
                branch=self._shared.branch,
                lane_id=lane_id,
                wave_id=wave_id,
            )
        path = self.runs_root.worktrees_dir(run_id) / "integration"
        wt = allocate_feature_branch_worktree(
            self.repo_root,
            path,
            branch=self.feature_branch,
            base_ref=self.base_ref,
        )
        self._shared = wt
        return Worktree(path=wt.path, branch=wt.branch, lane_id=lane_id, wave_id=wave_id)

    def cleanup(self, worktree: Worktree) -> None:
        """No-op — integration worktree persists across orchestrator waves."""
        return None
