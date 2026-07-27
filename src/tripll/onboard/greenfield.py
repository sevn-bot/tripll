"""Greenfield onboarding — ``tripll new`` for new projects (W15).

Exports:
    GreenfieldError — scaffold or onboarding failure.
    GreenfieldResult — new-project run summary.
    new_project — scaffold skeleton, then reuse brownfield emitters.
    render_project_skeleton — write packaged offline templates.
    scaffold_extra_available — whether cookiecutter scaffold extra is installed.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from importlib.resources import files as pkg_files
from importlib.util import find_spec
from pathlib import Path

from tripll.onboard.brownfield import BrownfieldResult, run_brownfield_init

__all__ = [
    "GreenfieldError",
    "GreenfieldResult",
    "new_project",
    "render_project_skeleton",
    "scaffold_extra_available",
]

_SKELETON_ROOT = "project-skeleton"
_TEMPLATE_MAP: tuple[tuple[str, str], ...] = (
    ("pyproject.toml.tmpl", "pyproject.toml"),
    ("Makefile.tmpl", "Makefile"),
    (".gitignore.tmpl", ".gitignore"),
    ("README.md.tmpl", "README.md"),
    ("package__init__.py.tmpl", "src/{package_module}/__init__.py"),
    ("main.py.tmpl", "src/{package_module}/main.py"),
    ("tests/test_smoke.py.tmpl", "tests/test_smoke.py"),
)


class GreenfieldError(RuntimeError):
    """Raised when greenfield scaffolding or onboarding fails.

    Examples:
        >>> issubclass(GreenfieldError, RuntimeError)
        True
    """


@dataclass
class GreenfieldResult:
    """Outcome of ``tripll new``.

    Args:
        project_dir (Path): Created or reconciled project root.
        brownfield (BrownfieldResult): Shared emitter / evaluation summary.
        skeleton_created (bool): Whether the offline skeleton was written this run.
        messages (list[str]): Operator-facing status lines.
    """

    project_dir: Path
    brownfield: BrownfieldResult
    skeleton_created: bool = False
    messages: list[str] = field(default_factory=list)


def scaffold_extra_available() -> bool:
    """Return True when the optional cookiecutter scaffold extra is importable.

    Returns:
        bool: True when ``cookiecutter`` is installed.

    Examples:
        >>> isinstance(scaffold_extra_available(), bool)
        True
    """
    return find_spec("cookiecutter") is not None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def _package_module(name: str) -> str:
    module = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if module and module[0].isdigit():
        module = f"p_{module}"
    return module or "project"


def _render_template(
    text: str, *, project_name: str, package_module: str, package_slug: str
) -> str:
    return (
        text.replace("{{project_name}}", project_name)
        .replace("{{package_module}}", package_module)
        .replace("{{package_slug}}", package_slug)
    )


def render_project_skeleton(project_dir: Path, project_name: str) -> None:
    """Write the packaged offline project skeleton under *project_dir*.

    Args:
        project_dir (Path): New project root (must not exist or be empty).
        project_name (str): Human project directory name.

    Raises:
        GreenfieldError: When template resources are missing.

    Examples:
        >>> isinstance(render_project_skeleton, object)
        True
    """
    package_module = _package_module(project_name)
    package_slug = _slugify(project_name)
    root = pkg_files("tripll.templates").joinpath(_SKELETON_ROOT)
    for template_name, rel_pattern in _TEMPLATE_MAP:
        resource = root.joinpath(template_name)
        try:
            raw = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise GreenfieldError(f"missing packaged skeleton template: {template_name}") from exc
        rel = rel_pattern.format(package_module=package_module)
        dest = project_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            _render_template(
                raw,
                project_name=project_name,
                package_module=package_module,
                package_slug=package_slug,
            ),
            encoding="utf-8",
        )


def _git_init(repo_root: Path) -> None:
    if (repo_root / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "init", "-q"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return


def _scaffold_with_cookiecutter(project_name: str, parent: Path) -> Path:
    if not scaffold_extra_available():
        raise GreenfieldError(
            "cookiecutter scaffold requires the tripll scaffold extra — install with: "
            "uv sync --extra scaffold  (or: pip install 'tripll[scaffold]')"
        )
    from tripll.scaffold import ScaffoldError, scaffold_package

    try:
        project_dir = scaffold_package(project_name=project_name, output_dir=parent)
    except ScaffoldError as exc:
        raise GreenfieldError(str(exc)) from exc
    if project_dir is None:
        raise GreenfieldError(
            f"cookiecutter scaffold did not create {project_name!r} under {parent}"
        )
    return project_dir.resolve()


def new_project(
    name: str,
    *,
    output_dir: Path | None = None,
    force: bool = False,
    cookiecutter: bool = False,
) -> GreenfieldResult:
    """Scaffold a new project and run shared brownfield onboarding emitters.

    Offline packaged templates are the default (no network). Pass
    ``cookiecutter=True`` to use the optional cookiecutter extra instead.

    Args:
        name (str): Project directory name.
        output_dir (Path | None): Parent directory (default: current working directory).
        force (bool): Overwrite existing onboarding artefacts when True.
        cookiecutter (bool): Use cookiecutter-pypackage when the scaffold extra is installed.

    Returns:
        GreenfieldResult: Structured summary for CLI reporting.

    Raises:
        GreenfieldError: When the target path is unusable or scaffolding fails.

    Examples:
        >>> isinstance(new_project, object)
        True
    """
    cleaned = name.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or cleaned.startswith("."):
        raise GreenfieldError(f"invalid project name: {name!r}")

    parent = (output_dir or Path.cwd()).resolve()
    project_dir = (parent / cleaned).resolve()
    skeleton_created = False

    if (
        project_dir.exists()
        and any(project_dir.iterdir())
        and not (project_dir / "tripll.toml").is_file()
        and not force
    ):
        raise GreenfieldError(
            f"{project_dir} already exists and is not a tripll project — remove it or pass --force"
        )

    if not (project_dir / "pyproject.toml").is_file():
        project_dir.mkdir(parents=True, exist_ok=True)
        if cookiecutter:
            project_dir = _scaffold_with_cookiecutter(cleaned, parent)
        else:
            render_project_skeleton(project_dir, cleaned)
        skeleton_created = True
        _git_init(project_dir)

    brownfield = run_brownfield_init(repo_root=project_dir, force=force)

    messages = [
        f"Project     : {project_dir}",
        f"Skeleton    : {'created' if skeleton_created else 'reused'}",
        f"Language    : {brownfield.layout.language}",
        f"Evaluation  : {brownfield.evaluation_path}",
    ]
    messages.extend(brownfield.messages)

    return GreenfieldResult(
        project_dir=project_dir,
        brownfield=brownfield,
        skeleton_created=skeleton_created,
        messages=messages,
    )
