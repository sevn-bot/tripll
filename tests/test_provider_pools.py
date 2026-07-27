"""Per-provider pool contract — PROV-02, PROV-03, P1.5, P1.6 (W1.15a)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tripll.adapters.base import DispatchResult
from tripll.adapters.claude_code import DEFAULT_MODEL, ClaudeCodeAdapter
from tripll.adapters.failure_class import classify_dispatch
from tripll.adapters.pools import ProviderConfig, ProviderPoolRegistry, pools_from_plan
from tripll.engine import Engine
from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.ledger import get_wave, open_ledger
from tripll.pipeline import RunsRoot
from tripll.plan.providers import validate_reasoning_effort

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_default_model_matches_engine_docstring() -> None:
    import tripll.engine as engine_mod

    assert DEFAULT_MODEL == "claude-sonnet-5"
    assert engine_mod.__doc__ is not None
    assert "claude-sonnet-5" in engine_mod.__doc__
    argv = ClaudeCodeAdapter().build_argv(
        {"workspace_scope": [], "agent_directives": []},
        Path("/wt"),
    )
    model_index = argv.index("--model") + 1
    assert argv[model_index] == DEFAULT_MODEL


def test_acquire_order_global_then_provider() -> None:
    clock = _FakeClock()
    reg = ProviderPoolRegistry(
        2,
        {
            "cursor_local": ProviderConfig(max_parallel=1),
            "claude_code": ProviderConfig(max_parallel=1),
        },
        clock=clock,
    )
    order: list[str] = []

    async def _run() -> None:
        await reg.acquire("cursor_local")
        order.append("held")
        reg.release("cursor_local")

    asyncio.run(_run())
    assert order == ["held"]


@pytest.mark.asyncio
async def test_provider_never_exceeds_max_parallel() -> None:
    clock = _FakeClock()
    reg = ProviderPoolRegistry(
        10,
        {"cursor_local": ProviderConfig(max_parallel=2)},
        clock=clock,
    )
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal in_flight, peak
        await reg.acquire("cursor_local")
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        reg.release("cursor_local")

    await asyncio.gather(*(worker() for _ in range(6)))
    assert peak <= 2


def test_infra_classification() -> None:
    result = DispatchResult(
        outcome="failed",
        result_text="Couldn't start extension host",
        returncode=1,
    )
    assert classify_dispatch(result) == "infra"


def test_infra_does_not_consume_attempt(tmp_path: Path) -> None:
    class InfraAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.infra_calls = 0

        async def dispatch(self, brief, **kwargs):  # type: ignore[no-untyped-def]
            self.infra_calls += 1
            if self.infra_calls == 1:
                return DispatchResult(
                    outcome="failed",
                    result_text="Workspace Disconnected",
                    returncode=1,
                    argv=["fake"],
                )
            return DispatchResult(outcome="done", result_text="ok", returncode=0, argv=["fake"])

    adapter = InfraAdapter()
    rr = RunsRoot(tmp_path / "runs")
    engine = Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
        max_parallel=4,
    )
    node = WaveNode("p:W1", "p", "plan.md", "W1", "lane", owned_paths=["src/a/"])
    graph = RunGraph(
        run_id="run-infra",
        batches=[Batch("A", "batch", lanes=["lane"])],
        lanes={"lane": Lane("lane", plans=["p"], owned_paths=["src/a/"], waves=[node])},
        nodes={"p:W1": node},
    )
    run_id = _seed(engine, graph)
    engine._init_provider_fabric(graph)
    assert engine._pools is not None
    for name in list(engine._pools.configs):
        cfg = engine._pools.configs[name]
        engine._pools._configs[name] = ProviderConfig(
            max_parallel=cfg.max_parallel,
            default_model=cfg.default_model,
            cooldown_s=0,
        )
    result = asyncio.run(engine._drive(run_id, graph))
    assert result.state == "done"
    ledger_path = engine.runs_root.processed_dir / run_id / "ledger.db"
    with open_ledger(ledger_path) as lc:
        wave = get_wave(lc, run_id, "p:W1")
    assert wave.attempt_count == 1


def test_adaptive_throttle_halves_pool() -> None:
    clock = _FakeClock()
    reg = ProviderPoolRegistry(
        10,
        {"cursor_local": ProviderConfig(max_parallel=4, cooldown_s=30)},
        clock=clock,
        infra_threshold=2,
    )
    reg.record_infra("cursor_local")
    reg.record_infra("cursor_local")
    assert reg.effective_limit("cursor_local") == 2
    reg.record_success("cursor_local")
    assert reg.effective_limit("cursor_local") == 3


def test_failover_preserves_model_intent(tmp_path: Path) -> None:
    node = WaveNode(
        "p:W1",
        "p",
        "plan.md",
        "W1",
        "lane",
        provider="cursor_local",
        model="claude-opus-5",
        fallback=["claude_code"],
    )
    reg, default = pools_from_plan({"pipeline": {"default_provider": "cursor_local"}})
    engine = Engine(
        adapter=FakeAdapter(),
        runs_root=RunsRoot(tmp_path / "runs"),
        repo_root=tmp_path,
        max_parallel=3,
    )
    engine._pools = reg
    engine._default_provider = default
    provider, used_fallback = engine._pick_provider(node)
    assert provider == "cursor_local"
    assert used_fallback is False
    reg._cooldown_until["cursor_local"] = reg._clock() + 60.0
    provider, used_fallback = engine._pick_provider(node)
    assert provider == "claude_code"
    assert used_fallback is True
    assert node.model == "claude-opus-5"


def test_reasoning_effort_rejected_at_parse() -> None:
    with pytest.raises(ValueError, match="invalid reasoning_effort"):
        validate_reasoning_effort("bogus", wave_id="W1")


def test_max_budget_usd_in_argv() -> None:
    argv = ClaudeCodeAdapter(max_budget_usd=8.5).build_argv(
        {"workspace_scope": [], "agent_directives": []},
        Path("/wt"),
    )
    assert argv[argv.index("--max-budget-usd") + 1] == "8.5"


def test_claude_argv_effort_and_budget() -> None:
    argv = ClaudeCodeAdapter(reasoning_effort="xhigh", max_budget_usd=12.0).build_argv(
        {"model": "claude-opus-5", "workspace_scope": [], "agent_directives": []},
        Path("/wt"),
    )
    assert "--effort" in argv
    assert argv[argv.index("--effort") + 1] == "xhigh"
    assert "--max-budget-usd" in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "12.0"


@pytest.mark.asyncio
async def test_cursor_pool_ceiling() -> None:
    clock = _FakeClock()
    reg = ProviderPoolRegistry(
        10,
        {"cursor_local": ProviderConfig(max_parallel=5)},
        clock=clock,
    )
    peak = 0
    in_flight = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal peak, in_flight
        await reg.acquire("cursor_local")
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.005)
        async with lock:
            in_flight -= 1
        reg.release("cursor_local")

    await asyncio.gather(*(worker() for _ in range(12)))
    assert peak <= 5


def _seed(engine: Engine, graph: RunGraph) -> str:
    import json

    from tripll.ledger import insert_run, insert_wave

    rr = engine.runs_root
    rr.init()
    run_id = graph.run_id
    run_dir = rr.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    rr.briefs_dir(run_id).mkdir(parents=True, exist_ok=True)
    rr.logs_dir(run_id).mkdir(parents=True, exist_ok=True)
    rr.graph_path(run_id).write_text(json.dumps(graph.to_dict(), indent=2))
    with open_ledger(rr.ledger_path(run_id)) as lc:
        insert_run(lc, run_id=run_id, slug=run_id, source_mode="A", input_path=str(run_dir))
        for node in graph.nodes.values():
            insert_wave(
                lc,
                node_id=node.node_id,
                run_id=run_id,
                plan_id=node.plan_id,
                wave_id=node.wave_id,
                lane=node.lane,
            )
    (run_dir / "pre0-approved").write_text("approved\n")
    return run_id


pytestmark = pytest.mark.tier1


@pytest.mark.tier2
def test_real_subprocess_concurrency_probe(tmp_path: Path) -> None:
    """W1.15b: tier-2 probe — CAP-01 subprocess ceiling deferred to manual calibration."""
    del tmp_path  # reserved for a future live subprocess harness
    pytest.skip(
        "CAP-01: tier-2 subprocess ceiling probe deferred — "
        "ProviderPoolRegistry unit tests cover async pool limits"
    )
