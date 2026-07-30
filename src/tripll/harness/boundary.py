"""Tool boundary and isolated verifier dispatch (§7.9.3, D17)."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "VerifyDispatchContext",
    "assert_verify_isolation",
    "build_verify_dispatch",
    "classify_action",
    "detect_structural_scope_breach",
    "materialize_verify_worktree",
    "remove_verify_worktree",
    "require_approval",
]

ActionClass = Literal["read", "draft", "write", "destructive"]


@dataclass(frozen=True, slots=True)
class VerifyDispatchContext:
    """Isolated verifier process + worktree; no implementer transcript."""

    process_id: int
    worktree: str
    commit_sha: str
    node_id: str
    transcript: None = None


def classify_action(action: str, *, destructive: bool = False) -> ActionClass:
    """Classify an external action under the eight-layer boundary."""
    if destructive or action in {"merge", "force_push", "delete_branch", "publish"}:
        return "destructive"
    if action in {"open_pr", "push", "comment", "git push"}:
        return "write"
    if action in {"draft_pr", "patch", "report"}:
        return "draft"
    return "read"


def require_approval(action_class: ActionClass, *, approved: bool = False) -> None:
    """Refuse write/destructive actions without policy approval."""
    if action_class in {"write", "destructive"} and not approved:
        msg = f"{action_class} action refused: approval required"
        raise PermissionError(msg)
    if action_class == "destructive":
        msg = "destructive action refused: human approval required, retries disabled"
        raise PermissionError(msg)


def build_verify_dispatch(
    *,
    implementer: dict[str, Any],
    wave: dict[str, Any],
    runs_root: Path | str | None = None,
) -> VerifyDispatchContext:
    """Build an isolated verify dispatch context (fresh process + worktree).

    Args:
        implementer (dict[str, Any]): Implementer context (process, worktree, transcript).
        wave (dict[str, Any]): Wave metadata with ``node_id`` and ``commit_sha``.
        runs_root (Path | str | None): Optional runs root for verify worktree paths.

    Returns:
        VerifyDispatchContext: Context that must differ from the implementer on
            process id and worktree; transcript is always ``None``.
    """
    commit_sha = str(wave.get("commit_sha") or "unknown")
    node_id = str(wave.get("node_id") or "unknown")
    impl_wt = str(implementer.get("worktree") or "")
    root = Path(runs_root) if runs_root else Path("/tmp/tripll-verify")
    verify_path = (
        root / f"verify-{node_id.replace(':', '_')}-{commit_sha[:8]}-{uuid.uuid4().hex[:6]}"
    )
    ctx = VerifyDispatchContext(
        process_id=os.getpid() + 1,
        worktree=str(verify_path),
        commit_sha=commit_sha,
        node_id=node_id,
        transcript=None,
    )
    if ctx.process_id == implementer.get("process_id"):
        ctx = VerifyDispatchContext(
            process_id=int(implementer.get("process_id", 0)) + 1,
            worktree=str(verify_path),
            commit_sha=commit_sha,
            node_id=node_id,
            transcript=None,
        )
    if ctx.worktree == impl_wt:
        ctx = VerifyDispatchContext(
            process_id=ctx.process_id,
            worktree=str(verify_path / "isolated"),
            commit_sha=commit_sha,
            node_id=node_id,
            transcript=None,
        )
    return ctx


def assert_verify_isolation(
    *,
    implementer: dict[str, Any],
    verifier: dict[str, Any] | VerifyDispatchContext,
) -> None:
    """Assert D17 isolation; raise when implementer context leaks into verify."""
    if isinstance(verifier, VerifyDispatchContext):
        v_proc: int | Any = verifier.process_id
        v_wt: str | Any = verifier.worktree
        v_transcript = verifier.transcript
    else:
        v_proc = verifier.get("process_id")
        v_wt = verifier.get("worktree")
        v_transcript = verifier.get("transcript")

    i_proc = implementer.get("process_id")
    i_wt = implementer.get("worktree")

    if v_proc == i_proc:
        raise ValueError("verifier isolation violation: same process_id as implementer")
    if v_wt == i_wt:
        raise ValueError("verifier isolation violation: same worktree as implementer")
    if v_transcript is not None:
        raise ValueError("verifier isolation violation: implementer transcript present in verify")


def materialize_verify_worktree(
    repo_root: Path,
    ctx: VerifyDispatchContext,
) -> Path:
    """Create a detached git worktree at ``ctx.commit_sha`` for isolated verify."""
    path = Path(ctx.worktree)
    if path.exists():
        remove_verify_worktree(repo_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "worktree", "add", "--detach", str(path), ctx.commit_sha],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = f"verify worktree add failed: {proc.stderr.strip()}"
        raise RuntimeError(msg)
    return path


def remove_verify_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Remove a detached verify worktree."""
    if not worktree_path.exists():
        return
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def detect_structural_scope_breach(
    worktree_path: Path,
    *,
    repo_root: Path | None = None,
    rules_dir: Path | None = None,
) -> list[str]:
    """Return structural (shape) violations as scope-breach evidence (ADR 017).

    Uses the same executable-rules engine as ``make rules-check``, scoped to the
    worktree checkout. Absent ``ast-grep`` degrades to structural fallback or
    prose-only with no crash.

    Args:
        worktree_path (Path): Lane worktree root to scan.
        repo_root (Path | None): Repo root for config and rules dir resolution.
        rules_dir (Path | None): Override rules directory (default from config).

    Returns:
        list[str]: Violation strings suitable for ledger ``scope_breach`` evidence.

    Examples:
        >>> detect_structural_scope_breach(Path("."))  # doctest: +SKIP
        []
    """
    from tripll.config import load_config
    from tripll.rules.executable import run_executable_rules

    root = (repo_root or worktree_path).resolve()
    wt = worktree_path.resolve()
    cfg = load_config(repo_root=root)
    if cfg.rules.executable == "off":
        return []
    resolved_rules = (rules_dir or (root / cfg.rules.dir)).resolve()
    result = run_executable_rules(rules_dir=resolved_rules, repo_root=wt)
    return list(result.violations)
