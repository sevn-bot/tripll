"""Tests for ``skw.changelog_validate`` — Keep a Changelog gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tripll.skw.changelog_validate import (
    check_diff_gate,
    check_staged_gate,
    load_changelog_rules,
    parse_changelog,
    unreleased_entries,
    validate_changelog,
)
from tripll.skw.changelog_validate import (
    main as changelog_main,
)

GOOD_CHANGELOG = """# Changelog

All notable changes follow Keep a Changelog and SemVer.

## [Unreleased]

### Added
- [2026-07-08] Proxy egress allowlist for outbound web fetches (#123)
### Changed
- [2026-07-08] `sevn doctor` now checks the changelog gate
### Deprecated
### Removed
### Fixed
### Security

## [0.0.1] - 2026-07-08
### Added
- Initial gateway skeleton
"""

BAD_CATEGORY_CHANGELOG = """# Changelog

## [Unreleased]

### Enhancements
- [2026-07-08] Added a shiny new thing here
"""

TRAILING_PERIOD_CHANGELOG = """# Changelog

## [Unreleased]

### Added
- [2026-07-08] Added a proper new capability.
"""

SHORT_ENTRY_CHANGELOG = """# Changelog

## [Unreleased]

### Added
- [2026-07-08] Too short
"""

RULES = load_changelog_rules()


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text, encoding="utf-8")
    return path


class TestParseChangelog:
    def test_parses_versions_and_categories(self) -> None:
        parsed = parse_changelog(GOOD_CHANGELOG)
        names = [v["name"] for v in parsed["versions"]]
        assert names == ["Unreleased", "0.0.1"]
        released = parsed["versions"][1]
        assert released["date"] == "2026-07-08"

    def test_unreleased_entries_extracts_bodies(self) -> None:
        entries = unreleased_entries(GOOD_CHANGELOG)
        assert "`sevn doctor` now checks the changelog gate" in entries
        assert any("Proxy egress allowlist" in e for e in entries)


class TestValidateChangelog:
    def test_good_changelog_passes(self, tmp_path: Path) -> None:
        path = _write(tmp_path, GOOD_CHANGELOG)
        errors, _warnings = validate_changelog(tmp_path, None, RULES, path)
        assert errors == []

    def test_bad_category_fails(self, tmp_path: Path) -> None:
        path = _write(tmp_path, BAD_CATEGORY_CHANGELOG)
        errors, _warnings = validate_changelog(tmp_path, None, RULES, path)
        assert any("unknown category" in err for err in errors)

    def test_trailing_period_fails(self, tmp_path: Path) -> None:
        path = _write(tmp_path, TRAILING_PERIOD_CHANGELOG)
        errors, _warnings = validate_changelog(tmp_path, None, RULES, path)
        assert any("must not end with a period" in err for err in errors)

    def test_short_entry_fails(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SHORT_ENTRY_CHANGELOG)
        errors, _warnings = validate_changelog(tmp_path, None, RULES, path)
        assert any("too short" in err for err in errors)

    def test_missing_unreleased_fails(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "# Changelog\n\n## [0.0.1] - 2026-07-08\n### Added\n- Thing\n")
        errors, _warnings = validate_changelog(tmp_path, None, RULES, path)
        assert any("missing '## [Unreleased]'" in err for err in errors)

    def test_json_mode_ok(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write(tmp_path, GOOD_CHANGELOG)
        rc = changelog_main(["--repo", str(tmp_path), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True


# ---------------------------------------------------------------------------
# Diff gate (hermetic git sandbox — no network, no origin)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", message)


def _head_sha(repo: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


class TestDiffGate:
    def test_fires_when_code_changed_without_entry(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        src = repo / "src" / "sevn"
        src.mkdir(parents=True)
        (src / "mod.py").write_text("x = 1\n", encoding="utf-8")
        _commit(repo, "chore: baseline")
        base = _head_sha(repo)
        # Change code without touching the Unreleased section.
        (src / "mod.py").write_text("x = 2\n", encoding="utf-8")
        _commit(repo, "feat: change code")

        errors, notes = check_diff_gate(repo, base, RULES)
        assert any("no new '## [Unreleased]'" in err for err in errors), (errors, notes)

    def test_passes_when_entry_added(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        src = repo / "src" / "sevn"
        src.mkdir(parents=True)
        (src / "mod.py").write_text("x = 1\n", encoding="utf-8")
        _commit(repo, "chore: baseline")
        base = _head_sha(repo)
        (src / "mod.py").write_text("x = 2\n", encoding="utf-8")
        new_text = GOOD_CHANGELOG.replace(
            "### Added\n- [2026-07-08] Proxy egress allowlist",
            "### Added\n- [2026-07-08] Fresh Unreleased entry describing the change\n- [2026-07-08] Proxy egress allowlist",
        )
        (repo / "CHANGELOG.md").write_text(new_text, encoding="utf-8")
        _commit(repo, "feat: change code with entry")

        errors, _notes = check_diff_gate(repo, base, RULES)
        assert errors == []

    def test_exempt_paths_do_not_fire(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        _commit(repo, "chore: baseline")
        base = _head_sha(repo)
        (repo / "README.md").write_text("hi there\n", encoding="utf-8")
        _commit(repo, "docs: tweak readme")

        errors, notes = check_diff_gate(repo, base, RULES)
        assert errors == []
        assert any("no code changes require" in note for note in notes)

    def test_escape_hatch_skips_gate(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        src = repo / "src" / "sevn"
        src.mkdir(parents=True)
        (src / "mod.py").write_text("x = 1\n", encoding="utf-8")
        _commit(repo, "chore: baseline")
        base = _head_sha(repo)
        (src / "mod.py").write_text("x = 2\n", encoding="utf-8")
        _commit(repo, "feat: change code\n\nchangelog: skip")

        errors, notes = check_diff_gate(repo, base, RULES)
        assert errors == []
        assert any("changelog: skip" in note for note in notes)

    def test_graceful_skip_when_no_git(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        errors, notes = check_diff_gate(tmp_path, "origin/main", RULES)
        assert errors == []
        assert any("not a git work tree" in note for note in notes)

    def test_graceful_skip_when_base_missing(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        _commit(repo, "chore: baseline")
        errors, notes = check_diff_gate(repo, "origin/nonexistent-ref", RULES)
        assert errors == []
        assert any("not found" in note for note in notes)


# ---------------------------------------------------------------------------
# Staged gate (local commit-msg hook — index vs HEAD, no remote base)
# ---------------------------------------------------------------------------


def _baseline_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Init a repo with a committed changelog + one src file. Returns (repo, src_file)."""
    repo = _init_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
    src = repo / "src" / "sevn"
    src.mkdir(parents=True)
    mod = src / "mod.py"
    mod.write_text("x = 1\n", encoding="utf-8")
    _commit(repo, "chore: baseline")
    return repo, mod


def _add_entry(repo: Path) -> None:
    new_text = GOOD_CHANGELOG.replace(
        "### Added\n- [2026-07-08] Proxy egress allowlist",
        "### Added\n- [2026-07-08] Fresh Unreleased entry describing the staged change\n- [2026-07-08] Proxy egress allowlist",
    )
    (repo / "CHANGELOG.md").write_text(new_text, encoding="utf-8")


class TestStagedGate:
    def test_fires_when_code_staged_without_entry(self, tmp_path: Path) -> None:
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "src/sevn/mod.py")
        errors, notes = check_staged_gate(repo, RULES)
        assert any("no new '## [Unreleased]'" in err for err in errors), (errors, notes)

    def test_passes_when_entry_staged(self, tmp_path: Path) -> None:
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _add_entry(repo)
        _git(repo, "add", "src/sevn/mod.py", "CHANGELOG.md")
        errors, _notes = check_staged_gate(repo, RULES)
        assert errors == []

    def test_ignores_unstaged_changelog_edit(self, tmp_path: Path) -> None:
        # The entry is written to the working tree but NOT staged: index == HEAD,
        # so the staged gate must still fire (proves index-not-working-tree semantics).
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "src/sevn/mod.py")
        _add_entry(repo)  # working tree only, unstaged
        errors, _notes = check_staged_gate(repo, RULES)
        assert any("no new '## [Unreleased]'" in err for err in errors)

    def test_no_staged_code_noops(self, tmp_path: Path) -> None:
        repo, _mod = _baseline_repo(tmp_path)
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        errors, notes = check_staged_gate(repo, RULES)
        assert errors == []
        assert any("no staged code changes require" in note for note in notes)

    def test_skip_trailer_in_commit_msg_file(self, tmp_path: Path) -> None:
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "src/sevn/mod.py")
        msg = tmp_path / "COMMIT_EDITMSG"
        msg.write_text("feat: change code\n\nchangelog: skip\n", encoding="utf-8")
        errors, notes = check_staged_gate(repo, RULES, commit_msg_file=msg)
        assert errors == []
        assert any("skipped" in note for note in notes)

    def test_skip_via_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "src/sevn/mod.py")
        monkeypatch.setenv("SEVN_CHANGELOG_SKIP", "1")
        errors, notes = check_staged_gate(repo, RULES)
        assert errors == []
        assert any("skipped" in note for note in notes)

    def test_graceful_skip_when_no_git(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text(GOOD_CHANGELOG, encoding="utf-8")
        errors, notes = check_staged_gate(tmp_path, RULES)
        assert errors == []
        assert any("not a git work tree" in note for note in notes)

    def test_validate_changelog_staged_mode(self, tmp_path: Path) -> None:
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "src/sevn/mod.py")
        errors, _warnings = validate_changelog(
            repo, None, RULES, repo / "CHANGELOG.md", staged=True
        )
        assert any("no new '## [Unreleased]'" in err for err in errors)

    def test_cli_staged_flag_via_positional_msg_file(self, tmp_path: Path) -> None:
        repo, mod = _baseline_repo(tmp_path)
        mod.write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "src/sevn/mod.py")
        msg = tmp_path / "COMMIT_EDITMSG"
        msg.write_text("feat: x\n\nchangelog: skip\n", encoding="utf-8")
        # Mirrors pre-commit's commit-msg stage appending the message path.
        rc = changelog_main(["--repo", str(repo), "--staged", str(msg)])
        assert rc == 0
