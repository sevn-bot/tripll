"""Verify and quality-gauntlet helpers extracted from :class:`~tripll.engine.Engine`.

Exports:
    VERIFY_ONLY_RETRIES — verify-only retry budget (no re-dispatch).
    verify_with_retries — run verify targets with transient-flap retries.
    run_isolated_verify — dispatch isolated verify and clean up the worktree.
    run_quality_gauntlet — optional quality inner loop before isolated verify.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

from tripll.harness.boundary import (
    assert_verify_isolation,
    build_verify_dispatch,
    materialize_verify_worktree,
    remove_verify_worktree,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.adapters.base import AgentAdapter
    from tripll.engine_worktrees import Verifier
    from tripll.graph import WaveNode
    from tripll.pipeline import RunsRoot
    from tripll.worktrees import Worktree

VERIFY_ONLY_RETRIES = 2


def verify_with_retries(
    verifier: Verifier,
    worktree_path: Path,
    targets: list[str],
) -> tuple[bool, str]:
    """Run verify targets with transient-flap retries (verify-only, no re-dispatch).

    Args:
        verifier (Verifier): Worktree verifier implementation.
        worktree_path (Path): Path to run verify targets in.
        targets (list[str]): Makefile verify targets.

    Returns:
        tuple[bool, str]: Success flag and evidence string.
    """
    evidence = ""
    for attempt in range(VERIFY_ONLY_RETRIES + 1):
        ok, evidence = verifier.verify(worktree_path, targets)
        if ok:
            return True, evidence
        if attempt < VERIFY_ONLY_RETRIES:
            logger.info(
                "engine: verify retry {}/{} — {}",
                attempt + 1,
                VERIFY_ONLY_RETRIES,
                evidence[:120],
            )
    return False, evidence


def run_isolated_verify(
    *,
    verifier: Verifier,
    repo_root: Path,
    runs_root: RunsRoot,
    run_id: str,
    node: WaveNode,
    implementer_worktree: Path,
    commit_sha: str,
    targets: list[str],
    transcript: str = "",
) -> tuple[bool, str]:
    """Dispatch isolated verify and always clean up the verify worktree.

    Args:
        verifier (Verifier): Worktree verifier implementation.
        repo_root (Path): Main repository checkout.
        runs_root (RunsRoot): Configured runs root.
        run_id (str): Run identifier.
        node (WaveNode): Wave node under verify.
        implementer_worktree (Path): Implementer lane worktree path.
        commit_sha (str): Checkpoint SHA to verify (or ``HEAD``).
        targets (list[str]): Makefile verify targets.
        transcript (str): Optional dispatch transcript for isolation audit.

    Returns:
        tuple[bool, str]: Success flag and evidence string.
    """
    verify_path: Path | None = None
    implementer = {
        "process_id": os.getpid(),
        "worktree": str(implementer_worktree),
        "transcript": transcript or None,
    }
    verify_ctx = build_verify_dispatch(
        implementer=implementer,
        wave={"node_id": node.node_id, "commit_sha": commit_sha or "HEAD"},
        runs_root=runs_root.run_dir(run_id) / "verify-wts",
    )
    assert_verify_isolation(implementer=implementer, verifier=verify_ctx)
    run_path = implementer_worktree
    if commit_sha and commit_sha not in {"", "unknown", "HEAD"}:
        try:
            run_path = materialize_verify_worktree(repo_root, verify_ctx)
            verify_path = run_path
        except RuntimeError as exc:
            logger.warning("engine: isolated verify worktree failed — {}", exc)
    try:
        return verify_with_retries(verifier, run_path, targets)
    finally:
        if verify_path is not None:
            remove_verify_worktree(repo_root, verify_path)


async def run_quality_gauntlet(
    *,
    adapter: AgentAdapter,
    repo_root: Path,
    runs_root: RunsRoot,
    last_checkpoint_sha: str,
    run_id: str,
    node: WaveNode,
    worktree: Worktree,
    outcome: dict[str, object],
) -> tuple[bool, str]:
    """Run optional quality inner loop before isolated verify (D26-D28).

    Args:
        adapter (AgentAdapter): Primary dispatch adapter.
        repo_root (Path): Main repository checkout.
        runs_root (RunsRoot): Configured runs root.
        last_checkpoint_sha (str): Latest checkpoint SHA for the wave.
        run_id (str): Run identifier.
        node (WaveNode): Wave node under verify.
        worktree (Worktree): Lane worktree handle.
        outcome (dict[str, object]): Parsed agent outcome payload.

    Returns:
        tuple[bool, str]: Success flag and evidence string.
    """
    from tripll.harness.quality_dispatch import (
        build_smoothing_brief,
        dispatch_smoothing_pass,
        resolve_quality_adapter,
        run_quality_gauntlet_live,
    )

    run_dir = runs_root.run_dir(run_id)
    quality_raw = outcome.get("quality_gauntlet")
    quality = quality_raw if isinstance(quality_raw, dict) else {}
    reference_raw = outcome.get("reference")
    reference = reference_raw if isinstance(reference_raw, dict) else {}

    result = await run_quality_gauntlet_live(
        repo_root=repo_root,
        run_dir=run_dir,
        run_id=run_id,
        worktree=worktree.path,
        node=node,
        outcome=dict(outcome),
        commit_sha=last_checkpoint_sha,
        adapter=adapter,
    )
    if result.state == "skipped":
        return True, ""
    if result.state == "unverified":
        return False, "; ".join(result.reasons) or "quality gauntlet unverified"
    if not result.passed:
        return False, "; ".join(result.reasons) or "quality gauntlet failed"

    evidence = f"quality gauntlet passed ({len(result.rounds)} round(s))"
    if bool(quality.get("smoothing")):
        smooth_adapter = resolve_quality_adapter(
            run_dir=run_dir,
            agent="smoothing-pass",
            adapter_override=adapter,
        )
        smooth_brief = build_smoothing_brief(
            run_id=run_id,
            node_id=node.node_id,
            wave_id=node.wave_id,
            owned_paths=list(node.owned_paths),
            worktree_path=worktree.path,
            run_dir=run_dir,
            quality_rounds=len(result.rounds),
            reference_path=str(reference.get("path") or ""),
        )
        smooth_ok, smooth_evidence = await dispatch_smoothing_pass(
            adapter=smooth_adapter,
            brief=smooth_brief,
            worktree_path=worktree.path,
            run_dir=run_dir,
            timeout_s=node.wall_clock_limit_s,
        )
        if not smooth_ok:
            return False, smooth_evidence or "smoothing-pass failed"
        evidence = f"{evidence}; {smooth_evidence}"
    return True, evidence
