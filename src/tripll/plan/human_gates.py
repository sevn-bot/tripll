"""Human-gate policy — prompt, auto_accept, and fail modes with tier-4 canaries.

Exports:
    HumanGateMode — ``prompt`` | ``auto_accept`` | ``fail``.
    HumanGateOutcome — resolved gate action for the engine / CLI.
    resolve_human_gate_mode — read plan config with env override.
    pipeline_from_plan_text — parse ``[pipeline]`` from a v3 plan body.
    evaluate_ci_billing_canary — tier-4 check that CI has started.
    resolve_pre0_gate — combine mode, auto_acceptable flag, and canary result.
    pipeline_config_for_graph — read pipeline config from a run graph's plan files.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from tripll.skw.validate import extract_toml_block

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.graph import RunGraph

HumanGateMode = Literal["prompt", "auto_accept", "fail"]
_VALID_MODES = frozenset({"prompt", "auto_accept", "fail"})


class HumanGateOutcome(StrEnum):
    """Resolved Pre-0 human-gate action."""

    PROMPT = "prompt"
    PROCEED = "proceed"
    PARKED = "parked"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class CanaryResult:
    """Outcome of a tier-4 canary probe."""

    ok: bool
    detail: str
    run_id: str | None = None


def resolve_human_gate_mode(
    pipeline: dict[str, Any] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> HumanGateMode:
    """Resolve the human-gate mode from env override or plan pipeline config.

    Args:
        pipeline (dict[str, Any] | None): Parsed ``[pipeline]`` table from a v3 plan.
        env (dict[str, str] | None): Environment mapping (default ``os.environ``).

    Returns:
        HumanGateMode: Effective gate mode.

    Examples:
        >>> resolve_human_gate_mode({"human_gates": "fail"}, env={"TRIPLL_HUMAN_GATES": "auto_accept"})
        'auto_accept'
    """
    mapping = env if env is not None else os.environ
    override = mapping.get("TRIPLL_HUMAN_GATES", "").strip().lower()
    if override:
        if override not in _VALID_MODES:
            raise ValueError(
                f"invalid TRIPLL_HUMAN_GATES={override!r} — expected prompt|auto_accept|fail"
            )
        return override  # type: ignore[return-value]
    raw = (pipeline or {}).get("human_gates", "prompt")
    mode = str(raw).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid pipeline.human_gates={raw!r} — expected prompt|auto_accept|fail")
    return mode  # type: ignore[return-value]


def pipeline_from_plan_text(text: str) -> dict[str, Any]:
    """Return the ``[pipeline]`` table from a v3 plan markdown body.

    Args:
        text (str): Full plan markdown.

    Returns:
        dict[str, Any]: Pipeline table, or ``{}`` when absent.
    """
    data, _err = extract_toml_block(text)
    if not data:
        return {}
    pipeline = data.get("pipeline")
    return dict(pipeline) if isinstance(pipeline, dict) else {}


def pipeline_config_for_graph(graph: RunGraph, repo_root: Path) -> dict[str, Any]:
    """Read ``[pipeline]`` from the first resolvable plan file on *graph*.

    Args:
        graph (RunGraph): Parsed run graph.
        repo_root (Path): Repository root for resolving ``plan_file`` paths.

    Returns:
        dict[str, Any]: Pipeline table, or ``{}`` when none is found.
    """
    root = repo_root.resolve()
    for node in graph.nodes.values():
        plan_path = (root / node.plan_file).resolve()
        if plan_path.is_file():
            return pipeline_from_plan_text(plan_path.read_text(encoding="utf-8"))
    return {}


def evaluate_ci_billing_canary(*, env: dict[str, str] | None = None) -> CanaryResult:
    """Tier-4 canary: ``gh run list --workflow=CI --limit 1`` shows a started run.

    Args:
        env (dict[str, str] | None): Subprocess environment.

    Returns:
        CanaryResult: ``ok`` when the latest CI run has started (not blocked/queued forever).

    Examples:
        >>> isinstance(evaluate_ci_billing_canary(env={"PATH": "/usr/bin"}).ok, bool)
        True
    """
    mapping = env if env is not None else os.environ
    try:
        proc = subprocess.run(
            ["gh", "run", "list", "--workflow=CI", "--limit", "1", "--json", "status,databaseId"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=mapping,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CanaryResult(ok=False, detail=f"canary probe failed: {exc}")

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"gh exit {proc.returncode}"
        return CanaryResult(ok=False, detail=detail)

    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return CanaryResult(ok=False, detail=f"canary JSON parse failed: {exc}")

    if not rows:
        return CanaryResult(ok=False, detail="no CI runs found")

    row = rows[0]
    status = str(row.get("status", "")).lower()
    run_id = str(row.get("databaseId", "")) or None
    blocked = status in {"", "queued", "waiting", "requested", "pending"}
    if blocked:
        return CanaryResult(ok=False, detail=f"latest CI run status={status!r}", run_id=run_id)
    return CanaryResult(ok=True, detail=f"latest CI run status={status!r}", run_id=run_id)


def resolve_pre0_gate(
    *,
    mode: HumanGateMode,
    auto_acceptable: bool = True,
    canary: CanaryResult | None = None,
) -> HumanGateOutcome:
    """Resolve a Pre-0 gate under the configured human-gate mode.

    ``auto_accept`` skips the prompt but never skips a red tier-4 canary — those
    resolve to :attr:`HumanGateOutcome.PARKED`.

    Args:
        mode (HumanGateMode): Effective gate mode.
        auto_acceptable (bool): Whether the gate may be auto-accepted when mode allows.
        canary (CanaryResult | None): Tier-4 canary outcome (evaluated when supplied).

    Returns:
        HumanGateOutcome: Action for the engine / CLI.

    Examples:
        >>> resolve_pre0_gate(mode="fail")
        <HumanGateOutcome.FAIL: 'fail'>
        >>> resolve_pre0_gate(
        ...     mode="auto_accept",
        ...     canary=CanaryResult(ok=False, detail="blocked"),
        ... )
        <HumanGateOutcome.PARKED: 'parked'>
    """
    if mode == "fail":
        return HumanGateOutcome.FAIL
    if mode == "prompt":
        return HumanGateOutcome.PROMPT
    if not auto_acceptable:
        return HumanGateOutcome.PROMPT
    if canary is not None and not canary.ok:
        return HumanGateOutcome.PARKED
    return HumanGateOutcome.PROCEED
