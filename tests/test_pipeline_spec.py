"""Tests for tripll.pipeline_spec — parsing and validating pipeline files."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.pipeline_spec import PipelineSpecError, load_pipeline_spec

SAMPLE = Path(__file__).resolve().parents[1] / "docs/examples/pipelines/tripll-l1-pipeline.toml"

MINIMAL = """
pipeline_format = 1
title = "Tiny"

[[steps]]
id = "a"
produces = "s1"
wave = "W0"
[[steps.next]]
to = "b"
label = "go"

[[steps]]
id = "b"
produces = "s2"
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "p.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def test_loads_minimal_pipeline(tmp_path: Path) -> None:
    spec = load_pipeline_spec(_write(tmp_path, MINIMAL))
    assert spec.title == "Tiny"
    assert [step.step_id for step in spec.steps] == ["a", "b"]
    assert spec.steps[0].transitions[0].to == "b"
    assert spec.steps[0].transitions[0].style == "primary"


def test_defaults_label_kind_and_work(tmp_path: Path) -> None:
    step = load_pipeline_spec(_write(tmp_path, MINIMAL)).steps[0]
    assert step.label == "a"
    assert step.kind == "agent"
    assert step.work_label == "a"
    assert step.layer is None
    assert step.column is None


def test_state_map_falls_back_to_undeclared_states(tmp_path: Path) -> None:
    states = load_pipeline_spec(_write(tmp_path, MINIMAL)).state_map()
    assert states["s1"].label == "s1"
    assert states["s1"].kind == "artifact"


def test_incoming_reverses_transitions(tmp_path: Path) -> None:
    incoming = load_pipeline_spec(_write(tmp_path, MINIMAL)).incoming()
    assert incoming["b"] == [
        ("a", load_pipeline_spec(_write(tmp_path, MINIMAL)).steps[0].transitions[0])
    ]
    assert incoming["a"] == []


def test_loads_committed_sample_pipeline() -> None:
    spec = load_pipeline_spec(SAMPLE)
    assert spec.title == "tripll L1 pipeline"
    assert len(spec.steps) == 28
    assert {cluster.cluster_id for cluster in spec.clusters} == {
        "preflight",
        "wave-exec",
        "pr-loop",
    }
    assert all(step.layer is not None and step.column is not None for step in spec.steps)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_rejects_unsupported_format(tmp_path: Path) -> None:
    with pytest.raises(PipelineSpecError, match="pipeline_format must be 1"):
        load_pipeline_spec(_write(tmp_path, MINIMAL.replace("= 1", "= 7", 1)))


def test_rejects_pipeline_without_steps(tmp_path: Path) -> None:
    with pytest.raises(PipelineSpecError, match="at least one"):
        load_pipeline_spec(_write(tmp_path, "pipeline_format = 1\ntitle = 'x'\n"))


def test_rejects_transition_to_unknown_step(tmp_path: Path) -> None:
    body = MINIMAL.replace('to = "b"', 'to = "nope"')
    with pytest.raises(PipelineSpecError, match="transition to unknown step 'nope'"):
        load_pipeline_spec(_write(tmp_path, body))


def test_rejects_duplicate_step_ids(tmp_path: Path) -> None:
    with pytest.raises(PipelineSpecError, match="duplicate step id"):
        load_pipeline_spec(_write(tmp_path, MINIMAL + '\n[[steps]]\nid = "a"\n'))


def test_rejects_unknown_step_key(tmp_path: Path) -> None:
    with pytest.raises(PipelineSpecError, match="unknown key"):
        load_pipeline_spec(_write(tmp_path, MINIMAL + '\n[[steps]]\nid = "c"\nagent = "x"\n'))


def test_rejects_unknown_kind(tmp_path: Path) -> None:
    body = MINIMAL.replace('id = "a"', 'id = "a"\nkind = "robot"')
    with pytest.raises(PipelineSpecError, match="unknown kind 'robot'"):
        load_pipeline_spec(_write(tmp_path, body))


def test_rejects_unknown_cluster_reference(tmp_path: Path) -> None:
    body = MINIMAL.replace('id = "a"', 'id = "a"\ncluster = "ghost"')
    with pytest.raises(PipelineSpecError, match="unknown cluster 'ghost'"):
        load_pipeline_spec(_write(tmp_path, body))


def test_rejects_produces_of_undeclared_state_when_states_declared(tmp_path: Path) -> None:
    body = MINIMAL + '\n[[states]]\nid = "s1"\n'
    with pytest.raises(PipelineSpecError, match="produces undeclared state 's2'"):
        load_pipeline_spec(_write(tmp_path, body))


def test_rejects_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(PipelineSpecError, match="invalid TOML"):
        load_pipeline_spec(_write(tmp_path, "pipeline_format = "))


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PipelineSpecError, match="cannot read pipeline file"):
        load_pipeline_spec(tmp_path / "absent.toml")
