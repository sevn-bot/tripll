"""Characterization tests for ``tripll.inject`` (#62, open-issues W1).

Locks import-surface identity before W5 façade extraction (ADR 013). Green at
baseline — W5 adds ``inject_dispatch`` identity rows without editing this file.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

import tripll.inject as inject_mod

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Module docstring ``Exports:`` inventory (ADR 013 façade contract).
DOCUMENTED_INJECT_EXPORTS: tuple[str, ...] = (
    "HotfixTask",
    "WaveAddTask",
    "ReconcileResult",
    "InjectError",
    "resolve_after_node_id",
    "validate_hotfix_inject",
    "plan_hotfix_inject",
    "apply_hotfix_inject",
    "plan_wave_add",
    "apply_wave_add",
    "merge_injected_artefacts",
    "merge_injected_hotfixes",
    "reconcile_run_graph",
    "load_hotfix_tasks",
    "load_wave_add_tasks",
)

_EXPORTS_RE = re.compile(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def _parse_docstring_exports(module: Any) -> tuple[str, ...]:
    doc = module.__doc__ or ""
    block = doc.split("Exports:", 1)[-1] if "Exports:" in doc else ""
    return tuple(_EXPORTS_RE.findall(block))


def _collect_imported_names(*, module: str, roots: Iterable[Path]) -> set[str]:
    names: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == module:
                    for alias in node.names:
                        if alias.name != "*":
                            names.add(alias.name)
    return names


def _assert_resolves(module: Any, name: str) -> None:
    assert hasattr(module, name), f"{module.__name__}.{name} missing from façade"
    assert getattr(module, name) is not None


IMPORTED_INJECT_NAMES = frozenset(
    _collect_imported_names(
        module="tripll.inject",
        roots=[_REPO_ROOT / "src", _REPO_ROOT / "tests", _REPO_ROOT / "scripts"],
    )
)


def test_inject_module_name_contract() -> None:
    """Façade module keeps ``tripll.inject`` identity after W5 extraction."""
    assert inject_mod.__name__ == "tripll.inject"


def test_inject_docstring_exports_match_inventory() -> None:
    """Docstring ``Exports:`` block matches the locked inventory table."""
    assert _parse_docstring_exports(inject_mod) == DOCUMENTED_INJECT_EXPORTS


@pytest.mark.parametrize("name", DOCUMENTED_INJECT_EXPORTS)
def test_inject_documented_export_resolves(name: str) -> None:
    """Every documented export resolves on ``tripll.inject``."""
    _assert_resolves(inject_mod, name)


@pytest.mark.parametrize("name", sorted(IMPORTED_INJECT_NAMES))
def test_inject_imported_name_resolves(name: str) -> None:
    """Every name imported from ``tripll.inject`` resolves on the façade."""
    _assert_resolves(inject_mod, name)


@pytest.mark.parametrize("name", DOCUMENTED_INJECT_EXPORTS)
def test_inject_symbol_name_matches_attribute(name: str) -> None:
    """Public symbols keep ``obj.__name__ == attr`` (submodule naming contract)."""
    obj = getattr(inject_mod, name)
    if isinstance(obj, type) or callable(obj):
        assert obj.__name__ == name
