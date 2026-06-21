"""Engine tests for orchestrator serial mode (W2.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.brief import extract_wave_summary, orchestrator_directives, render_dispatch_prompt
from tripll.engine import Engine, orchestrator_serial_nodes
from tripll.graph import OrchestratorConfig, RunGraph, WaveNode
from tripll.orchestrator_status import read_latest
from tripll.pipeline import RunsRoot

from ._dev_eval import DEV_EVAL, copy_dev_eval_input
from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager
from .hitl_helpers import approve_run_with_hitl
from .test_engine import MarkingAdapter, _make_engine

_ORCH_PLAN = """# Orch demo

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

## Wave W1 — first

- [ ] **W1.1** Do first wave.

## Wave W2 — second

- [ ] **W2.1** Do second wave.
"""

_ORCH_PROMPT = """# Orchestrator prompt

Feature branch: `feature/tripll-test`

## Wave execution order

```text
W1 → W2
```

## Per-wave verify and commit

| Wave | Verify | Suggested commit |
|------|--------|------------------|
| W1 | partial-ci | feat(tripll): W1 |
| W2 | partial-ci | feat(tripll): W2 |

## MODEL POLICY

Do NOT pass `model` to wave-runner.

## REPORTING FORMAT

| Wave | Status | Branch | Commit | Evidence / blockers |
"""


def _seed_orchestrator_input(rr: RunsRoot) -> Path:
    rr.init()
    src = rr.input_dir / "orch-demo"
    src.mkdir(parents=True)
    (src / "orch-demo-wave-plan.md").write_text(_ORCH_PLAN)
    (src / "orch-demo-orchestrator-prompt.md").write_text(_ORCH_PROMPT)
    return src


class SummaryAdapter(MarkingAdapter):
    """Returns structured wave-complete markdown for summary extraction."""

    async def dispatch(self, brief, **kwargs):  # type: ignore[no-untyped-def]
        result = await super().dispatch(brief, **kwargs)
        wave_id = str(brief.get("wave_id", ""))
        if result.outcome == "done":
            return result.__class__(
                outcome=result.outcome,
                result_text=f"## Wave {wave_id} complete\n\nAll good.",
                returncode=result.returncode,
                log_path=result.log_path,
                argv=result.argv,
            )
        return result


def test_orchestrator_directives_include_partial_ci() -> None:
    cfg = OrchestratorConfig(True, "p.md", "feature/x", ci_base="origin/test-pre")
    lines = orchestrator_directives(cfg, "W1", commit_subject="feat(tripll): W1")
    assert any("partial-ci" in line for line in lines)
    assert any("commit-msg-check" in line for line in lines)


def test_extract_wave_summary_first_h2() -> None:
    text = "## Wave W1 complete\n\nDone.\n\n## Other\nNope."
    assert extract_wave_summary(text).startswith("## Wave W1 complete")


def test_render_dispatch_prompt_orchestrator_context() -> None:
    brief = {
        "wave_id": "W2",
        "plan_worktree_path": "/wt/plan.md",
        "branch": "feature/x",
        "worktree_path": "/wt",
        "owned_paths": ["src/a.py"],
        "forbidden_paths": [],
        "verify_targets": ["make lint"],
        "node_id": "p:W2",
        "plan_file": "p.md",
        "prerequisite_waves": ["p:W1"],
        "workspace_scope": ["src/a.py"],
        "agent_directives": ["Commit and push."],
        "orchestrator_context": {"feature_branch": "feature/x", "ci_base": "origin/test-pre"},
        "prior_wave_commits": {"W1": "abc123def456"},
    }
    prompt = render_dispatch_prompt(brief)
    assert "integration branch: `feature/x`" in prompt
    assert "W1=abc123def456" in prompt


def test_orchestrator_serial_nodes_order() -> None:
    graph = RunGraph(
        run_id="r",
        nodes={
            "p:W1": WaveNode("p:W1", "p", "plan.md", "W1", "l"),
            "p:W2": WaveNode("p:W2", "p", "plan.md", "W2", "l", depends_on=["p:W1"]),
        },
        orchestrator=OrchestratorConfig(
            True,
            "p.md",
            serial_waves=["W1", "W2"],
        ),
    )
    ordered = orchestrator_serial_nodes(graph)
    assert [n.wave_id for n in ordered] == ["W1", "W2"]


@pytest.mark.asyncio
async def test_orchestrator_serial_run_status_turns(tmp_path: Path) -> None:
    adapter = SummaryAdapter()
    rr = RunsRoot(tmp_path / "runs")
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )
    src = _seed_orchestrator_input(rr)
    result = await engine.start(src)

    assert result.state == "done"
    assert adapter.dispatched == ["orch-demo:W1", "orch-demo:W2"]

    run_dir = rr.processed_dir / result.run_id
    snap = read_latest(run_dir)
    turn_types = [t.turn_type for t in snap.turns]
    assert "bootstrap" in turn_types
    assert "wave_dispatched" in turn_types
    assert "wave_complete" in turn_types
    assert (run_dir / "orchestrator-status.md").exists()


@pytest.mark.asyncio
async def test_orchestrator_gate_dispatch_auto_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W4.4: gate agent approve continues serial run when env flag set."""
    from tripll.adapters.base import DispatchResult

    class GateApproveAdapter(FakeAdapter):
        async def dispatch(self, brief, **kwargs):  # type: ignore[no-untyped-def]
            node_id = str(brief.get("node_id", ""))
            if node_id == "orchestrator-gate":
                return DispatchResult(outcome="done", result_text="approve", returncode=0)
            return await super().dispatch(brief, **kwargs)

    monkeypatch.setenv("TRIPLL_ORCHESTRATOR_AGENT", "1")
    adapter = GateApproveAdapter()
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    src = rr.input_dir / "orch-demo"
    src.mkdir(parents=True)
    plan = _ORCH_PLAN.replace(
        "| W2 | Second | W1 | | S | make lint |",
        "",
    ).replace("## Wave W2 — second\n\n- [ ] **W2.1** Do second wave.\n", "")
    prompt = (
        _ORCH_PROMPT.replace("W1 → W2", "W1")
        + "\n## Review gates\n\n| Wave | Gate |\n|------|------|\n| W1 | W1.8 REVIEW GATE |\n"
    )
    (src / "orch-demo-wave-plan.md").write_text(plan)
    (src / "orch-demo-orchestrator-prompt.md").write_text(prompt)
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )
    result = await engine.start(src)

    assert result.state == "done"
    run_dir = rr.processed_dir / result.run_id
    assert (run_dir / "review-gate-approved").exists()
    assert not (run_dir / "review-gate-pending.md").exists()
    snap = read_latest(run_dir)
    assert any(t.turn_type == "orchestrator_agent" for t in snap.turns)


@pytest.mark.asyncio
async def test_orchestrator_review_gate_pause(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    rr = RunsRoot(tmp_path / "runs")
    rr.init()
    src = rr.input_dir / "orch-demo"
    src.mkdir(parents=True)
    plan = _ORCH_PLAN.replace(
        "| W2 | Second | W1 | | S | make lint |",
        "",
    ).replace("## Wave W2 — second\n\n- [ ] **W2.1** Do second wave.\n", "")
    prompt = (
        _ORCH_PROMPT.replace("W1 → W2", "W1")
        + "\n## Review gates\n\n| Wave | Gate |\n|------|------|\n| W1 | W1.8 REVIEW GATE |\n"
    )
    (src / "orch-demo-wave-plan.md").write_text(plan)
    (src / "orch-demo-orchestrator-prompt.md").write_text(prompt)
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )
    result = await engine.start(src)

    assert result.state == "paused"
    run_dir = rr.run_dir(result.run_id)
    assert (run_dir / "review-gate-pending.md").exists()
    snap = read_latest(run_dir)
    assert any(t.turn_type == "review_gate" for t in snap.turns)


@pytest.mark.asyncio
async def test_orchestrator_emits_ledger_phase_events(tmp_path: Path) -> None:
    """Orchestrator turns append ``phase=orchestrator`` rows to the ledger (W3.6)."""
    from tripll.ledger import list_events, open_ledger

    adapter = SummaryAdapter()
    rr = RunsRoot(tmp_path / "runs")
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )
    src = _seed_orchestrator_input(rr)
    result = await engine.start(src)

    assert result.state == "done"
    ledger_path = rr.processed_dir / result.run_id / "ledger.db"
    with open_ledger(ledger_path) as lc:
        orch_events = [e for e in list_events(lc, result.run_id) if e.phase == "orchestrator"]
    assert orch_events, "expected orchestrator phase events"
    assert any("bootstrap" in (e.metadata or "") for e in orch_events)
    assert orch_events[0].last_action


@pytest.mark.asyncio
async def test_dev_eval_orchestrator_e2e_pre0_then_processed(tmp_path: Path) -> None:
    """Mode A dev_eval with orchestrator prompt: Pre-0 pause, serial resume, processed."""
    if not (DEV_EVAL / "parallel-wave.md").exists():
        pytest.skip("dev_eval set not present")
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)
    engine.runs_root.init()
    dest = copy_dev_eval_input(engine.runs_root, with_orchestrator=True)

    started = await engine.start(dest)
    assert started.state == "paused"
    assert started.pre0_pending is True

    approve_run_with_hitl(engine, started.run_id)
    result = await engine.resume(started.run_id)
    assert result.state == "done"
    run_dir = engine.runs_root.processed_dir / result.run_id
    assert run_dir.exists()
    assert len(result.nodes) == 16
    assert all(nr.state == "done" for nr in result.nodes.values())
    assert adapter.calls == 16

    snap = read_latest(run_dir)
    turn_types = [t.turn_type for t in snap.turns]
    assert "bootstrap" in turn_types
    assert "wave_complete" in turn_types
    assert (run_dir / "orchestrator-status.md").exists()
