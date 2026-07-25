"""Helpers for invoking LangGraph pipeline nodes in unit tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.pipeline import PipelineBuilder
from tripll.skw.states import PipelineState


def invoke_pipeline_node(
    builder: PipelineBuilder,
    node_name: str,
    state: PipelineState,
) -> PipelineState:
    """Run one compiled graph node and return the updated state."""
    graph = builder.build_graph()
    spec = graph.nodes[node_name]
    result = spec.runnable.invoke(state)
    if not isinstance(result, dict):
        msg = f"node {node_name!r} returned non-dict: {type(result)!r}"
        raise TypeError(msg)
    return result


def copy_minimal_kit(tmp_path: Path) -> tuple[Path, Path]:
    """Copy prompts, config, and fixtures into an isolated kit root."""
    kit_root = tmp_path / "kit"
    kit_root.mkdir()
    shutil.copytree(KIT_ROOT / "prompts", kit_root / "prompts")
    shutil.copy(KIT_ROOT / "skw.toml", kit_root / "skw.toml")
    fixture_dir = kit_root / "tests" / "fixtures"
    shutil.copytree(FIXTURES, fixture_dir)
    (kit_root / "waves").mkdir()
    wave_file = fixture_dir / "pipeline-three-wave.md"
    return kit_root, wave_file


def write_verdict(kit_root: Path, slug: str, verdict: str) -> Path:
    """Write a review-result JSON file under ``waves/``."""
    path = kit_root / "waves" / f"{slug}.review-result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"verdict": "{verdict}", "findings": []}}\n',
        encoding="utf-8",
    )
    return path
