"""Brownfield and greenfield onboarding tests (W14, W15).

Exports:
    foreign_repo — temp git fixture that is neither tripll nor sevn.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tripll.cli import app
from tripll.onboard import emitters
from tripll.onboard.brownfield import run_brownfield_init
from tripll.onboard.emitters import spec_template_path
from tripll.onboard.greenfield import GreenfieldError, new_project
from tripll.repo_root import resolve_repo_root

runner = CliRunner()


@pytest.fixture
def foreign_repo(tmp_path: Path) -> Path:
    """Minimal foreign git repo with one Python module."""
    root = tmp_path / "demo-app"
    root.mkdir()
    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("def greet() -> str:\n    return 'hi'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root,
        check=True,
    )
    return root


def test_init_foreign_repo_writes_artefacts(
    foreign_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(foreign_repo))
    monkeypatch.setenv("TRIPLL_HUMAN_GATES", "auto_accept")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (foreign_repo / "tripll.toml").is_file()
    assert any((foreign_repo / "docs" / "specs").glob("*.md"))
    assert any((foreign_repo / "docs" / "prds").glob("*.md"))
    assert any((foreign_repo / "docs" / "plans").glob("*-wave-plan.md"))
    evaluations = list((foreign_repo / "docs").glob("evaluation-*.md"))
    assert evaluations
    text = evaluations[0].read_text(encoding="utf-8")
    assert "| EV-" in text
    assert ":184" in text or ":1" in text


def test_init_idempotent_preserves_operator_edits(
    foreign_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIPLL_REPO_ROOT", str(foreign_repo))
    monkeypatch.setenv("TRIPLL_HUMAN_GATES", "auto_accept")
    runner.invoke(app, ["init"])
    toml = foreign_repo / "tripll.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + "operator edit\n", encoding="utf-8")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert toml.read_text(encoding="utf-8").count("operator edit") == 1


def test_brownfield_programmatic(foreign_repo: Path) -> None:
    result = run_brownfield_init(repo_root=foreign_repo)
    assert result.evaluation_path is not None
    assert result.runs_root.is_dir()
    assert (foreign_repo / "runs" / "input").is_dir()


def test_emitters_shared_template_path() -> None:
    path = spec_template_path()
    assert path.name == "spec-template.md"


def test_no_sevn_imports_in_src_tripll() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tripll"
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import sevn" in text or "from sevn" in text:
            hits.append(str(path.relative_to(root)))
    assert hits == []


def test_tripll_checkout_is_not_foreign_fixture() -> None:
    tripll_root = Path(__file__).resolve().parents[1]
    assert (tripll_root / "src" / "tripll").is_dir()
    assert resolve_repo_root(cwd=tripll_root).name != "demo-app"


def test_greenfield_new_writes_artefacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRIPLL_HUMAN_GATES", "auto_accept")
    result = runner.invoke(app, ["new", "demo-project"])
    assert result.exit_code == 0, result.output
    project = tmp_path / "demo-project"
    assert (project / "tripll.toml").is_file()
    assert (project / "pyproject.toml").is_file()
    assert any((project / "docs" / "specs").glob("*.md"))
    assert any((project / "docs" / "plans").glob("*-wave-plan.md"))


def test_greenfield_shares_brownfield_emitters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _track_emit(*args: object, **kwargs: object) -> emitters.EmitResult:
        calls.append("emit_doc_skeletons")
        return emitters.EmitResult()

    monkeypatch.setattr("tripll.onboard.brownfield.emit_doc_skeletons", _track_emit)
    new_project("demo-project", output_dir=tmp_path)
    run_brownfield_init(repo_root=tmp_path / "demo-project")
    assert calls.count("emit_doc_skeletons") >= 2


def test_greenfield_cookiecutter_without_extra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tripll.onboard.greenfield.scaffold_extra_available", lambda: False)
    with pytest.raises(GreenfieldError, match="scaffold extra"):
        new_project("demo", output_dir=tmp_path, cookiecutter=True)


def test_greenfield_idempotent_preserves_operator_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRIPLL_HUMAN_GATES", "auto_accept")
    runner.invoke(app, ["new", "demo-project"])
    project = tmp_path / "demo-project"
    toml = project / "tripll.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + "operator edit\n", encoding="utf-8")
    result = runner.invoke(app, ["init"], env={"TRIPLL_REPO_ROOT": str(project)})
    assert result.exit_code == 0, result.output
    assert toml.read_text(encoding="utf-8").count("operator edit") == 1


def test_greenfield_validate_plan_and_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIPLL_HUMAN_GATES", "auto_accept")
    result = new_project("demo-project", output_dir=tmp_path)
    project = result.project_dir
    plans = list((project / "docs" / "plans").glob("*-wave-plan.md"))
    assert plans
    validate = runner.invoke(
        app, ["validate-plan", str(plans[0])], env={"TRIPLL_REPO_ROOT": str(project)}
    )
    assert validate.exit_code == 0, validate.output
    check = subprocess.run(
        ["make", "check"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
