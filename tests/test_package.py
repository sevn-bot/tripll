"""Placeholder tests — full suite added in W1+."""

import zipfile
from pathlib import Path
from subprocess import run as subprocess_run

import pytest

import tripll


def test_package_importable() -> None:
    assert tripll.__version__ == "0.0.1"


@pytest.mark.tier2
def test_wheel_ships_data_files(tmp_path: Path) -> None:
    """W13.7a — wheel contains templates, rules, and prompts without force-include."""
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess_run(
        ["uv", "build", "--wheel", "-o", str(out_dir)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    wheel = sorted(out_dir.glob("*.whl"))[-1]
    names = zipfile.ZipFile(wheel).namelist()
    for needle in (
        "tripll/templates/wave-plan-template.md",
        "tripll/skw/spec-templates/spec-rules.toml",
        "tripll/skw/prd-templates/prd-rules.toml",
    ):
        assert any(needle in n for n in names), needle
    assert any("tripll/skw/prompts/" in n for n in names)
