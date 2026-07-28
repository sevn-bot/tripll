"""Tests for ``PipelineBuilder`` JSON compile and round-trip (Wave W1.1)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.pipeline import PipelineBuilder

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"


def test_from_wave_file_topo_order() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    payload = builder.to_json()
    state_ids = [state["id"] for state in payload["states"]]
    assert state_ids.index("W1") < state_ids.index("W2") < state_ids.index("Final")


def test_from_wave_file_roles_and_review_gates() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    payload = builder.to_json()
    by_id = {state["id"]: state for state in payload["states"]}
    assert by_id["W1"]["role"] == "test-author"
    assert by_id["W2"]["role"] == "impl"
    assert by_id["W2"]["review_gate"] is True
    assert by_id["Final"]["review_gate"] is False


def test_from_wave_file_commit_flags() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    payload = builder.to_json()
    for state in payload["states"]:
        assert "commit" in state
        assert isinstance(state["commit"], bool)


def test_to_json_schema_keys() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    payload = builder.to_json()
    assert payload["slug"] == "pipeline-three-wave"
    assert payload["base"] == "origin/main"
    assert payload["branch"] == "feature/pipeline-three-wave"
    assert payload["max_turns"] == 3
    assert isinstance(payload["states"], list)


def test_json_round_trip_stable(tmp_path: Path) -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    first = builder.to_json()
    out_path = tmp_path / "pipeline.json"
    out_path.write_text(json.dumps(first, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    restored = PipelineBuilder.from_json(json.loads(out_path.read_text(encoding="utf-8")))
    second = restored.to_json()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_verify_targets_from_wave_file() -> None:
    builder = PipelineBuilder.from_wave_file(PIPELINE_FIXTURE, kit_root=KIT_ROOT)
    payload = builder.to_json()
    by_id = {state["id"]: state for state in payload["states"]}
    assert by_id["W1"]["verify"] == ["make -C spec-kit-wave test"]
    assert by_id["W2"]["verify"] == ["make validate-selftest"]
