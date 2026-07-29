"""Path-aware partial CI gate (local iteration / wave agents).

``make ci-affected`` unions Python partial gates (``ci-changed`` logic) with
``make`` targets selected from changed paths vs ``TRIPLL_CI_BASE``. Not a merge
gate — use ``make ci-resume`` at wave boundary / before merge.

Module: scripts.ci_affected
Depends: scripts.ci_lib

Exports:
    main — run Python gates plus path-mapped ``make`` targets.

Examples:
    >>> from scripts.ci_lib import match_path_rules
    >>> "about-site-check" in match_path_rules(["about-tripll/_sources/index.md"])
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_lib import (
    collect_changed_paths,
    collect_changed_py,
    match_path_rules,
    run_make_targets,
    run_python_gates,
)


def main() -> int:
    """Run path-aware partial CI gates.

    Returns:
        int: ``0`` when all steps pass or nothing changed; ``1`` on failure.

    Examples:
        >>> main() in (0, 1)
        True
    """
    all_changed = collect_changed_paths()
    py_changed = collect_changed_py()
    make_targets = match_path_rules(all_changed)

    if not all_changed:
        print("[ci-affected] no changed files — skipped")
        return 0

    print("[ci-affected] changed:", ", ".join(all_changed), flush=True)
    if make_targets:
        print("[ci-affected] make targets:", ", ".join(make_targets), flush=True)

    exit_code = 0
    if py_changed:
        code = run_python_gates(py_changed, prefix="ci-affected")
        if code != 0:
            exit_code = code

    if make_targets:
        code = run_make_targets(make_targets, prefix="ci-affected")
        if code != 0 and exit_code == 0:
            exit_code = code

    if not py_changed and not make_targets:
        print("[ci-affected] no matching gates — skipped")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
