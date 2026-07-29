"""Tests for ``skw.prd_validate`` — about-sevn.bot PRD validator."""

from __future__ import annotations

import json

import pytest

from tests.skw.paths import FIXTURES, KIT_ROOT, REPO_ROOT
from tripll.skw.prd_validate import main as prd_validate_main
from tripll.skw.prd_validate import parse_frontmatter, validate_prd_file

_PRD_FIXTURES = FIXTURES / "prd"


def _validate(path) -> tuple[list[str], list[str]]:
    return validate_prd_file(path, KIT_ROOT)


class TestParseFrontmatter:
    def test_parses_multiline_summary(self) -> None:
        text = (
            "---\nid: prd-01-x\nkind: prd\nsummary: 'line one\n"
            "  line two'\nparent_prd: prd-00-main\n---\n\n## Goals\n"
        )
        meta, _body, err = parse_frontmatter(text)
        assert err is None
        assert "line one" in meta["summary"]
        assert "line two" in meta["summary"]

    def test_parses_list_fields(self) -> None:
        text = "---\nid: prd-01-x\nkind: prd\nspecs:\n- spec-17-gateway\n---\n\n## Goals\n"
        meta, body, err = parse_frontmatter(text)
        assert err is None
        assert meta["specs"] == ["spec-17-gateway"]
        assert body.startswith("## Goals")


class TestValidatePrdFile:
    def test_good_standard_passes(self) -> None:
        errors, _warnings = _validate(_PRD_FIXTURES / "good-standard.md")
        assert errors == []

    def test_good_ai_native_passes(self) -> None:
        errors, _warnings = _validate(_PRD_FIXTURES / "good-ai-native.md")
        assert errors == []

    def test_bad_missing_sections_fails(self) -> None:
        errors, _warnings = _validate(_PRD_FIXTURES / "bad-missing-sections.md")
        assert any("missing required H2 sections" in err for err in errors)

    def test_template_fails_placeholder_id(self) -> None:
        errors, _warnings = _validate(KIT_ROOT / "prd-templates" / "prd-template.md")
        assert any("id" in err for err in errors)

    def test_json_mode_good(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = prd_validate_main(
            [
                str(_PRD_FIXTURES / "good-standard.md"),
                "--kit-root",
                str(KIT_ROOT),
                "--json",
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["reports"][0]["ok"] is True


class TestRenderPrdAuthor:
    def test_render_prd_author_prompt(self) -> None:
        from tripll.skw.render import render_prd_author_prompt

        rendered = render_prd_author_prompt(
            KIT_ROOT,
            prd_path=_PRD_FIXTURES / "good-standard.md",
            repo_root=REPO_ROOT,
        )
        assert "prd-99-fixture-standard" in rendered
        assert "tripll.skw.prd_validate" in rendered
        assert "{{" not in rendered
