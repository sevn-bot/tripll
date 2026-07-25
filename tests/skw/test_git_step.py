"""Tests for deterministic ``commit_wave`` git step (Wave W1.6, D9)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.skw.paths import KIT_ROOT, REPO_ROOT
from tripll.skw.git import commit_wave
from tripll.skw.validate import load_skw_config

PIPELINE_FIXTURE_SLUG = "pipeline-three-wave"


def _git_config(**overrides: Any) -> dict[str, Any]:
    cfg = load_skw_config(KIT_ROOT)
    cfg["git"].update(overrides)
    return cfg


def test_commit_wave_stages_tracked_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W2",
        title="Impl with review gate",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(),
    )
    flat = " ".join(" ".join(c) for c in calls)
    assert "git add" in flat
    assert "git commit" in flat


def test_commit_wave_impl_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W2",
        title="Impl with review gate",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(),
    )
    commit_line = next(" ".join(c) for c in calls if c and c[0] == "git" and "commit" in c)
    assert "feat(pipeline-three-wave): W2 — Impl with review gate" in commit_line


def test_commit_wave_test_author_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W1",
        title="Test author wave",
        slug=PIPELINE_FIXTURE_SLUG,
        role="test-author",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(),
    )
    commit_line = next(" ".join(c) for c in calls if c and c[0] == "git" and "commit" in c)
    assert "test(pipeline-three-wave): W1 — Test author wave" in commit_line


def test_commit_wave_pushes_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W2",
        title="Impl",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(push_per_wave=True, remote="origin"),
    )
    flat = " ".join(" ".join(c) for c in calls)
    assert "git push origin feature/pipeline-three-wave" in flat


def test_commit_wave_noop_when_commit_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W2",
        title="Impl",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(commit_per_wave=False),
    )
    assert calls == []


def test_commit_wave_no_push_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W2",
        title="Impl",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(push_per_wave=False),
    )
    flat = " ".join(" ".join(c) for c in calls)
    assert "git commit" in flat
    assert "git push" not in flat


def test_commit_wave_dryrun_prints_argv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKW_DRYRUN", "1")

    def _fail(cmd: list[str], **_kwargs: object) -> object:
        raise AssertionError(f"subprocess must not run in dry-run: {cmd}")

    monkeypatch.setattr("subprocess.run", _fail)
    commit_wave(
        wave_id="W2",
        title="Impl",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(),
    )
    captured = capsys.readouterr()
    assert "git add" in captured.out
    assert "git commit" in captured.out
    assert "git push" in captured.out


def test_commit_wave_resolves_worktree_never_switches_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout_calls: list[list[str]] = []

    def _record(cmd: list[str], **_kwargs: object) -> object:
        if len(cmd) >= 3 and cmd[0] == "git" and cmd[1] == "checkout":
            checkout_calls.append(cmd)

        class _Result:
            returncode = 0
            stdout = str(REPO_ROOT)
            stderr = ""

        return _Result()

    monkeypatch.setattr("subprocess.run", _record)
    commit_wave(
        wave_id="W2",
        title="Impl",
        slug=PIPELINE_FIXTURE_SLUG,
        role="impl",
        branch="feature/pipeline-three-wave",
        worktree=REPO_ROOT,
        git_config=_git_config(),
    )
    assert checkout_calls == []
