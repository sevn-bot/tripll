"""Quality gauntlet inner loop — reference-driven polish (D26-D28)."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pathlib import Path

from tripll.harness.contracts import parse_outcome_contract, parse_quality_gauntlet_config
from tripll.loops.exits import NO_PROGRESS_STREAK, no_progress_exit

__all__ = [
    "QualityGauntletResult",
    "QualityVerdict",
    "Winner",
    "artifact_fingerprint",
    "capture_artifact_paths",
    "check_quality_exits",
    "evaluate_stop_condition",
    "parse_wave_outcome",
    "quality_gauntlet_enabled",
    "resolve_decomposition",
    "run_quality_gauntlet",
    "write_workbench_html",
]

QualityState = Literal["passed", "failed", "unverified", "skipped"]
Winner = Literal["build", "reference", "tie"]


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    round_num: int
    comparison: str
    winner: Winner
    gap: str
    artifact_paths: tuple[str, ...]
    reference_path: str
    exit_reason: str = ""


@dataclass(frozen=True, slots=True)
class QualityGauntletResult:
    passed: bool
    state: QualityState
    rounds: tuple[QualityVerdict, ...]
    exit_id: int | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)


def quality_gauntlet_enabled(outcome: dict[str, Any] | None) -> bool:
    if not outcome:
        return False
    quality = outcome.get("quality_gauntlet") or {}
    reference = outcome.get("reference") or {}
    if not quality.get("enabled"):
        return False
    return bool(
        str(reference.get("path") or "").strip() or str(reference.get("kind") or "").strip()
    )


def resolve_decomposition(*, wave_decomposition: str, quality: dict[str, Any]) -> str:
    if wave_decomposition in {"prescribed", "gauntlet"}:
        return wave_decomposition
    mode = str(quality.get("decomposition") or "prescribed")
    return mode if mode in {"prescribed", "gauntlet"} else "prescribed"


def _split_reference_path(raw: str) -> tuple[str, str]:
    if "#" in raw:
        base, anchor = raw.split("#", 1)
        return base, anchor
    return raw, ""


def capture_artifact_paths(
    *,
    repo_root: Path,
    worktree: Path,
    owned_paths: list[str],
    reference: dict[str, str],
) -> list[str]:
    captured: list[str] = []
    for rel in owned_paths:
        rel_clean = rel.rstrip("/")
        candidate = worktree / rel_clean
        if candidate.is_file():
            captured.append(rel_clean)
            continue
        if candidate.is_dir():
            for path in sorted(candidate.rglob("*")):
                if path.is_file() and not path.name.startswith("."):
                    captured.append(str(path.relative_to(worktree)))
    ref_raw = str(reference.get("path") or "")
    if ref_raw:
        ref_file, _anchor = _split_reference_path(ref_raw)
        ref_candidate = repo_root / ref_file
        if ref_candidate.is_file():
            captured.append(ref_file)
    return captured


def _artifact_fingerprint(worktree: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(paths):
        path = worktree / rel
        if path.is_file():
            digest.update(rel.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def artifact_fingerprint(worktree: Path, paths: list[str]) -> str:
    """Return a stable SHA-256 digest over *paths* file contents in *worktree*."""
    return _artifact_fingerprint(worktree, paths)


def evaluate_stop_condition(
    *,
    stop_when: str,
    verdict: QualityVerdict,
    round_num: int,
    max_rounds: int,
) -> tuple[bool, str]:
    mode = stop_when or "reference_wins"
    if mode == "reference_wins" and verdict.winner == "build":
        return True, "build output beats reference"
    if mode == "max_rounds" and round_num >= max_rounds:
        return True, f"max_rounds ({max_rounds}) reached"
    if mode == "operator":
        return False, "operator interrupt required"
    return False, ""


def check_quality_exits(
    *,
    round_num: int,
    max_rounds: int,
    sub_budget_spent: float,
    sub_budget_usd: float,
    artifact_hashes: list[str],
) -> int | None:
    if max_rounds > 0 and round_num > max_rounds:
        return 2
    if sub_budget_usd > 0 and sub_budget_spent >= sub_budget_usd:
        return 3
    if no_progress_exit(artifact_hashes, streak=NO_PROGRESS_STREAK):
        return 5
    return None


def write_workbench_html(
    *,
    run_dir: Path,
    node_id: str,
    rounds: list[QualityVerdict],
    reference: dict[str, str],
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "workbench.html"
    ref_path = html.escape(str(reference.get("path") or ""))
    ref_kind = html.escape(str(reference.get("kind") or ""))
    rows: list[str] = []
    for verdict in rounds:
        artifacts = ", ".join(html.escape(p) for p in verdict.artifact_paths) or "-"
        rows.append(
            "<tr>"
            f"<td>{verdict.round_num}</td>"
            f"<td>{html.escape(verdict.comparison)}</td>"
            f"<td>{html.escape(verdict.winner)}</td>"
            f"<td>{html.escape(verdict.gap or '-')}</td>"
            f"<td>{artifacts}</td>"
            f"<td>{html.escape(verdict.exit_reason or '-')}</td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan='6'>No quality rounds yet.</td></tr>"
    path.write_text(
        f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Quality workbench — {html.escape(node_id)}</title></head>
<body><h1>Quality gauntlet — {html.escape(node_id)}</h1>
<p>Reference: <code>{ref_kind}</code> @ <code>{ref_path}</code></p>
<table><thead><tr><th>Round</th><th>Comparison</th><th>Winner</th><th>Gap</th><th>Artifacts</th><th>Exit</th></tr></thead>
<tbody>{body}</tbody></table></body></html>""",
        encoding="utf-8",
    )
    (run_dir / "quality-rounds.json").write_text(
        json.dumps(
            [
                {
                    "round": v.round_num,
                    "comparison": v.comparison,
                    "winner": v.winner,
                    "gap": v.gap,
                    "artifact_paths": list(v.artifact_paths),
                    "reference_path": v.reference_path,
                    "exit_reason": v.exit_reason,
                }
                for v in rounds
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


CriticFn = Callable[[int, list[str], dict[str, str]], QualityVerdict | None]


def run_quality_gauntlet(
    *,
    repo_root: Path,
    run_dir: Path,
    worktree: Path,
    node_id: str,
    outcome: dict[str, Any],
    wave_decomposition: str = "",
    critic_verdict: CriticFn | None = None,
    sub_budget_spent: float = 0.0,
) -> QualityGauntletResult:
    if not quality_gauntlet_enabled(outcome):
        return QualityGauntletResult(passed=True, state="skipped", rounds=())

    reference = outcome.get("reference") or {}
    quality = outcome.get("quality_gauntlet") or {}
    max_rounds = int(quality.get("max_rounds") or 5)
    sub_budget = float(quality.get("sub_budget_usd") or 0.0)
    stop_when = str(reference.get("stop_when") or "reference_wins")
    comparison = str(reference.get("comparison") or "blind_ab")
    resolve_decomposition(wave_decomposition=wave_decomposition, quality=quality)

    if critic_verdict is None:
        return QualityGauntletResult(
            passed=False,
            state="unverified",
            rounds=(),
            reasons=("quality-critic unavailable — inner loop not run",),
        )

    rounds: list[QualityVerdict] = []
    artifact_hashes: list[str] = []
    round_num = 0
    while True:
        round_num += 1
        artifacts = capture_artifact_paths(
            repo_root=repo_root,
            worktree=worktree,
            owned_paths=outcome.get("_owned_paths") or [],
            reference=reference,
        )
        artifact_hashes.append(_artifact_fingerprint(worktree, artifacts))
        exit_id = check_quality_exits(
            round_num=round_num,
            max_rounds=max_rounds,
            sub_budget_spent=sub_budget_spent,
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
                run_dir=run_dir, node_id=node_id, rounds=rounds, reference=reference
            )
            return QualityGauntletResult(
                passed=False,
                state="failed",
                rounds=tuple(rounds),
                exit_id=exit_id,
                reasons=(f"quality gauntlet exit {exit_id} fired",),
            )

        raw_verdict = critic_verdict(round_num, artifacts, reference)
        if raw_verdict is None:
            write_workbench_html(
                run_dir=run_dir, node_id=node_id, rounds=rounds, reference=reference
            )
            return QualityGauntletResult(
                passed=False,
                state="unverified",
                rounds=tuple(rounds),
                reasons=("quality-critic returned no verdict",),
            )

        rounds.append(raw_verdict)
        write_workbench_html(run_dir=run_dir, node_id=node_id, rounds=rounds, reference=reference)
        should_stop, reason = evaluate_stop_condition(
            stop_when=stop_when,
            verdict=raw_verdict,
            round_num=round_num,
            max_rounds=max_rounds,
        )
        if should_stop:
            passed = raw_verdict.winner == "build" or stop_when == "max_rounds"
            return QualityGauntletResult(
                passed=passed,
                state="passed" if passed else "failed",
                rounds=tuple(rounds),
                reasons=(reason,) if reason else (),
            )


def parse_wave_outcome(
    raw: dict[str, Any] | None,
    *,
    owned_paths: list[str] | None = None,
    wave_decomposition: str = "",
) -> dict[str, Any]:
    parsed = parse_outcome_contract(raw)
    quality_raw = raw.get("quality_gauntlet") if isinstance(raw, dict) else None
    if isinstance(quality_raw, dict):
        parsed["quality_gauntlet"] = parse_quality_gauntlet_config(
            quality_raw,
            wave_decomposition=wave_decomposition,
        )
    if owned_paths:
        parsed["_owned_paths"] = list(owned_paths)
    return parsed
