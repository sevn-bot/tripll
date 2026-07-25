"""Verify node — run compiled Makefile targets before commit (Fix-W2).

Each wave state's ``verify`` list holds shell commands (typically ``make -C …``).
Non-zero exit aborts the graph before ``commit_{wid}``.

Exports:
    VerifyError — raised when a verify target exits non-zero.
    run_verify_targets — execute compiled verify commands for one wave.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from tripll.skw.runtime import is_dryrun, is_pytest

__all__: list[str] = ["VerifyError", "run_verify_targets"]

_REAL_SUBPROCESS_RUN = subprocess.run


class VerifyError(RuntimeError):
    """A verify Makefile target returned a non-zero exit code."""

    def __init__(self, exit_code: int, command: list[str]) -> None:
        self.exit_code = exit_code
        self.command = command
        cmd = " ".join(command)
        super().__init__(f"verify failed (exit {exit_code}): {cmd}")


def run_verify_targets(
    *,
    targets: list[str],
    kit_root: Path,
    wave_id: str | None = None,
) -> None:
    """Run each compiled verify command; fail loud on non-zero exit.

    Args:
        targets (list[str]): Shell commands from pipeline JSON (e.g. ``make -C …``).
        kit_root (Path): Kit root directory.
        wave_id (str | None): Optional wave id for error context.

    Raises:
        VerifyError: When any target exits non-zero.

    Examples:
        >>> run_verify_targets(targets=[], kit_root=Path("."))  # doctest: +SKIP
    """
    if not targets:
        return
    if is_pytest() and subprocess.run is _REAL_SUBPROCESS_RUN:
        return
    from tripll.skw.paths import repo_root_for_kit

    repo_root = repo_root_for_kit(kit_root)
    label = wave_id or "verify"
    for target in targets:
        cmd = shlex.split(target)
        if is_dryrun():
            quoted = " ".join(shlex.quote(arg) for arg in cmd)
            print(f"[dry-run] would run verify ({label}): {quoted}")
            continue
        result = subprocess.run(cmd, cwd=str(repo_root), check=False)
        if result.returncode != 0:
            raise VerifyError(result.returncode, cmd)
