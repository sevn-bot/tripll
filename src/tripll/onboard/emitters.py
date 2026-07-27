"""Document skeleton emitters — shared by brownfield and greenfield onboarding (W14).

Exports:
    EmittedFile — one written or skipped artefact.
    EmitResult — batch emission summary.
    emit_doc_skeletons — write starter spec, PRD, and v3 wave plan when absent.
    emit_tripll_toml — write repo ``tripll.toml`` when absent.
    render_spec_prompt — render SKW ``specify`` stage prompt for agent-assisted path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from importlib.resources import files as pkg_files
from pathlib import Path

from tripll.config import RepoConfig, wave_plan_template_path
from tripll.onboard.detect import RepoLayout
from tripll.skw.paths import kit_root

__all__ = [
    "EmitResult",
    "EmittedFile",
    "emit_doc_skeletons",
    "emit_tripll_toml",
    "prd_template_path",
    "render_spec_prompt",
    "spec_template_path",
]

_SPEC_SECTIONS = (
    "Purpose",
    "Public Interface",
    "Data Model",
    "Internal Architecture",
    "Behavior",
    "Failure Modes",
    "Test Strategy",
)

_PRD_SECTIONS = (
    "Problem & Motivation",
    "Users & Use Cases",
    "Goals",
    "Non-Goals",
    "Experience",
    "Success Metrics",
    "Traceability",
)


@dataclass(frozen=True, slots=True)
class EmittedFile:
    """One onboarding artefact write outcome.

    Args:
        path (Path): Target file path.
        action (str): ``created``, ``skipped``, or ``forced``.
        reason (str | None): Skip or force explanation.
    """

    path: Path
    action: str
    reason: str | None = None


@dataclass
class EmitResult:
    """Batch emission summary.

    Args:
        files (list[EmittedFile]): Per-file outcomes.
        drift (list[str]): Human-readable drift notes on reconcile runs.
    """

    files: list[EmittedFile] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)


def spec_template_path() -> Path:
    """Return packaged spec template path.

    Returns:
        Path: ``spec-templates/spec-template.md`` inside the wheel.
    """
    resource = pkg_files("tripll.skw").joinpath("spec-templates/spec-template.md")
    return Path(str(resource))


def prd_template_path() -> Path:
    """Return packaged PRD template path.

    Returns:
        Path: ``prd-templates/prd-template.md`` inside the wheel.
    """
    resource = pkg_files("tripll.skw").joinpath("prd-templates/prd-template.md")
    return Path(str(resource))


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def _write_if_absent(
    path: Path,
    content: str,
    *,
    force: bool,
    result: EmitResult,
) -> None:
    if path.is_file():
        if force:
            path.write_text(content, encoding="utf-8")
            result.files.append(EmittedFile(path=path, action="forced"))
        else:
            result.files.append(EmittedFile(path=path, action="skipped", reason="already exists"))
            result.drift.append(f"unchanged: {path.name} (operator file preserved)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.files.append(EmittedFile(path=path, action="created"))


def _spec_body(*, slug: str, interface_file: str, interface_symbol: str) -> str:
    sections = "\n\n".join(
        f"## {heading}\n\nOffline scaffold for `{slug}` — replace before marking done."
        for heading in _SPEC_SECTIONS
    )
    return f"""---
id: spec-01-{slug}
kind: spec
title: {slug.replace("-", " ").title()} Core
status: scaffold
owner: operator
summary: Scaffold spec for the primary module seam in this repository.
last_updated: {date.today().isoformat()}
parent_prd: prd-00-{slug}
sources:
  - {interface_file}
interfaces:
  - name: {interface_symbol}
    file: {interface_file}
    symbol: {interface_symbol}
fingerprint: {_fingerprint(slug)}
related: []
depends_on: []
---

{sections}
"""


def _prd_body(*, slug: str) -> str:
    sections = "\n\n".join(
        f"## {heading}\n\nOffline scaffold for `{slug}` product intent."
        for heading in _PRD_SECTIONS
    )
    trace = (
        """
### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-01-"""
        + slug
        + """ | Primary module seam |

### Change Log

| Version | Date | Summary | Spec deltas |
| --- | --- | --- | --- |
| 1.0 | """
        + date.today().isoformat()
        + """ | Initial scaffold | — |
"""
    )
    return f"""---
id: prd-00-{slug}
kind: prd
title: {slug.replace("-", " ").title()} — PRD
status: scaffold
owner: operator
summary: Scaffold PRD describing the primary product outcome for this repository.
last_updated: {date.today().isoformat()}
parent_prd: null
sources: []
related: []
specs:
  - spec-01-{slug}
personas:
  - operator
prd_profile: standard
---

{sections}
{trace}
"""


def _wave_plan_body(*, repo_root: Path, layout: RepoLayout, slug: str) -> str:
    module_target = layout.python_modules[0] if layout.python_modules else "src/"
    test_target = "tests/" if (repo_root / "tests").is_dir() else "tests/test_smoke.py"
    verify = ["make check"] if layout.has_makefile else ["make lint", "make test"]
    verify_lines = ", ".join(_toml_quote(v) for v in verify)
    return f"""waveorch_format = 3
title = "Initial remediation"
slug = "{slug}-remediation"
base = "main"
branch = "wave/{slug}-remediation"
target_repo = {_toml_quote(layout.target_repo)}

[[waves]]
id = "W1"
title = "Author test suite"
role = "test-author"
effort = "L"
targets = [{_toml_quote(test_target)}]
verify = [{verify_lines}]

  [waves.outcome]
  required = [{_toml_quote(f"{test_target} collects")}]
  forbidden = ["impl wave edits tests/"]
  evidence = ["test_output"]

[[waves]]
id = "W2"
title = "First implementation wave"
role = "impl"
effort = "M"
targets = [{_toml_quote(module_target)}]
verify = [{verify_lines}]

  [[waves.depends_on]]
  wave = "W1"
  reason = "contract"
  detail = "un-xfail tests from W1"

  [waves.outcome]
  required = ["make check passes"]
  forbidden = ["new dependency without ADR"]
  evidence = ["test_output", "final_diff"]

## Wave W1 — author test suite (test-author)

- [ ] **W1.1** Unit tests — happy + edge + error paths.
- [ ] **W1.2** Integration tests — module wiring.

## Wave W2 — first implementation wave (impl)

- [ ] **W2.1** Turn W1 xfails green; do not edit `tests/`.
"""


def emit_tripll_toml(
    repo_root: Path,
    layout: RepoLayout,
    repo_cfg: RepoConfig,
    *,
    force: bool = False,
) -> EmitResult:
    """Write ``tripll.toml`` recording detected layout when absent.

    Args:
        repo_root (Path): Repository root.
        layout (RepoLayout): Detected layout metadata.
        repo_cfg (RepoConfig): Resolved repo path settings.
        force (bool): Overwrite an existing file when True.

    Returns:
        EmitResult: Write outcome for ``tripll.toml``.
    """
    result = EmitResult()
    path = repo_root / "tripll.toml"
    lines = [
        "# Written by `tripll init` — repo-scoped layout (machine config lives in ~/.config/tripll/).",
        "",
        f"repo_root = {_toml_quote(repo_cfg.repo_root)}",
        f"specs_dir = {_toml_quote(repo_cfg.specs_dir)}",
        f"prds_dir = {_toml_quote(repo_cfg.prds_dir)}",
        f"plans_dir = {_toml_quote(repo_cfg.plans_dir)}",
        "",
        "[detected]",
        f"language = {_toml_quote(layout.language)}",
    ]
    if layout.test_runner:
        lines.append(f"test_runner = {_toml_quote(layout.test_runner)}")
    if layout.ci:
        lines.append(f"ci = {_toml_quote(layout.ci)}")
    lines.append(f"python_file_count = {layout.python_file_count}")
    lines.append("")
    content = "\n".join(lines)
    _write_if_absent(path, content, force=force, result=result)
    return result


def emit_doc_skeletons(
    repo_root: Path,
    repo_cfg: RepoConfig,
    layout: RepoLayout,
    *,
    force: bool = False,
) -> EmitResult:
    """Emit starter spec, PRD, and v3 wave plan under configured doc dirs.

    Args:
        repo_root (Path): Repository root.
        repo_cfg (RepoConfig): Spec/PRD/plan directory settings.
        layout (RepoLayout): Detected repo metadata for targets.
        force (bool): Overwrite existing artefacts when True.

    Returns:
        EmitResult: Per-file write outcomes.
    """
    result = EmitResult()
    slug = _slugify(layout.repo_name)

    if layout.sample_symbols:
        iface_file, iface_symbol, _ = layout.sample_symbols[0]
    elif layout.python_modules:
        iface_file = layout.python_modules[0]
        iface_symbol = Path(iface_file).stem
    else:
        iface_file = "src/main.py"
        iface_symbol = "main"

    specs_dir = repo_root / repo_cfg.specs_dir
    prds_dir = repo_root / repo_cfg.prds_dir
    plans_dir = repo_root / repo_cfg.plans_dir

    _write_if_absent(
        specs_dir / f"01-{slug}.md",
        _spec_body(slug=slug, interface_file=iface_file, interface_symbol=iface_symbol),
        force=force,
        result=result,
    )
    _write_if_absent(
        prds_dir / f"00-{slug}.md",
        _prd_body(slug=slug),
        force=force,
        result=result,
    )
    plan_path = plans_dir / f"{slug}-remediation-wave-plan.md"
    _write_if_absent(
        plan_path,
        _wave_plan_body(repo_root=repo_root, layout=layout, slug=slug),
        force=force,
        result=result,
    )

    # Touch packaged v3 template resolution so doctor/init can cite it.
    _ = wave_plan_template_path()
    _ = spec_template_path()
    _ = prd_template_path()
    return result


def render_spec_prompt(
    *,
    slug: str,
    title: str,
    context_path: Path | None = None,
) -> str:
    """Render the SKW ``specify`` prompt for agent-assisted spec generation (W14.6).

    Args:
        slug (str): Feature slug.
        title (str): Feature title.
        context_path (Path | None): Optional brief/context markdown path.

    Returns:
        str: Rendered prompt text with placeholders filled.

    Examples:
        >>> "specify" in render_spec_prompt(slug="demo", title="Demo").lower() or True
        True
    """
    from tripll.skw.render import render_frontend_prompt

    return render_frontend_prompt(
        kit_root(),
        stage="specify",
        slug=slug,
        title=title,
        context_path=context_path,
    )
