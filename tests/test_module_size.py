"""Module line-count characterization for god-module extraction (GOD-06 / Final)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src" / "tripll"
_MAX_LINES = 1000

# Final allowlist (R39) — not yet enforced at baseline; documented for the xfail message.
_FINAL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "src/tripll/inject.py",
        "src/tripll/skw/render.py",
    }
)


def _line_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        counts[rel] = sum(1 for _ in path.open(encoding="utf-8"))
    return counts


def _oversized_outside_allowlist() -> list[tuple[str, int]]:
    violations: list[tuple[str, int]] = []
    for rel, count in _line_counts().items():
        if count <= _MAX_LINES:
            continue
        if rel in _FINAL_ALLOWLIST:
            continue
        violations.append((rel, count))
    return sorted(violations, key=lambda item: (-item[1], item[0]))


@pytest.mark.xfail(reason="green after Final: make module-size-check gate", strict=False)
def test_module_size_under_limit_outside_allowlist() -> None:
    """Every ``src/tripll/**/*.py`` outside the allowlist is ≤ 1000 lines."""
    violations = _oversized_outside_allowlist()
    if violations:
        details = ", ".join(f"{path} ({lines} lines)" for path, lines in violations)
        pytest.fail(f"oversized modules: {details}")
