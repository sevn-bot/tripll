"""Tests for ``skw.resolve_wave`` — wave id and role resolution."""

from __future__ import annotations

import pytest

from tests.skw.paths import FIXTURES
from tripll.skw.resolve_wave import (
    load_wave_data,
    resolve_test_author_id,
    wave_role,
)


class TestResolveWave:
    """Wave id / role resolution helpers."""

    def test_impl_wave_role(self) -> None:
        data = load_wave_data(FIXTURES / "good-tier-b.md")
        assert wave_role(data, "W0") == "impl"

    def test_no_test_author_errors(self) -> None:
        data = load_wave_data(FIXTURES / "good-tier-b.md")
        with pytest.raises(ValueError, match="no test-author wave"):
            resolve_test_author_id(data)

    def test_double_test_author_errors(self) -> None:
        data = load_wave_data(FIXTURES / "bad-double-test-author.md")
        with pytest.raises(ValueError, match="multiple test-author"):
            resolve_test_author_id(data)

    def test_pipeline_fixture_test_author_id(self) -> None:
        data = load_wave_data(FIXTURES / "pipeline-three-wave.md")
        assert resolve_test_author_id(data) == "W1"

    def test_validate_impl_rejects_test_author_via_cli(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from tripll.skw.resolve_wave import main as resolve_main

        rc = resolve_main([str(FIXTURES / "bad-double-test-author.md"), "--validate-impl", "W0"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "test-creator" in captured.err
