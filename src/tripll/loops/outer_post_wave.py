"""L1 outer post-wave nodes — verify, commit, review, generate (L2 outer scaffold).

Each async invoker performs meaningful work after the ``waves`` node completes:
Final-batch gate verify, wave-completion manifest, ledger review audit, and
optional ``post-review-wave-generator`` dispatch when
``orchestrator.review_generate_cycle`` is enabled. Never auto-merges (D15).

Exports:
    OuterNodeResult — outcome dataclass for one post-wave node.
    outer_result_as_dict — serialize for LangGraph state.
    invoke_outer_verify_async — Final-batch gate verify.
    invoke_outer_commit_async — wave completion manifest (no git commit).
    invoke_outer_review_async — ledger wave audit.
    invoke_outer_generate_async — complete or generate-agent dispatch.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tripll.engine import Engine
    from tripll.loops.state import L1OuterState

__all__ = [
    "OuterNodeResult",
    "invoke_outer_commit_async",
    "invoke_outer_generate_async",
    "invoke_outer_review_async",
    "invoke_outer_verify_async",
    "outer_result_as_dict",
]


@dataclass(frozen=True, slots=True)
class OuterNodeResult:
    """Outcome of one L1 outer post-wave node.

    Args:
        node (str): Outer node name.
        ok (bool): Whether the step succeeded or may proceed.
        evidence (str): Human-readable outcome summary.
        extra (dict[str, Any]): Structured fields for LangGraph state.
    """

    node: str
    ok: bool
    evidence: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def outer_result_as_dict(result: OuterNodeResult) -> dict[str, Any]:
    """Serialize an outer post-wave node result for LangGraph state."""
    return asdict(result)


def _state_run_dir(state: L1OuterState) -> Path | None:
    raw = state.get("run_dir")
    if isinstance(raw, Path):
        return raw
    if isinstance(raw, str) and raw.strip():
        return Path(raw)
    return None


def _wave_dispatch_payload(state: L1OuterState) -> dict[str, Any]:
    raw = state.get("wave_dispatch")
    return raw if isinstance(raw, dict) else {}


def _resolve_run_dir(state: L1OuterState, engine: Engine, run_id: str) -> Path:
    found = engine.runs_root.find_run_dir(run_id)
    if found is not None:
        return found
    explicit = _state_run_dir(state)
    if explicit is not None and explicit.is_dir():
        return explicit
    return engine.runs_root.run_dir(run_id)


def _resolve_run_graph(run_dir: Path, run_id: str, *, engine: Engine) -> Any:
    active = getattr(engine, "_active_run_graph", None)
    if active is not None:
        return active
    from tripll.parse import build_graph_from_dir

    return build_graph_from_dir(run_dir, run_id=run_id)


def _collect_gate_targets(graph: Any) -> list[str]:
    targets: list[str] = []
    final_batch = next(
        (b for b in graph.batches if b.batch_id == "Final" and not b.is_human_gate),
        None,
    )
    batches = [final_batch] if final_batch is not None else list(graph.batches)
    for batch in batches:
        if batch is None or batch.is_human_gate:
            continue
        for cmd in batch.gate_commands or []:
            if cmd not in targets:
                targets.append(cmd)
    return targets or ["make ci-affected"]


def _append_outer_ledger_event(
    lc: Any,
    *,
    run_id: str,
    phase: str,
    metadata: dict[str, Any],
) -> None:
    from tripll.ledger import append_event

    append_event(
        lc,
        run_id=run_id,
        node_id="__loop__",
        phase=phase,
        metadata=json.dumps(metadata),
    )


def _simulation_stub(node: str, *, review_clean: bool = False) -> OuterNodeResult:
    extra: dict[str, Any] = {"skipped": True, "simulation": True}
    if node == "review":
        extra["review_clean"] = review_clean
    if node == "generate":
        extra["action"] = "complete"
    return OuterNodeResult(
        node=node,
        ok=True,
        evidence=f"{node} simulation stub",
        extra=extra,
    )


async def invoke_outer_verify_async(
    state: L1OuterState,
    *,
    engine: Engine | None = None,
) -> OuterNodeResult:
    """Run Final-batch gate targets after wave dispatch."""
    from tripll.loops import require_graph
    from tripll.loops.dispatch_bridge import resolve_engine_from_state

    require_graph(feature="L1 outer verify")
    if engine is None and _state_run_dir(state) is None:
        return _simulation_stub("verify")

    run_id = str(state.get("run_id") or state.get("thread_id") or "default")
    wave = _wave_dispatch_payload(state)
    if wave.get("paused") or wave.get("hitl_pending"):
        return OuterNodeResult(
            node="verify",
            ok=False,
            evidence="waves paused — verify skipped",
            extra={"skipped": True, "paused": True},
        )
    if wave.get("quota_pending") or wave.get("cost_pending"):
        return OuterNodeResult(
            node="verify",
            ok=False,
            evidence="waves paused for quota/cost — verify skipped",
            extra={"skipped": True, "paused": True},
        )
    wave_state = str(wave.get("state") or "")
    if wave_state and wave_state not in ("done",):
        return OuterNodeResult(
            node="verify",
            ok=False,
            evidence=f"waves state={wave_state!r} — verify skipped",
            extra={"skipped": True, "wave_state": wave_state},
        )

    eng = resolve_engine_from_state(state, engine=engine)
    run_dir = _resolve_run_dir(state, eng, run_id)
    graph = _resolve_run_graph(run_dir, run_id, engine=eng)
    targets = _collect_gate_targets(graph)
    ok, evidence = eng.verifier.verify(eng.repo_root, targets)

    metadata = {
        "ok": ok,
        "targets": targets,
        "evidence": evidence,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    ledger_path = run_dir / "ledger.db"
    if ledger_path.is_file():
        from tripll.ledger import open_ledger

        with open_ledger(ledger_path) as lc:
            _append_outer_ledger_event(lc, run_id=run_id, phase="outer_verify", metadata=metadata)

    return OuterNodeResult(
        node="verify",
        ok=ok,
        evidence=evidence,
        extra={"targets": targets, "skipped": False},
    )


async def invoke_outer_commit_async(
    state: L1OuterState,
    *,
    engine: Engine | None = None,
) -> OuterNodeResult:
    """Write wave-completion manifest (no auto-merge git commit)."""
    from tripll.loops import require_graph
    from tripll.loops.dispatch_bridge import resolve_engine_from_state

    require_graph(feature="L1 outer commit")
    if engine is None and _state_run_dir(state) is None:
        return _simulation_stub("commit")
    run_id = str(state.get("run_id") or state.get("thread_id") or "default")
    if not state.get("ci_green"):
        return OuterNodeResult(
            node="commit",
            ok=False,
            evidence="verify not green — commit skipped",
            extra={"skipped": True},
        )

    eng = resolve_engine_from_state(state, engine=engine)
    run_dir = _resolve_run_dir(state, eng, run_id)
    manifest_path = run_dir / "outer-commit.json"
    waves_payload: list[dict[str, str | int]] = []
    ledger_path = run_dir / "ledger.db"
    if ledger_path.is_file():
        from tripll.ledger import list_waves, open_ledger

        with open_ledger(ledger_path) as lc:
            waves_payload = [
                {
                    "node_id": w.node_id,
                    "wave_id": w.wave_id,
                    "state": w.state,
                    "attempts": w.attempt_count,
                }
                for w in list_waves(lc, run_id)
            ]
            metadata = {
                "waves": waves_payload,
                "waves_done": sum(1 for w in waves_payload if w["state"] == "done"),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            _append_outer_ledger_event(lc, run_id=run_id, phase="outer_commit", metadata=metadata)
    else:
        metadata = {
            "waves": waves_payload,
            "waves_done": 0,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return OuterNodeResult(
        node="commit",
        ok=True,
        evidence=f"manifest → {manifest_path.name}",
        extra={"manifest_path": str(manifest_path), "waves_done": metadata["waves_done"]},
    )


async def invoke_outer_review_async(
    state: L1OuterState,
    *,
    engine: Engine | None = None,
) -> OuterNodeResult:
    """Audit ledger wave rows and set review_clean."""
    from tripll.loops import require_graph
    from tripll.loops.dispatch_bridge import resolve_engine_from_state

    require_graph(feature="L1 outer review")
    if engine is None and _state_run_dir(state) is None:
        return _simulation_stub("review", review_clean=True)

    run_id = str(state.get("run_id") or state.get("thread_id") or "default")
    eng = resolve_engine_from_state(state, engine=engine)
    run_dir = _resolve_run_dir(state, eng, run_id)

    blocked: list[str] = []
    done: list[str] = []
    ledger_path = run_dir / "ledger.db"
    if ledger_path.is_file():
        from tripll.ledger import list_waves, open_ledger

        with open_ledger(ledger_path) as lc:
            for w in list_waves(lc, run_id):
                if w.state == "done":
                    done.append(w.node_id)
                elif w.state in ("blocked", "failed"):
                    blocked.append(w.node_id)
            review_clean = bool(done) and not blocked
            metadata = {
                "review_clean": review_clean,
                "done": done,
                "blocked": blocked,
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            _append_outer_ledger_event(lc, run_id=run_id, phase="outer_review", metadata=metadata)
    else:
        review_clean = bool(state.get("ci_green"))
        metadata = {
            "review_clean": review_clean,
            "done": done,
            "blocked": blocked,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    review_path = run_dir / "outer-review.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    evidence = "review clean" if review_clean else f"blocked={len(blocked)}"
    return OuterNodeResult(
        node="review",
        ok=review_clean,
        evidence=evidence,
        extra={
            "review_clean": review_clean,
            "blocked_count": len(blocked),
            "done_count": len(done),
            "review_path": str(review_path),
        },
    )


async def invoke_outer_generate_async(
    state: L1OuterState,
    *,
    engine: Engine | None = None,
    adapter: Any | None = None,
) -> OuterNodeResult:
    """Complete the outer loop or dispatch post-review-wave-generator."""
    from tripll.loops import require_graph
    from tripll.loops.dispatch_bridge import (
        dispatch_results_as_dicts,
        invoke_loop_dispatches,
        resolve_engine_from_state,
    )

    require_graph(feature="L1 outer generate")
    if engine is None and _state_run_dir(state) is None:
        return _simulation_stub("generate")

    run_id = str(state.get("run_id") or state.get("thread_id") or "default")
    review_clean = bool(state.get("review_clean"))
    eng = resolve_engine_from_state(state, engine=engine)
    run_dir = _resolve_run_dir(state, eng, run_id)
    graph = _resolve_run_graph(run_dir, run_id, engine=eng)
    orch = graph.orchestrator
    cycle = bool(orch is not None and getattr(orch, "review_generate_cycle", False))

    action = "complete"
    dispatch_results: list[dict[str, Any]] = []
    if not review_clean and cycle:
        dispatch_meta = [
            {
                "agent": "post-review-wave-generator",
                "action": "generate",
                "finding_id": None,
                "kind": "review",
            }
        ]
        results = invoke_loop_dispatches(
            {**state, "run_dir": str(run_dir)},
            dispatch_meta,
            node="generate",
            adapter=adapter,
        )
        dispatch_results = dispatch_results_as_dicts(results)
        action = "generate"
        evidence = f"dispatched generate ({results[0].outcome if results else 'none'})"
        ok = bool(results) and results[0].outcome == "done"
    else:
        ok = review_clean or not cycle
        evidence = "outer loop complete" if review_clean else "generate skipped (no cycle)"

    metadata = {
        "action": action,
        "review_clean": review_clean,
        "cycle": cycle,
        "ok": ok,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    ledger_path = run_dir / "ledger.db"
    if ledger_path.is_file():
        from tripll.ledger import open_ledger

        with open_ledger(ledger_path) as lc:
            _append_outer_ledger_event(lc, run_id=run_id, phase="outer_generate", metadata=metadata)

    generate_path = run_dir / "outer-generate.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    generate_path.write_text(
        json.dumps({**metadata, "dispatch_results": dispatch_results}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return OuterNodeResult(
        node="generate",
        ok=ok,
        evidence=evidence,
        extra={
            "action": action,
            "cycle": cycle,
            "dispatch_results": dispatch_results,
            "generate_path": str(generate_path),
        },
    )
