"""Tests for agent driver dry-run and role mapping (Wave W1.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.driver import run_agent

PIPELINE_FIXTURE = FIXTURES / "pipeline-three-wave.md"


@pytest.mark.parametrize(
    ("role", "expected_agent"),
    [
        ("test-author", "test-creator"),
        ("impl", "wave-runner"),
    ],
)
def test_role_to_agent_mapping(role: str, expected_agent: str) -> None:
    from tripll.skw.driver import agent_for_role

    assert agent_for_role(role) == expected_agent


def test_dryrun_prints_cursor_agent_argv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKW_DRYRUN", "1")
    monkeypatch.setenv("SKW_AGENT_BIN", "cursor-agent")
    rc = run_agent(
        wave_file=PIPELINE_FIXTURE,
        wave_id="W2",
        kit_root=KIT_ROOT,
        stage="run",
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "cursor-agent" in captured.out
    assert "[dry-run]" in captured.out


def test_dryrun_test_author_wave_uses_test_creator(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKW_DRYRUN", "1")
    rc = run_agent(
        wave_file=PIPELINE_FIXTURE,
        wave_id="W1",
        kit_root=KIT_ROOT,
        stage="run",
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "test-creator" in captured.out.lower() or "test-author" in captured.out


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"type": "system", "subtype": "init"}', None),
        ('{"type": "user"}', None),
        ("plain text line", "plain text line"),
        ("not json {oops", "not json {oops"),
        ('{"type": "result", "subtype": "success"}', "[result] success"),
        ('{"type": "tool_use", "name": "Edit"}', "[tool] Edit"),
        (
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}',
            "hi",
        ),
    ],
)
def test_format_stream_line(raw: str, expected: str | None) -> None:
    from tripll.skw.driver import _format_stream_line

    assert _format_stream_line(raw) == expected


def test_dryrun_does_not_spawn_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SKW_DRYRUN", "1")
    called: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: object) -> object:
        called.append(cmd)
        raise AssertionError("subprocess should not run in dry-run mode")

    monkeypatch.setattr("subprocess.run", _fake_run)
    run_agent(
        wave_file=PIPELINE_FIXTURE,
        wave_id="W2",
        kit_root=KIT_ROOT,
        stage="run",
    )
    assert called == []


def test_orchestrator_stage_applies_wave_model_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wave = tmp_path / "orch-model.md"
    wave.write_text(
        """# Orchestrator model fixture

```toml
waveorch_format = 2
title = "Orch"
slug = "orch"
base = "main"
branch = "feature/orch"

[pipeline]
max_turns = 1

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[pipeline.models.orchestrator]
model = "orchestrator-only-model"

[[waves]]
id = "W0"
title = "Only"
depends_on = []
role = "impl"
verify = ["make lint"]
```

## Wave W0

- [ ] **W0.1** task
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SKW_DRYRUN", "1")
    rc = run_agent(
        wave_file=wave,
        kit_root=KIT_ROOT,
        stage="orchestrator",
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "orchestrator-only-model" in captured.out
