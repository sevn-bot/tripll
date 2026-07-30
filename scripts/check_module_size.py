"""Fail when any non-allowlisted ``src/tripll`` module exceeds 1,000 lines.

Module: scripts.check_module_size
Exports:
    main — CLI entry; scans ``src/tripll/**/*.py`` and reports violations.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "tripll"
MAX_LINES = 1000

# Explicit allowlist (R39): over the limit but not named in #16 — tracked in #62.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # inject.py orchestrates run dispatch; not in #16 scope — #62.
        "src/tripll/inject.py",
        # skw/render.py is the SKW template renderer; not in #16 scope — #62.
        "src/tripll/skw/render.py",
    }
)


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8"))


def _violations() -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        count = _line_count(path)
        if count <= MAX_LINES:
            continue
        if rel in ALLOWLIST:
            continue
        found.append((rel, count))
    return sorted(found, key=lambda item: (-item[1], item[0]))


def main() -> int:
    """Scan ``src/tripll`` modules and fail on oversized files outside the allowlist.

    Returns:
        int: ``0`` when every non-allowlisted module is within the limit, else ``1``.
    """
    violations = _violations()
    if not violations:
        print(
            f"module-size-check: ok — all non-allowlisted modules ≤ {MAX_LINES} lines",
            file=sys.stderr,
        )
        return 0

    print("module-size-check: oversized modules (limit 1000 lines):", file=sys.stderr)
    for rel, count in violations:
        print(f"  {rel}: {count} lines", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
