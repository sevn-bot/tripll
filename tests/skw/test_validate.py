"""Tests for ``skw.validate`` — wave-file v2 validator."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tests.skw.paths import FIXTURES, KIT_ROOT
from tripll.skw.validate import main as validate_main
from tripll.skw.validate import validate_wave_file


def _validate(path: Path) -> tuple[list[str], list[str]]:
    return validate_wave_file(path, KIT_ROOT)


class TestValidateWaveFile:
    """Good and bad fixture coverage for the v2 validator."""

    def test_good_fixture_passes(self) -> None:
        errors, _warnings = _validate(FIXTURES / "good-tier-b.md")
        assert errors == []

    def test_bad_cycle_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-cycle.md")
        assert any("cycle detected" in err for err in errors)

    def test_bad_dangling_dep_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-dangling-dep.md")
        assert any("depends on unknown 'W99'" in err for err in errors)

    def test_bad_orphan_heading_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-orphan-heading.md")
        assert any("orphan heading for wave id 'Orphan'" in err for err in errors)

    def test_bad_verify_nonmake_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-verify-nonmake.md")
        assert any("verify entry must start with 'make '" in err for err in errors)

    def test_bad_parent_ref_fails(self) -> None:
        base = (FIXTURES / "bad-parent-ref.md").read_text(encoding="utf-8")
        bad_target = chr(46) + chr(46) + chr(47) + "README.md"
        content = base.replace("BAD_LINK_TARGET", bad_target)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix="-wave-plan.md",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            errors, _warnings = _validate(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
        assert any("forbidden parent ref" in err for err in errors)

    def test_bad_missing_prompt_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-missing-prompt.md")
        assert any("prompt file not found" in err for err in errors)

    def test_bad_double_test_author_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-double-test-author.md")
        assert any("at most one test-author wave" in err for err in errors)

    def test_bad_impl_missing_test_dep_fails(self) -> None:
        errors, _warnings = _validate(FIXTURES / "bad-impl-missing-test-dep.md")
        assert any("must depend on test-author wave" in err for err in errors)

    def test_json_mode_good(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = validate_main(
            [
                str(FIXTURES / "good-tier-b.md"),
                "--kit-root",
                str(KIT_ROOT),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)
        assert payload["ok"] is True
