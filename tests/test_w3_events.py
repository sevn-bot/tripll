"""Tests for W3 per-agent live event stream.

Covers:
- append_event / list_events round-trip.
- list_events after_event_id paging.
- Engine emits phase events across a node lifecycle.
- on_event streaming callback writes running events with action/usage.
- Throttling: action-changed callback fires; repeated same action does not.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tripll.adapters.base import (
    DispatchResult,
    run_streaming,
)
from tripll.engine import Engine
from tripll.graph import Batch, Lane, RunGraph, WaveNode
from tripll.ledger import (
    append_event,
    insert_run,
    insert_wave,
    list_events,
    open_ledger,
)
from tripll.pipeline import RunsRoot

from ._fakes import AlwaysPassVerifier, FakeAdapter, FakeWorktreeManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def lc():  # type: ignore[no-untyped-def]
    """In-memory ledger for each test."""
    ledger = open_ledger(":memory:")
    yield ledger
    ledger.close()


def _seed(lc, run_id: str = "r1", node_id: str = "p:W1") -> None:  # type: ignore[no-untyped-def]
    insert_run(lc, run_id=run_id, slug="test", source_mode="A", input_path="/tmp/test")
    insert_wave(lc, node_id=node_id, run_id=run_id, plan_id="p", wave_id="W1", lane="core")


# ---------------------------------------------------------------------------
# 1. append_event / list_events round-trip
# ---------------------------------------------------------------------------


def test_append_event_returns_incrementing_ids(lc) -> None:  # type: ignore[no-untyped-def]
    """Each append_event call returns a monotonically increasing event_id."""
    _seed(lc)
    e1 = append_event(lc, run_id="r1", node_id="p:W1", phase="running")
    e2 = append_event(lc, run_id="r1", node_id="p:W1", phase="done")
    assert e1 >= 1
    assert e2 > e1


def test_append_event_stores_all_fields(lc) -> None:  # type: ignore[no-untyped-def]
    """All optional fields are stored and hydrated correctly."""
    _seed(lc)
    append_event(
        lc,
        run_id="r1",
        node_id="p:W1",
        phase="running",
        last_action="editing src/foo.py",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.042,
    )
    evts = list_events(lc, "r1")
    assert len(evts) == 1
    ev = evts[0]
    assert ev.run_id == "r1"
    assert ev.node_id == "p:W1"
    assert ev.phase == "running"
    assert ev.last_action == "editing src/foo.py"
    assert ev.input_tokens == 1000
    assert ev.output_tokens == 500
    assert ev.cost_usd == pytest.approx(0.042)
    assert ev.ts  # non-empty ISO timestamp


def test_append_event_stores_metadata(lc) -> None:  # type: ignore[no-untyped-def]
    """Orchestrator events persist optional JSON metadata (W3)."""
    _seed(lc)
    meta = '{"turn_type":"review_gate","excerpt":"AWAITING REVIEW"}'
    append_event(
        lc,
        run_id="r1",
        node_id="__orchestrator__",
        phase="orchestrator",
        last_action="AWAITING REVIEW (W0.8)",
        metadata=meta,
    )
    evts = list_events(lc, "r1")
    assert evts[0].phase == "orchestrator"
    assert evts[0].metadata == meta


def test_list_events_returns_all_for_run(lc) -> None:  # type: ignore[no-untyped-def]
    """list_events returns all events in event_id order."""
    _seed(lc)
    for phase in ("dispatched", "running", "verifying", "done"):
        append_event(lc, run_id="r1", node_id="p:W1", phase=phase)
    phases = [e.phase for e in list_events(lc, "r1")]
    assert phases == ["dispatched", "running", "verifying", "done"]


def test_list_events_after_event_id_paging(lc) -> None:  # type: ignore[no-untyped-def]
    """after_event_id returns only events with event_id strictly greater than the cursor."""
    _seed(lc)
    e1 = append_event(lc, run_id="r1", node_id="p:W1", phase="dispatched")
    e2 = append_event(lc, run_id="r1", node_id="p:W1", phase="running")
    _e3 = append_event(lc, run_id="r1", node_id="p:W1", phase="done")

    # Page from after first event.
    paged = list_events(lc, "r1", after_event_id=e1)
    assert len(paged) == 2
    assert paged[0].event_id == e2
    assert paged[0].phase == "running"
    assert paged[1].phase == "done"


def test_list_events_after_last_returns_empty(lc) -> None:  # type: ignore[no-untyped-def]
    """Paging past the last event returns an empty list."""
    _seed(lc)
    last = append_event(lc, run_id="r1", node_id="p:W1", phase="done")
    assert list_events(lc, "r1", after_event_id=last) == []


def test_list_events_empty_run(lc) -> None:  # type: ignore[no-untyped-def]
    """list_events returns [] for a run with no events."""
    _seed(lc)
    assert list_events(lc, "r1") == []


def test_list_events_filters_by_run_id(lc) -> None:  # type: ignore[no-untyped-def]
    """Events from a different run are not returned."""
    insert_run(lc, run_id="r1", slug="a", source_mode="A", input_path="/tmp/a")
    insert_run(lc, run_id="r2", slug="b", source_mode="A", input_path="/tmp/b")
    insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
    insert_wave(lc, node_id="q:W1", run_id="r2", plan_id="q", wave_id="W1", lane="l")
    append_event(lc, run_id="r1", node_id="p:W1", phase="running")
    append_event(lc, run_id="r2", node_id="q:W1", phase="done")

    r1_events = list_events(lc, "r1")
    assert len(r1_events) == 1
    assert r1_events[0].node_id == "p:W1"

    r2_events = list_events(lc, "r2")
    assert len(r2_events) == 1
    assert r2_events[0].node_id == "q:W1"


# ---------------------------------------------------------------------------
# 2. Engine emits phase events across a node lifecycle
# ---------------------------------------------------------------------------


def _single_node_graph(run_id: str) -> RunGraph:
    node = WaveNode("p:W1", "p", "plan.md", "W1", "lane", owned_paths=["src/x/"])
    lane = Lane("lane", plans=["p"], owned_paths=["src/x/"], waves=[node])
    batch = Batch("B0", "B0", ["lane"], wave_ids=["W1"])
    return RunGraph(
        run_id=run_id,
        source_mode="A",
        nodes={"p:W1": node},
        lanes={"lane": lane},
        batches=[batch],
        pre0_gates=[],
    )


def _make_engine(tmp_path: Path, adapter: Any) -> Engine:
    rr = RunsRoot(tmp_path / "runs")
    return Engine(
        adapter=adapter,
        runs_root=rr,
        repo_root=tmp_path,
        worktree_manager=FakeWorktreeManager(tmp_path / "wt"),
        verifier=AlwaysPassVerifier(),
    )


def _find_ledger_path(rr: RunsRoot, run_id: str) -> Path:
    """Find the ledger for a completed run (may be in processing/processed/failed)."""
    for folder in (rr.processing_dir, rr.processed_dir, rr.failed_dir):
        p = folder / run_id / "ledger.db"
        if p.exists():
            return p
    raise FileNotFoundError(f"Ledger not found for run {run_id!r}")


def test_engine_emits_dispatched_and_running_events(tmp_path: Path) -> None:
    """Engine emits dispatched and running events when a node starts executing."""
    adapter = FakeAdapter()
    engine = _make_engine(tmp_path, adapter)

    # Patch build_graph_from_dir to return our controlled graph.
    graph = _single_node_graph("r1")
    with (
        patch("tripll.engine.build_graph_from_dir", return_value=graph),
        patch("tripll.engine.write_report"),
        patch("tripll.engine.sync_report"),
    ):
        # Use a fake input directory.
        fake_input = tmp_path / "fake-input"
        fake_input.mkdir()

        result = asyncio.run(engine.start(fake_input))

    assert result.state in ("done", "failed")
    run_id = result.run_id

    ledger_path = _find_ledger_path(engine.runs_root, run_id)
    with open_ledger(ledger_path) as lc:
        events = list_events(lc, run_id)

    phases = [e.phase for e in events]
    # Must contain dispatched and running at minimum.
    assert "dispatched" in phases
    assert "running" in phases


def test_engine_emits_done_event_with_tokens(tmp_path: Path) -> None:
    """Engine emits a done event with cost/tokens from the DispatchResult."""
    adapter = FakeAdapter()
    # Patch dispatch to return a result with usage data.
    result_with_usage = DispatchResult(
        outcome="done",
        result_text="ok",
        returncode=0,
        cost_usd=0.123,
        input_tokens=500,
        output_tokens=250,
    )

    async def _dispatch_with_usage(
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: Any = None,
    ) -> DispatchResult:
        return result_with_usage

    graph = _single_node_graph("r1")
    engine = _make_engine(tmp_path, adapter)
    with (
        patch.object(adapter, "dispatch", side_effect=_dispatch_with_usage),
        patch("tripll.engine.build_graph_from_dir", return_value=graph),
        patch("tripll.engine.write_report"),
        patch("tripll.engine.sync_report"),
    ):
        fake_input = tmp_path / "fake-input"
        fake_input.mkdir()
        run_result = asyncio.run(engine.start(fake_input))

    ledger_path = _find_ledger_path(engine.runs_root, run_result.run_id)
    with open_ledger(ledger_path) as lc:
        events = list_events(lc, run_result.run_id)

    done_events = [e for e in events if e.phase == "done"]
    assert done_events, "Expected at least one 'done' event"
    done = done_events[-1]
    assert done.cost_usd == pytest.approx(0.123)
    assert done.input_tokens == 500
    assert done.output_tokens == 250


def test_engine_emits_failed_event_on_blocked(tmp_path: Path) -> None:
    """Engine emits failed-phase events when a node is blocked after max attempts."""
    adapter = FakeAdapter(fail_times=10, final_outcome="failed")
    engine = _make_engine(tmp_path, adapter)
    engine.max_attempts = 2  # fail faster

    graph = _single_node_graph("r1")
    with (
        patch("tripll.engine.build_graph_from_dir", return_value=graph),
        patch("tripll.engine.write_report"),
        patch("tripll.engine.sync_report"),
    ):
        fake_input = tmp_path / "fake-input"
        fake_input.mkdir()
        run_result = asyncio.run(engine.start(fake_input))

    ledger_path = _find_ledger_path(engine.runs_root, run_result.run_id)
    with open_ledger(ledger_path) as lc:
        events = list_events(lc, run_result.run_id)

    # Should have at least one failed event.
    failed_events = [e for e in events if e.phase == "failed"]
    assert failed_events, f"Expected failed events, got phases: {[e.phase for e in events]}"


# ---------------------------------------------------------------------------
# 3. on_event callback in run_streaming
# ---------------------------------------------------------------------------


def test_run_streaming_on_event_called_on_action_change(tmp_path: Path) -> None:
    """on_event is called when the action summary changes."""
    calls: list[dict[str, Any]] = []

    async def _cb(**kwargs: Any) -> None:
        calls.append(dict(kwargs))

    # Two different action lines.
    line1 = '{"type":"system","subtype":"init","model":"sonnet","cwd":"/wt"}\n'
    line2 = '{"type":"result","is_error":false}\n'

    log_path = tmp_path / "test.log"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.kill = MagicMock()
        # Simulate readline yielding lines then b"".
        side_effects = [line1.encode(), line2.encode(), b""]
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=side_effects)
        mock_exec.return_value = mock_proc

        _rc, _output, _stop = asyncio.run(
            run_streaming(
                ["echo"],
                cwd=tmp_path,
                log_path=log_path,
                timeout_s=10,
                on_event=_cb,
            )
        )

    # The system/init line yields an action summary; the result line also yields one.
    # Both should trigger the callback since actions change.
    assert len(calls) >= 1
    # First call should have a last_action about the session start.
    assert any("last_action" in c for c in calls)


def test_run_streaming_on_event_not_called_on_same_action(tmp_path: Path) -> None:
    """on_event is NOT called when the same action repeats (throttled)."""
    calls: list[dict[str, Any]] = []

    async def _cb(**kwargs: Any) -> None:
        calls.append(dict(kwargs))

    # Two identical lines — same action, no token delta yet.
    line = '{"type":"system","subtype":"init","model":"x","cwd":"/wt"}\n'

    log_path = tmp_path / "test.log"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.kill = MagicMock()
        mock_proc.stdout = MagicMock()
        # Two identical lines then EOF.
        mock_proc.stdout.readline = AsyncMock(side_effect=[line.encode(), line.encode(), b""])
        mock_exec.return_value = mock_proc

        asyncio.run(
            run_streaming(
                ["echo"],
                cwd=tmp_path,
                log_path=log_path,
                timeout_s=10,
                on_event=_cb,
            )
        )

    # Only called once — second line has same action so callback is suppressed.
    assert len(calls) == 1


def test_run_streaming_on_event_none_no_error(tmp_path: Path) -> None:
    """run_streaming works without on_event (backward compat)."""
    log_path = tmp_path / "test.log"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.kill = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=[b"hello\n", b""])
        mock_exec.return_value = mock_proc

        rc, output, _stop = asyncio.run(
            run_streaming(
                ["echo"],
                cwd=tmp_path,
                log_path=log_path,
                timeout_s=10,
                on_event=None,
            )
        )
    assert rc == 0
    assert "hello" in output


# ---------------------------------------------------------------------------
# 4. Throttling: row count stays sane
# ---------------------------------------------------------------------------


def test_on_event_throttle_many_same_action_lines(tmp_path: Path) -> None:
    """Throttling: sending 20 identical action lines triggers on_event only once."""
    calls: list[dict[str, Any]] = []

    async def _cb(**kwargs: Any) -> None:
        calls.append(dict(kwargs))

    line = '{"type":"system","subtype":"init","model":"x","cwd":"/wt"}\n'
    lines = [line.encode()] * 20 + [b""]

    log_path = tmp_path / "test.log"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.kill = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=lines)
        mock_exec.return_value = mock_proc

        asyncio.run(
            run_streaming(
                ["echo"],
                cwd=tmp_path,
                log_path=log_path,
                timeout_s=10,
                on_event=_cb,
            )
        )

    # Only one call even though 20 identical lines were emitted.
    assert len(calls) == 1


def test_on_event_two_different_actions_two_calls(tmp_path: Path) -> None:
    """Two different action lines each trigger on_event once."""
    calls: list[dict[str, Any]] = []

    async def _cb(**kwargs: Any) -> None:
        calls.append(dict(kwargs))

    line1 = '{"type":"system","subtype":"init","model":"sonnet","cwd":"/a"}\n'
    line2 = '{"type":"result","is_error":false}\n'
    lines = [line1.encode(), line2.encode(), b""]

    log_path = tmp_path / "test.log"
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.kill = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=lines)
        mock_exec.return_value = mock_proc

        asyncio.run(
            run_streaming(
                ["echo"],
                cwd=tmp_path,
                log_path=log_path,
                timeout_s=10,
                on_event=_cb,
            )
        )

    # Two different actions → two calls.
    assert len(calls) == 2
