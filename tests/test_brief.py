"""Tests for tripll.brief — JSON + human dispatch-brief rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.brief import (
    render_dispatch_prompt,
    render_human_brief,
    render_json_brief,
    write_brief,
)
from tripll.parse.parallel_wave import build_run_graph_from_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_EVAL = _REPO_ROOT / "plan" / "dev_eval_14062026"

_REQUIRED_KEYS = {
    "$schema",
    "brief_version",
    "run_id",
    "node_id",
    "plan_file",
    "wave_id",
    "branch",
    "worktree_path",
    "plan_worktree_path",
    "prerequisite_waves",
    "bullets_in_scope",
    "specs_with_10x_row",
    "locked_decisions",
    "owned_paths",
    "forbidden_paths",
    "verify_targets",
    "docs_menu_sync_targets",
    "manual_smoke_deferred",
    "wall_clock_limit_s",
    "retry_policy",
    "agent_directives",
    "workspace_scope",
    "model",
}


@pytest.fixture
def telemetry_node():  # type: ignore[no-untyped-def]
    if not (_DEV_EVAL / "parallel-wave.md").exists():
        pytest.skip("dev_eval set not present")
    graph = build_run_graph_from_dir(_DEV_EVAL, run_id="dev-eval-test")
    return graph.nodes["telemetry:all-waves"]


def test_json_brief_has_all_schema_keys(telemetry_node) -> None:  # type: ignore[no-untyped-def]
    brief = render_json_brief(
        telemetry_node,
        run_id="r",
        branch="wave/r/telemetry-w1",
        worktree_path="runs/r/worktrees/telemetry-w1",
    )
    assert set(brief) == _REQUIRED_KEYS


def test_json_brief_lists_telemetry_owned(telemetry_node) -> None:  # type: ignore[no-untyped-def]
    brief = render_json_brief(telemetry_node, run_id="r", branch="b", worktree_path="w")
    assert "src/sevn/agent/adapters/" in brief["owned_paths"]


def test_json_brief_forbids_cw_hotspots(telemetry_node) -> None:  # type: ignore[no-untyped-def]
    brief = render_json_brief(telemetry_node, run_id="r", branch="b", worktree_path="w")
    forbidden = brief["forbidden_paths"]
    assert "src/sevn/gateway/agent_turn.py" in forbidden
    assert "infra/sevn.schema.json" in forbidden
    assert "Makefile (ci: line)" in forbidden


def test_retry_policy_escalates(telemetry_node) -> None:  # type: ignore[no-untyped-def]
    brief = render_json_brief(telemetry_node, run_id="r", branch="b", worktree_path="w")
    assert brief["retry_policy"] == {"max_attempts": 5, "on_5th_failure": "escalate"}


def test_human_brief_mentions_owned_and_forbidden(telemetry_node) -> None:  # type: ignore[no-untyped-def]
    text = render_human_brief(
        telemetry_node, branch="wave/r/telemetry-w1", worktree_path="runs/r/wt"
    )
    assert "src/sevn/agent/adapters/" in text
    assert "src/sevn/gateway/agent_turn.py" in text
    assert "infra/sevn.schema.json" in text
    assert "do not commit" in text


def test_write_brief_creates_file(telemetry_node, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    brief = render_json_brief(telemetry_node, run_id="r", branch="b", worktree_path="w")
    path = write_brief(brief, tmp_path / "briefs")
    assert path.exists()
    assert path.name == "telemetry_all-waves.json"


def test_dispatch_prompt_uses_plan_worktree_path(telemetry_node) -> None:  # type: ignore[no-untyped-def]
    brief = render_json_brief(
        telemetry_node,
        run_id="r",
        branch="b",
        worktree_path="/wt",
        plan_worktree_path="/wt/plan/tripll/x-wave-plan.md",
    )
    prompt = render_dispatch_prompt(brief)
    assert "Execute wave" in prompt
    assert "/wt/plan/tripll/x-wave-plan.md" in prompt
    assert "plan/tripll/" in prompt
    assert "Agent directives:" in prompt
    assert "do not commit" in prompt.lower()
