"""Tests for L2-W5d orchestrator serial ``--after`` inject ordering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripll.engine import Engine
from tripll.graph import OrchestratorConfig, RunGraph, WaveNode, insert_orchestrator_serial_after
from tripll.inject import apply_hotfix_inject, merge_injected_artefacts
from tripll.ledger import get_wave, open_ledger, transition_wave
from tripll.parse import build_graph_from_dir
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl
from .test_engine import MarkingAdapter

_HOTFIX_PATH = "docs/orch-inject-hotfix.md"

_ORCH_PLAN = """# Orch inject demo

orchestrator_mode: serial

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `wave-orchestrator/src/tripll/demo/` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets |
|---------|-------|------------|-------------|--------|----------------|
| W1 | First | | | S | make lint |
| W2 | Second | W1 | | S | make lint |
| W3 | Third | W2 | W3.8 REVIEW GATE | S | make lint |
| W4 | Fourth | W3 | | S | make lint |

## Wave W1 — first

- [ ] **W1.1** Do first wave.

## Wave W2 — second

- [ ] **W2.1** Do second wave.

## Wave W3 — third

- [ ] **W3.1** Do third wave.

## Wave W4 — fourth

- [ ] **W4.1** Do fourth wave.
"""

_ORCH_PROMPT = """# Orchestrator prompt

Feature branch: `feature/tripll-test`

## Wave execution order

```text
W1 → W2 → W3 → W4
```

## Review gates

| Wave | Gate |
|------|------|
| W3 | W3.8 REVIEW GATE |

## Per-wave verify and commit

| Wave | Verify | Suggested commit |
|------|--------|------------------|
| W1 | partial-ci | feat(tripll): W1 |
| W2 | partial-ci | feat(tripll): W2 |
| W3 | partial-ci | feat(tripll): W3 |
| W4 | partial-ci | feat(tripll): W4 |

## MODEL POLICY

Do NOT pass `model` to wave-runner.

## REPORTING FORMAT

| Wave | Status | Branch | Commit | Evidence / blockers |
"""


def _seed_orchestrator_input(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "orch-inject"
    src.mkdir(parents=True)
    (src / "orch-inject-wave-plan.md").write_text(_ORCH_PLAN, encoding="utf-8")
    (src / "orch-inject-orchestrator-prompt.md").write_text(_ORCH_PROMPT, encoding="utf-8")
    return src


def _make_engine(tmp_path: Path, adapter: MarkingAdapter) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )


def _mark_done(rr: RunsRoot, run_id: str, node_ids: list[str]) -> None:
    with open_ledger(rr.ledger_path(run_id)) as lc:
        for node_id in node_ids:
            row = get_wave(lc, run_id, node_id)
            if row.state != "done":
                transition_wave(lc, run_id, node_id, "done")


def test_insert_orchestrator_serial_after_inserts_before_next_wave() -> None:
    graph = RunGraph(
        run_id="r",
        nodes={
            "p:W1": WaveNode("p:W1", "p", "plan.md", "W1", "l"),
            "p:W2": WaveNode("p:W2", "p", "plan.md", "W2", "l", depends_on=["p:W1"]),
            "p:W3": WaveNode("p:W3", "p", "plan.md", "W3", "l", depends_on=["p:W2"]),
            "p:W4": WaveNode("p:W4", "p", "plan.md", "W4", "l", depends_on=["p:W3"]),
        },
        orchestrator=OrchestratorConfig(
            True,
            "p.md",
            serial_waves=["W1", "W2", "W3", "W4"],
        ),
    )
    assert insert_orchestrator_serial_after(graph, "HF-1", "p:W3") is True
    assert graph.orchestrator is not None
    assert graph.orchestrator.serial_waves == ["W1", "W2", "W3", "HF-1", "W4"]


def test_insert_orchestrator_serial_after_idempotent() -> None:
    graph = RunGraph(
        run_id="r",
        nodes={"p:W1": WaveNode("p:W1", "p", "plan.md", "W1", "l")},
        orchestrator=OrchestratorConfig(True, "p.md", serial_waves=["W1", "HF-1", "W2"]),
    )
    assert insert_orchestrator_serial_after(graph, "HF-1", "p:W1") is True
    assert graph.orchestrator is not None
    assert graph.orchestrator.serial_waves == ["W1", "HF-1", "W2"]


@pytest.mark.asyncio
async def test_merge_injected_restores_serial_order_on_reparse(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_orchestrator_input(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)
    _mark_done(
        engine.runs_root,
        rid,
        ["orch-inject:W1", "orch-inject:W2", "orch-inject:W3"],
    )
    (run_dir / "pause-requested.md").write_text("# pause\n", encoding="utf-8")

    task = apply_hotfix_inject(
        engine.runs_root,
        rid,
        brief="Fix before W4",
        owned_paths=[_HOTFIX_PATH],
        after="W3",
    )
    graph_data = json.loads(engine.runs_root.graph_path(rid).read_text(encoding="utf-8"))
    assert graph_data["orchestrator"]["serial_waves"] == ["W1", "W2", "W3", "HF-1", "W4"]

    reparsed = build_graph_from_dir(run_dir, run_id=rid)
    assert reparsed.orchestrator is not None
    assert reparsed.orchestrator.serial_waves == ["W1", "W2", "W3", "W4"]
    restored = merge_injected_artefacts(reparsed, run_dir)
    assert restored.orchestrator is not None
    assert restored.orchestrator.serial_waves == ["W1", "W2", "W3", "HF-1", "W4"]
    assert task.node_id in restored.nodes


@pytest.mark.asyncio
async def test_hotfix_inject_after_w3_runs_before_w4(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_orchestrator_input(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)

    _mark_done(
        engine.runs_root,
        rid,
        ["orch-inject:W1", "orch-inject:W2", "orch-inject:W3"],
    )
    (run_dir / "pause-requested.md").write_text("# pause\n", encoding="utf-8")

    task = apply_hotfix_inject(
        engine.runs_root,
        rid,
        brief="Fix race before W4",
        owned_paths=[_HOTFIX_PATH],
        after="orch-inject:W3",
    )
    assert task.node_id == "hotfix:HF-1"

    adapter.dispatched = []
    adapter.calls = 0
    run_dir.joinpath("pause-requested.md").unlink(missing_ok=True)
    result = await engine.resume(rid)
    assert result.state == "done"
    assert adapter.dispatched == ["hotfix:HF-1", "orch-inject:W4"]


@pytest.mark.asyncio
async def test_hotfix_inject_does_not_add_review_gate(tmp_path: Path) -> None:
    adapter = MarkingAdapter()
    engine = _make_engine(tmp_path, adapter)
    src = _seed_orchestrator_input(engine.runs_root)
    started = await engine.start(src)
    approve_run_with_hitl(engine, started.run_id)
    rid = started.run_id
    run_dir = engine.runs_root.run_dir(rid)

    _mark_done(
        engine.runs_root,
        rid,
        ["orch-inject:W1", "orch-inject:W2", "orch-inject:W3"],
    )
    (run_dir / "pause-requested.md").write_text("# pause\n", encoding="utf-8")
    apply_hotfix_inject(
        engine.runs_root,
        rid,
        brief="No gate on hotfix",
        owned_paths=[_HOTFIX_PATH],
        after="W3",
    )

    graph_data = json.loads(engine.runs_root.graph_path(rid).read_text(encoding="utf-8"))
    review_gates = graph_data["orchestrator"]["review_gates"]
    assert review_gates.get("W3") == "W3.8"
    assert "HF-1" not in review_gates

    adapter.dispatched = []
    run_dir.joinpath("pause-requested.md").unlink(missing_ok=True)
    await engine.resume(rid)
    assert "orchestrator-gate" not in adapter.dispatched
