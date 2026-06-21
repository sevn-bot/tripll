"""Tests for tripll.run_dispatch."""

from __future__ import annotations

from pathlib import Path

from tripll.run_dispatch import (
    DISPATCH_CONFIG_FILENAME,
    read_dispatch_config,
    resolve_dispatch,
    resume_cli_extra_argv,
    write_dispatch_config,
)


def test_write_and_read_dispatch_config(tmp_path: Path) -> None:
    cfg = write_dispatch_config(
        tmp_path,
        backend="cursor_local",
        model="auto",
        agent="wave-runner",
        role_dispatch=True,
    )
    assert cfg.backend == "cursor_local"
    assert (tmp_path / DISPATCH_CONFIG_FILENAME).is_file()
    loaded = read_dispatch_config(tmp_path)
    assert loaded is not None
    assert loaded.model == "auto"
    assert loaded.agent == "wave-runner"


def test_resolve_dispatch_uses_persisted_when_cli_omits_backend(tmp_path: Path) -> None:
    write_dispatch_config(tmp_path, backend="cursor_local", model="auto", agent=None)
    cfg = resolve_dispatch(tmp_path)
    assert cfg.backend == "cursor_local"
    assert cfg.model == "auto"


def test_resolve_dispatch_cli_overrides_persisted(tmp_path: Path) -> None:
    write_dispatch_config(tmp_path, backend="cursor_local", model="auto", agent=None)
    cfg = resolve_dispatch(tmp_path, provider="claude_code", model="claude-opus-4-8")
    assert cfg.backend == "claude_code"
    assert cfg.model == "claude-opus-4-8"


def test_resume_cli_extra_argv_from_persisted(tmp_path: Path) -> None:
    write_dispatch_config(
        tmp_path,
        backend="cursor_local",
        model="auto",
        agent="wave-runner",
    )
    argv = resume_cli_extra_argv(tmp_path)
    assert argv == ["--backend", "cursor_local", "--model", "auto", "--agent", "wave-runner"]
