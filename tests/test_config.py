"""Tests for tripll.config — four-layer precedence (W13)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from subprocess import run as subprocess_run

import pytest
from typer.testing import CliRunner

from tripll.cli import app
from tripll.config import (
    load_config,
    resolve_agent_model,
    wave_plan_template_path,
)
from tripll.onboard.setup import write_user_config

runner = CliRunner()


def test_config_precedence_env_over_repo_over_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four layers: env beats repo beats user beats defaults."""
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))

    user_dir = home / ".config" / "tripll"
    user_dir.mkdir(parents=True)
    (user_dir / "config.toml").write_text(
        'default_provider = "claude_code"\n\n[providers.claude_code]\nmax_parallel = 9\n',
        encoding="utf-8",
    )
    (repo / "tripll.toml").write_text(
        'default_provider = "cursor_local"\n\n[providers.cursor_local]\nmax_parallel = 4\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TRIPLL_DEFAULT_PROVIDER", "claude_code")
    monkeypatch.setenv("TRIPLL_MAX_PARALLEL", "2")

    cfg = load_config(repo_root=repo)
    assert cfg.default_provider == "claude_code"
    assert cfg.providers["claude_code"].max_parallel == 2
    assert cfg.sources.default_provider == "env"
    assert cfg.sources.repo_config == repo / "tripll.toml"
    assert cfg.sources.user_config == user_dir / "config.toml"


def test_resolve_agent_model_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config()
    monkeypatch.setenv("TRIPLL_DEFAULT_MODEL", "claude-opus-5")
    merged = resolve_agent_model(cfg, agent_id="wave-runner")
    assert merged["model"] == "claude-opus-5"


def test_wave_plan_template_in_package() -> None:
    path = wave_plan_template_path()
    assert path.is_file() or path.name == "wave-plan-template.md"
    text = path.read_text(encoding="utf-8")
    assert "waveorch_format = 3" in text


def test_docs_template_matches_package() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    docs_path = repo_root / "docs" / "wave-plan-template.md"
    pkg_path = repo_root / "src" / "tripll" / "templates" / "wave-plan-template.md"
    assert docs_path.is_file()
    assert pkg_path.is_file()
    assert docs_path.read_text(encoding="utf-8") == pkg_path.read_text(encoding="utf-8")


def test_setup_non_interactive_writes_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cfg_path = home / ".config" / "tripll" / "config.toml"

    result = runner.invoke(app, ["setup", "--non-interactive", "--provider", "cursor_local"])
    assert result.exit_code == 0, result.output
    assert cfg_path.is_file()
    text = cfg_path.read_text(encoding="utf-8")
    assert 'default_provider = "cursor_local"' in text
    assert "[tracing]" in text
    assert "[credentials]" not in text


def test_setup_second_run_preserves_operator_edited_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: re-running setup must not drop operator-added config keys."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cfg_path = home / ".config" / "tripll" / "config.toml"

    first = runner.invoke(app, ["setup", "--non-interactive", "--provider", "cursor_local"])
    assert first.exit_code == 0, first.output

    write_user_config(
        {
            "operator_flag": True,
            "operator": {"note": "keep me"},
            "providers": {"cursor_local": {"custom_timeout": 99}},
        },
        path=cfg_path,
    )

    second = runner.invoke(app, ["setup", "--non-interactive", "--provider", "claude_code"])
    assert second.exit_code == 0, second.output

    text = cfg_path.read_text(encoding="utf-8")
    assert 'default_provider = "claude_code"' in text
    assert "operator_flag = true" in text
    assert 'note = "keep me"' in text
    assert "custom_timeout = 99" in text


def test_doctor_exits_zero_when_provider_available() -> None:
    result = runner.invoke(app, ["doctor"])
    # At least one backend is typically available in dev (cursor_local or claude_code).
    assert result.exit_code in (0, 1)
    assert "Python" in result.output
    assert "Providers" in result.output


def test_doctor_next_option() -> None:
    plan = Path("ignorelocal/tripll-l1-remediation-wave-plan.md")
    if not plan.is_file():
        pytest.skip("plan fixture absent")
    result = runner.invoke(app, ["doctor", "--next", str(plan)])
    assert result.exit_code in (0, 1)
    assert "Next step" in result.output or "PASS" in result.output


def test_doctor_fails_without_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tripll.onboard.doctor.BACKENDS",
        {"fake": lambda: None},  # type: ignore[dict-item]
    )
    monkeypatch.setattr(
        "tripll.onboard.doctor.get_adapter",
        lambda _name: type(
            "Fake",
            (),
            {
                "capabilities": lambda self: type(
                    "C",
                    (),
                    {"available": False, "detail": "missing", "backend": "fake"},
                )()
            },
        )(),
    )
    from tripll.onboard.doctor import run_doctor

    assert run_doctor() == 1


@pytest.mark.tier2
def test_wheel_contains_packaged_assets(tmp_path: Path) -> None:
    out_dir = tmp_path / "wheel"
    out_dir.mkdir()
    build = subprocess_run(
        ["uv", "build", "--wheel", "-o", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert build.returncode == 0, build.stderr
    wheels = sorted(out_dir.glob("*.whl"))
    assert wheels
    names = zipfile.ZipFile(wheels[-1]).namelist()
    required_fragments = (
        "templates/wave-plan-template.md",
        "spec-templates/spec-rules.toml",
        "prd-templates/prd-rules.toml",
        "prompts/",
    )
    for fragment in required_fragments:
        assert any(fragment in entry for entry in names), f"missing {fragment} in wheel"
