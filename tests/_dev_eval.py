"""Shared dev_eval fixture helpers for tripll tests."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tripll.pipeline import RunsRoot

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_EVAL = _REPO_ROOT / "plan" / "dev_eval_14062026"
_ORCH_PROMPT = "parallel-wave-orchestrator-prompt.md"


def copy_dev_eval_input(runs_root: RunsRoot, *, with_orchestrator: bool = True) -> Path:
    """Copy the dev_eval plan set into *runs_root* input (Mode A).

    Args:
        runs_root (RunsRoot): Initialized runs root.
        with_orchestrator (bool): When ``False``, omit the orchestrator prompt so
            the graph stays in parallel lane mode.

    Returns:
        Path: Claim-ready input directory under ``runs_root.input_dir``.
    """
    dest = runs_root.input_dir / "dev_eval"
    shutil.copytree(DEV_EVAL, dest)
    if not with_orchestrator:
        (dest / _ORCH_PROMPT).unlink(missing_ok=True)
    return dest
