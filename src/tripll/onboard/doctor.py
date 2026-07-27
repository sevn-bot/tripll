"""Preflight diagnostics — ``tripll doctor`` (W13).

Exports:
    DoctorReport — structured preflight result.
    run_doctor — print report and return exit code.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer

from tripll.adapters import BACKENDS, get_adapter
from tripll.config import (
    TripllConfig,
    load_config,
    repo_config_path,
    user_config_path,
    wave_plan_template_path,
)
from tripll.onboard.nextstep import compute_next_step
from tripll.onboard.setup import AUTH_FIX_COMMANDS
from tripll.pipeline import default_runs_root
from tripll.repo_root import resolve_repo_root

__all__ = ["DoctorReport", "run_doctor"]

_OPTIONAL_EXTRAS = ("graph", "kg", "api", "obs", "scaffold")


@dataclass
class DoctorReport:
    """Structured ``tripll doctor`` output.

    Args:
        python_version (str): Running interpreter version.
        extras (dict[str, bool]): Optional extra install state.
        providers (dict[str, tuple[bool, str]]): Backend availability + detail.
        repo_root (Path): Resolved repository root.
        runs_root (Path): Resolved runs directory.
        config (TripllConfig): Loaded configuration.
        template_ok (bool): Packaged v3 template resolves.
        template_path (Path | None): Resolved template path when ok.
        next_step (str | None): Optional next command hint.
        available_provider_count (int): Count of reachable backends.
        lines (list[str]): Human-readable report lines.
    """

    python_version: str
    extras: dict[str, bool]
    providers: dict[str, tuple[bool, str]]
    repo_root: Path
    runs_root: Path
    config: TripllConfig
    template_ok: bool
    template_path: Path | None
    next_step: str | None
    available_provider_count: int
    lines: list[str] = field(default_factory=list)


def _extra_installed(name: str) -> bool:
    probes: dict[str, str] = {
        "graph": "langgraph",
        "kg": "networkx",
        "api": "fastapi",
        "obs": "logfire",
        "scaffold": "cookiecutter",
    }
    module = probes.get(name, name)
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def build_doctor_report(*, plan_path: Path | None = None) -> DoctorReport:
    """Collect preflight state without printing.

    Args:
        plan_path (Path | None): Plan file for ``--next`` hint computation.

    Returns:
        DoctorReport: Full diagnostic snapshot.
    """
    repo_root = resolve_repo_root()
    env_runs = os.environ.get("TRIPLL_RUNS")
    runs_root = Path(env_runs).resolve() if env_runs else default_runs_root(repo_root)
    cfg = load_config(repo_root=repo_root)

    providers: dict[str, tuple[bool, str]] = {}
    available = 0
    for name in BACKENDS:
        caps = get_adapter(name).capabilities()
        providers[name] = (caps.available, caps.detail)
        if caps.available:
            available += 1

    extras = {name: _extra_installed(name) for name in _OPTIONAL_EXTRAS}

    template_ok = False
    template_path: Path | None = None
    try:
        template_path = wave_plan_template_path()
        text = template_path.read_text(encoding="utf-8")
        template_ok = "waveorch_format = 3" in text
    except (OSError, FileNotFoundError):
        template_ok = False

    next_step: str | None = None
    if plan_path is not None and plan_path.is_file():
        next_step = compute_next_step(plan_path=plan_path)

    user_path = user_config_path()
    repo_path = repo_config_path(repo_root)

    lines: list[str] = [
        "tripll doctor",
        f"  Python     : {sys.version.split()[0]} ({sys.executable})",
        "  Extras     : "
        + ", ".join(f"{name}={'yes' if ok else 'no'}" for name, ok in extras.items()),
        f"  Repo root  : {repo_root}",
        f"  Runs root  : {runs_root}",
        "  Config     :",
        f"    user  : {user_path} ({'present' if user_path.is_file() else 'missing'})",
        f"    repo  : {repo_path} ({'present' if repo_path.is_file() else 'missing'})",
        f"    winner: default_provider from {cfg.sources.default_provider}",
        f"    default_provider = {cfg.default_provider}",
        "  Providers  :",
    ]
    for name, (ok, detail) in providers.items():
        mark = "OK" if ok else "MISSING"
        lines.append(f"    {name}: {mark} — {detail}")
        if not ok and name in AUTH_FIX_COMMANDS:
            lines.append(f"      fix: {AUTH_FIX_COMMANDS[name]}")

    if template_ok:
        lines.append(f"  Template   : v3 wave-plan OK ({template_path})")
    else:
        lines.append("  Template   : v3 wave-plan MISSING from wheel")

    if next_step:
        lines.append(f"  Next step  : {next_step}")

    return DoctorReport(
        python_version=sys.version.split()[0],
        extras=extras,
        providers=providers,
        repo_root=repo_root,
        runs_root=runs_root,
        config=cfg,
        template_ok=template_ok,
        template_path=template_path,
        next_step=next_step,
        available_provider_count=available,
        lines=lines,
    )


def run_doctor(*, plan_path: Path | None = None) -> int:
    """Print preflight report; exit non-zero when no provider is available.

    Args:
        plan_path (Path | None): Plan file for ``--next`` hint.

    Returns:
        int: Process exit code (0 when at least one provider is available).

    Examples:
        >>> run_doctor() in (0, 1)
        True
    """
    report = build_doctor_report(plan_path=plan_path)
    for line in report.lines:
        typer.echo(line)

    if report.available_provider_count == 0:
        typer.echo("FAIL — no provider available", err=True)
        return 1
    return 0
