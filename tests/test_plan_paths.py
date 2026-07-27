"""Plan path validation — planned-new creates exemption (P0.7)."""

from __future__ import annotations

from pathlib import Path

from tripll.plan_paths import extract_planned_creates, find_unresolved_refs, validate_plan


def test_extract_planned_creates_from_v3_block() -> None:
    body = '```toml\nwaveorch_format = 3\n[pipeline]\ncreates = ["src/new.py"]\n```\n'
    assert extract_planned_creates(body) == frozenset({"src/new.py"})


def test_planned_create_path_is_not_gated() -> None:
    body = '[planned](src/new.py)\n```toml\nwaveorch_format = 3\n[pipeline]\ncreates = ["src/new.py"]\n```\n'
    root = Path("/repo")
    dead = find_unresolved_refs(
        body,
        root,
        planned_creates=frozenset({"src/new.py"}),
    )
    assert dead == []


def test_validate_plan_skips_pipeline_creates(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(
        "[future](src/future.py)\n"
        "```toml\n"
        "waveorch_format = 3\n"
        "[pipeline]\n"
        'creates = ["src/future.py"]\n'
        "```\n",
        encoding="utf-8",
    )
    assert validate_plan(plan, tmp_path) == []
