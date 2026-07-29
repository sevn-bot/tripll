"""Partial CI gate on changed Python paths (local iteration only).

``make ci-changed`` runs ruff and mypy on changed files plus scoped pytest on
files changed vs ``TRIPLL_CI_BASE`` (default ``origin/main``). Prefer
``make ci-affected`` when non-Python paths may have changed. Not a merge gate —
use ``make ci``.

Module: scripts.ci_changed
Depends: scripts.ci_lib

Exports:
    main — discover changed paths and run partial Python gates.

Examples:
    >>> from ci_lib import REPO_ROOT
    >>> REPO_ROOT.name
    'tripll'
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_lib import REPO_ROOT, collect_changed_py, run_python_gates


def main() -> int:
    """Run partial Python gates on changed files.

    Returns:
        int: ``0`` when all steps pass or nothing changed; ``1`` on failure.

    Examples:
        >>> main() in (0, 1)
        True
    """
    changed = collect_changed_py()
    if not changed:
        print("[ci-changed] no changed Python files under src/, tests/, scripts/ — skipped")
        return 0

    rel_paths = [str(p.relative_to(REPO_ROOT)) for p in changed]
    print("[ci-changed] files:", ", ".join(rel_paths), flush=True)
    return run_python_gates(changed, prefix="ci-changed")


if __name__ == "__main__":
    raise SystemExit(main())
