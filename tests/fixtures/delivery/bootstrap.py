"""Bootstrap a git fixture repo from ``minimal-repo/`` template.

Exports:
    FIXTURE_TEMPLATE — path to the checked-in template tree.
    bootstrap_minimal_repo — copy template, ``git init``, initial commit.
    copy_delivery_smoke_input — install the wave plan into a runs input set.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FIXTURE_TEMPLATE = Path(__file__).resolve().parent / "minimal-repo"
_WAVE_PLAN = FIXTURE_TEMPLATE / "docs" / "plans" / "delivery-smoke-wave-plan.md"


def bootstrap_minimal_repo(dest: Path) -> Path:
    """Copy the minimal-repo template and create an initial git commit.

    Args:
        dest (Path): Directory for the new fixture repository root.

    Returns:
        Path: ``dest`` after ``git init`` and first commit on ``main``.
    """
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(FIXTURE_TEMPLATE, dest)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run(["git", "add", "."], cwd=dest, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=delivery-fixture@test",
            "-c",
            "user.name=delivery-fixture",
            "commit",
            "-qm",
            "init: delivery fixture repo",
        ],
        cwd=dest,
        check=True,
    )
    # Default integrate base_ref is ``test-pre`` (see plan_integration).
    subprocess.run(["git", "branch", "test-pre"], cwd=dest, check=True)
    return dest


def copy_delivery_smoke_input(runs_input_set: Path) -> Path:
    """Copy the delivery-smoke wave plan into a runs input set directory.

    Args:
        runs_input_set (Path): e.g. ``runs/input/delivery-smoke``.

    Returns:
        Path: The input set directory (created if needed).
    """
    runs_input_set.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_WAVE_PLAN, runs_input_set / "delivery-smoke-wave-plan.md")
    return runs_input_set
