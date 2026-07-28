"""Isolated quality-critic and smoothing-pass adapter dispatch (D27).

LangGraph inner sub-graph for the quality loop is **deferred** — the engine micro-loop in
:func:`run_quality_gauntlet` / :func:`run_quality_gauntlet_live` handles rounds directly.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tripll.harness.boundary import (
    VerifyDispatchContext,
    assert_verify_isolation,
    build_verify_dispatch,
    materialize_verify_worktree,
    remove_verify_worktree,
)
from tripll.harness.quality import (
    QualityGauntletResult,
    QualityVerdict,
    Winner,
    artifact_fingerprint,
    capture_artifact_paths,
    check_quality_exits,
    evaluate_stop_condition,
    quality_gauntlet_enabled,
    write_workbench_html,
)

if TYPE_CHECKING:
    from tripll.adapters.base import AgentAdapter
    from tripll.graph import WaveNode

__all__ = [
    "QualityDispatchResult",
    "build_quality_critic_brief",
    "build_smoothing_brief",
    "dispatch_quality_critic_round",
    "dispatch_smoothing_pass",
    "parse_quality_verdict",
    "render_quality_critic_prompt",
    "render_smoothing_pass_prompt",
    "resolve_quality_adapter",
    "run_quality_gauntlet_live",
]

QUALITY_CRITIC_AGENT = "quality-critic"
SMOOTHING_PASS_AGENT = "smoothing-pass"
QUALITY_VERDICT_FILENAME = "quality-verdict.json"
SMOOTHING_VERDICT_FILENAME = "smoothing-verdict.json"
_DEFAULT_TIMEOUT_S = 600
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\"winner\"[^{}]*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class QualityDispatchResult:
    """Outcome of one isolated quality-critic or smoothing-pass dispatch."""

    outcome: str
    verdict: QualityVerdict | None = None
    result_text: str = ""
    cost_usd: float = 0.0


def _kit_prompt_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "skw" / "prompts" / f"{name}.md"


def _substitute(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace(f"{{{{{key}}}}}", value)
    return out


def render_quality_critic_prompt(
    *,
    round_num: int,
    comparison: str,
    reference: dict[str, str],
    artifact_paths: list[str],
    worktree_path: Path,
    verdict_path: Path,
) -> str:
    """Render ``prompts/quality-critic.md`` for one inner-loop round."""
    template = _kit_prompt_path("quality-critic").read_text(encoding="utf-8")
    artifacts_block = "\n".join(f"- `{p}`" for p in artifact_paths) or "(none captured)"
    mapping = {
        "ROUND_NUM": str(round_num),
        "COMPARISON": comparison,
        "REFERENCE_KIND": str(reference.get("kind") or ""),
        "REFERENCE_PATH": str(reference.get("path") or ""),
        "STOP_WHEN": str(reference.get("stop_when") or "reference_wins"),
        "ARTIFACT_PATHS": artifacts_block,
        "WORKTREE_PATH": str(worktree_path),
        "VERDICT_PATH": str(verdict_path),
    }
    return _substitute(template, mapping)


def render_smoothing_pass_prompt(
    *,
    wave_id: str,
    owned_paths: list[str],
    worktree_path: Path,
    quality_rounds: int,
    reference_path: str,
    verdict_path: Path,
) -> str:
    """Render ``prompts/smoothing-pass.md`` for the post-gauntlet consistency pass."""
    template = _kit_prompt_path("smoothing-pass").read_text(encoding="utf-8")
    owned = ", ".join(owned_paths) or "(none)"
    mapping = {
        "WAVE_ID": wave_id,
        "OWNED_PATHS": owned,
        "WORKTREE_PATH": str(worktree_path),
        "QUALITY_ROUNDS": str(quality_rounds),
        "REFERENCE_PATH": reference_path or "(none)",
        "VERDICT_PATH": str(verdict_path),
    }
    return _substitute(template, mapping)


def resolve_quality_adapter(
    *,
    run_dir: Path,
    agent: str,
    adapter_override: AgentAdapter | None = None,
) -> AgentAdapter:
    """Resolve an adapter for *agent* from run dispatch config (D27)."""
    if adapter_override is not None:
        return adapter_override
    from tripll.adapters import build_adapter
    from tripll.adapters.options import BackendOptions
    from tripll.run_dispatch import read_dispatch_config

    backend = "cursor_local"
    model: str | None = None
    cfg = read_dispatch_config(run_dir)
    if cfg is not None:
        backend = cfg.backend
        model = cfg.model
    return build_adapter(backend, options=BackendOptions(model=model, agent=agent))


def _isolated_critic_worktree(
    *,
    repo_root: Path,
    runs_root: Path,
    node_id: str,
    commit_sha: str,
    implementer_worktree: Path,
) -> tuple[Path, VerifyDispatchContext | None]:
    """Materialize an isolated worktree for critic inspection (D17/D27)."""
    implementer = {
        "process_id": os.getpid(),
        "worktree": str(implementer_worktree),
        "transcript": None,
    }
    ctx = build_verify_dispatch(
        implementer=implementer,
        wave={"node_id": node_id, "commit_sha": commit_sha or "HEAD"},
        runs_root=runs_root / "quality-wts",
    )
    assert_verify_isolation(implementer=implementer, verifier=ctx)
    if commit_sha and commit_sha not in {"", "unknown", "HEAD"}:
        try:
            return materialize_verify_worktree(repo_root, ctx), ctx
        except RuntimeError:
            return implementer_worktree, None
    return implementer_worktree, None


def build_quality_critic_brief(
    *,
    run_id: str,
    node_id: str,
    wave_id: str,
    round_num: int,
    comparison: str,
    reference: dict[str, str],
    artifact_paths: list[str],
    worktree_path: Path,
    run_dir: Path,
    owned_paths: list[str],
) -> dict[str, object]:
    """Build an isolated dispatch brief for ``quality-critic`` (no implementer transcript)."""
    verdict_path = run_dir / f"quality-round-{round_num}-{QUALITY_VERDICT_FILENAME}"
    prompt = render_quality_critic_prompt(
        round_num=round_num,
        comparison=comparison,
        reference=reference,
        artifact_paths=artifact_paths,
        worktree_path=worktree_path,
        verdict_path=verdict_path,
    )
    scope = sorted({*artifact_paths, *owned_paths})
    ref_raw = str(reference.get("path") or "")
    if ref_raw and "#" in ref_raw:
        ref_raw = ref_raw.split("#", 1)[0]
    if ref_raw and ref_raw not in scope:
        scope.append(ref_raw)
    return {
        "node_id": f"{node_id}:quality:round-{round_num}",
        "wave_id": wave_id,
        "plan_file": "quality-gauntlet",
        "plan_worktree_path": "",
        "branch": f"quality/{run_id}",
        "worktree_path": str(worktree_path),
        "owned_paths": [],
        "forbidden_paths": owned_paths,
        "workspace_scope": scope,
        "verify_targets": [],
        "prerequisite_waves": [],
        "locked_decisions": [],
        "manual_smoke_deferred": [],
        "agent_directives": [
            "D17/D27 isolation — no implementer transcript; inspect artifacts only.",
            f"Write verdict JSON to {verdict_path}.",
            "One gap per round when reference wins.",
        ],
        "agent": QUALITY_CRITIC_AGENT,
        "run_id": run_id,
        "quality_round": round_num,
        "reference": reference,
        "artifact_paths": artifact_paths,
        "_prompt_override": prompt,
    }


def build_smoothing_brief(
    *,
    run_id: str,
    node_id: str,
    wave_id: str,
    owned_paths: list[str],
    worktree_path: Path,
    run_dir: Path,
    quality_rounds: int,
    reference_path: str,
) -> dict[str, object]:
    """Build a dispatch brief for ``smoothing-pass`` after the quality loop."""
    verdict_path = run_dir / SMOOTHING_VERDICT_FILENAME
    prompt = render_smoothing_pass_prompt(
        wave_id=wave_id,
        owned_paths=owned_paths,
        worktree_path=worktree_path,
        quality_rounds=quality_rounds,
        reference_path=reference_path,
        verdict_path=verdict_path,
    )
    return {
        "node_id": f"{node_id}:smooth",
        "wave_id": wave_id,
        "plan_file": "quality-gauntlet",
        "plan_worktree_path": "",
        "branch": f"quality/{run_id}",
        "worktree_path": str(worktree_path),
        "owned_paths": owned_paths,
        "forbidden_paths": ["tests/"],
        "workspace_scope": list(owned_paths),
        "verify_targets": [],
        "prerequisite_waves": [],
        "locked_decisions": [],
        "manual_smoke_deferred": [],
        "agent_directives": [
            "Post-gauntlet consistency only — no redesign, no test edits.",
            f"Write verdict JSON to {verdict_path}.",
            "Leave changes staged; do not commit.",
        ],
        "agent": SMOOTHING_PASS_AGENT,
        "run_id": run_id,
        "_prompt_override": prompt,
    }


def _normalise_winner(raw: object) -> Winner:
    value = str(raw or "").strip().lower()
    if value in {"build", "reference", "tie"}:
        return value  # type: ignore[return-value]
    if value in {"a", "b"}:
        return "build" if value == "a" else "reference"
    return "reference"


def parse_quality_verdict(
    result_text: str,
    *,
    round_num: int,
    comparison: str,
    reference_path: str,
    artifact_paths: tuple[str, ...],
    verdict_path: Path | None = None,
) -> QualityVerdict | None:
    """Parse a ``quality-critic`` JSON verdict from adapter output or disk."""
    payload: dict[str, Any] | None = None
    if verdict_path is not None and verdict_path.is_file():
        try:
            loaded = json.loads(verdict_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        for candidate in (result_text, *_JSON_BLOCK_RE.findall(result_text)):
            try:
                loaded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict) and "winner" in loaded:
                payload = loaded
                break
    if payload is None:
        return None
    paths_raw = payload.get("artifact_paths")
    paths: tuple[str, ...] = artifact_paths
    if isinstance(paths_raw, list):
        paths = tuple(str(p) for p in paths_raw if str(p).strip()) or artifact_paths
    winner_str = _normalise_winner(payload.get("winner"))
    return QualityVerdict(
        round_num=int(payload.get("round") or round_num),
        comparison=str(payload.get("comparison") or comparison),
        winner=winner_str,
        gap=str(payload.get("gap") or ""),
        artifact_paths=paths,
        reference_path=str(payload.get("reference_path") or reference_path),
    )


async def dispatch_quality_critic_round(
    *,
    adapter: AgentAdapter,
    brief: dict[str, object],
    worktree_path: Path,
    run_dir: Path,
    round_num: int,
    comparison: str,
    reference_path: str,
    artifact_paths: tuple[str, ...],
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> QualityDispatchResult:
    """Dispatch one isolated ``quality-critic`` round via *adapter*."""
    log_dir = run_dir / "logs" / "quality"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"round-{round_num}.log"
    verdict_path = run_dir / f"quality-round-{round_num}-{QUALITY_VERDICT_FILENAME}"

    result = await adapter.dispatch(
        brief,
        worktree_path=worktree_path,
        log_path=log_path,
        timeout_s=timeout_s,
        log_header={
            "run_id": str(brief.get("run_id") or ""),
            "node_id": str(brief.get("node_id") or ""),
            "backend": adapter.name,
            "agent": QUALITY_CRITIC_AGENT,
        },
    )
    verdict = parse_quality_verdict(
        result.result_text or "",
        round_num=round_num,
        comparison=comparison,
        reference_path=reference_path,
        artifact_paths=artifact_paths,
        verdict_path=verdict_path,
    )
    return QualityDispatchResult(
        outcome=result.outcome,
        verdict=verdict,
        result_text=result.result_text or "",
        cost_usd=float(result.cost_usd or 0.0),
    )


async def dispatch_smoothing_pass(
    *,
    adapter: AgentAdapter,
    brief: dict[str, object],
    worktree_path: Path,
    run_dir: Path,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> tuple[bool, str]:
    """Dispatch ``smoothing-pass`` after the quality loop."""
    log_dir = run_dir / "logs" / "quality"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "smoothing-pass.log"
    verdict_path = run_dir / SMOOTHING_VERDICT_FILENAME

    result = await adapter.dispatch(
        brief,
        worktree_path=worktree_path,
        log_path=log_path,
        timeout_s=timeout_s,
        log_header={
            "run_id": str(brief.get("run_id") or ""),
            "node_id": str(brief.get("node_id") or ""),
            "backend": adapter.name,
            "agent": SMOOTHING_PASS_AGENT,
        },
    )
    if result.outcome != "done":
        return False, result.result_text or "smoothing-pass dispatch failed"
    summary = "smoothing-pass complete"
    if verdict_path.is_file():
        try:
            payload = json.loads(verdict_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                summary = str(payload.get("summary") or summary)
        except json.JSONDecodeError:
            pass
    elif result.result_text:
        summary = result.result_text[:200]
    return True, summary


async def run_quality_gauntlet_live(
    *,
    repo_root: Path,
    run_dir: Path,
    run_id: str,
    worktree: Path,
    node: WaveNode,
    outcome: dict[str, Any],
    commit_sha: str,
    adapter: AgentAdapter,
    adapter_override: AgentAdapter | None = None,
    sub_budget_spent: float = 0.0,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> QualityGauntletResult:
    """Run the quality inner loop with live ``quality-critic`` adapter rounds (D27)."""
    if not quality_gauntlet_enabled(outcome):
        return QualityGauntletResult(passed=True, state="skipped", rounds=())

    reference = outcome.get("reference") or {}
    quality = outcome.get("quality_gauntlet") or {}
    max_rounds = int(quality.get("max_rounds") or 5)
    sub_budget = float(quality.get("sub_budget_usd") or 0.0)
    stop_when = str(reference.get("stop_when") or "reference_wins")
    comparison = str(reference.get("comparison") or "blind_ab")
    owned_paths = list(outcome.get("_owned_paths") or node.owned_paths)

    critic_adapter = resolve_quality_adapter(
        run_dir=run_dir,
        agent=QUALITY_CRITIC_AGENT,
        adapter_override=adapter_override or adapter,
    )

    isolated_path, isolated_ctx = _isolated_critic_worktree(
        repo_root=repo_root,
        runs_root=run_dir,
        node_id=node.node_id,
        commit_sha=commit_sha,
        implementer_worktree=worktree,
    )

    rounds: list[QualityVerdict] = []
    artifact_hashes: list[str] = []
    round_num = 0
    budget_spent = sub_budget_spent

    try:
        while True:
            round_num += 1
            artifacts = capture_artifact_paths(
                repo_root=repo_root,
                worktree=worktree,
                owned_paths=owned_paths,
                reference=reference,
            )
            artifact_hashes.append(artifact_fingerprint(worktree, artifacts))
            exit_id = check_quality_exits(
                round_num=round_num,
                max_rounds=max_rounds,
                sub_budget_spent=budget_spent,
                sub_budget_usd=sub_budget,
                artifact_hashes=artifact_hashes,
            )
            if exit_id is not None:
                rounds.append(
                    QualityVerdict(
                        round_num=round_num,
                        comparison=comparison,
                        winner="reference",
                        gap="",
                        artifact_paths=tuple(artifacts),
                        reference_path=str(reference.get("path") or ""),
                        exit_reason=f"exit {exit_id} fired",
                    )
                )
                write_workbench_html(
                    run_dir=run_dir,
                    node_id=node.node_id,
                    rounds=rounds,
                    reference=reference,
                )
                return QualityGauntletResult(
                    passed=False,
                    state="failed",
                    rounds=tuple(rounds),
                    exit_id=exit_id,
                    reasons=(f"quality gauntlet exit {exit_id} fired",),
                )

            brief = build_quality_critic_brief(
                run_id=run_id,
                node_id=node.node_id,
                wave_id=node.wave_id,
                round_num=round_num,
                comparison=comparison,
                reference=reference,
                artifact_paths=artifacts,
                worktree_path=isolated_path,
                run_dir=run_dir,
                owned_paths=owned_paths,
            )
            dispatch = await dispatch_quality_critic_round(
                adapter=critic_adapter,
                brief=brief,
                worktree_path=isolated_path,
                run_dir=run_dir,
                round_num=round_num,
                comparison=comparison,
                reference_path=str(reference.get("path") or ""),
                artifact_paths=tuple(artifacts),
                timeout_s=timeout_s,
            )
            budget_spent += dispatch.cost_usd
            if dispatch.verdict is None:
                write_workbench_html(
                    run_dir=run_dir,
                    node_id=node.node_id,
                    rounds=rounds,
                    reference=reference,
                )
                return QualityGauntletResult(
                    passed=False,
                    state="unverified",
                    rounds=tuple(rounds),
                    reasons=("quality-critic returned no verdict",),
                )
            if dispatch.outcome != "done":
                write_workbench_html(
                    run_dir=run_dir,
                    node_id=node.node_id,
                    rounds=rounds,
                    reference=reference,
                )
                return QualityGauntletResult(
                    passed=False,
                    state="unverified",
                    rounds=tuple(rounds),
                    reasons=(f"quality-critic dispatch: {dispatch.outcome}",),
                )

            rounds.append(dispatch.verdict)
            write_workbench_html(
                run_dir=run_dir,
                node_id=node.node_id,
                rounds=rounds,
                reference=reference,
            )
            should_stop, reason = evaluate_stop_condition(
                stop_when=stop_when,
                verdict=dispatch.verdict,
                round_num=round_num,
                max_rounds=max_rounds,
            )
            if should_stop:
                passed = dispatch.verdict.winner == "build" or stop_when == "max_rounds"
                return QualityGauntletResult(
                    passed=passed,
                    state="passed" if passed else "failed",
                    rounds=tuple(rounds),
                    reasons=(reason,) if reason else (),
                )
    finally:
        if isolated_ctx is not None:
            remove_verify_worktree(repo_root, isolated_path)
