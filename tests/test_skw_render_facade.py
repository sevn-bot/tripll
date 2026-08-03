"""Characterization tests for ``tripll.skw.render`` (#62, open-issues W1).

Locks import-surface identity before W6 façade extraction (ADR 013). Green at
baseline — W6 adds ``render_core`` identity rows without editing this file.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

import tripll.skw.render as render_mod

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Module docstring ``Exports:`` inventory (ADR 013 façade contract).
DOCUMENTED_RENDER_EXPORTS: tuple[str, ...] = (
    "PLACEHOLDER_RE",
    "topo_sort",
    "build_context",
    "load_prompt_template",
    "render_prompt",
    "check_unfilled",
    "main",
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


IMPORTED_RENDER_NAMES = frozenset(
    _collect_imported_names(
        module="tripll.skw.render",
        roots=[_REPO_ROOT / "src", _REPO_ROOT / "tests"],
    )
)


def test_render_module_name_contract() -> None:
    """Façade module keeps ``tripll.skw.render`` identity after W6 extraction."""
    assert render_mod.__name__ == "tripll.skw.render"


def test_render_docstring_exports_match_inventory() -> None:
    """Docstring ``Exports:`` block matches the locked inventory table."""
    assert _parse_docstring_exports(render_mod) == DOCUMENTED_RENDER_EXPORTS


@pytest.mark.parametrize("name", DOCUMENTED_RENDER_EXPORTS)
def test_render_documented_export_resolves(name: str) -> None:
    """Every documented export resolves on ``tripll.skw.render``."""
    _assert_resolves(render_mod, name)


@pytest.mark.parametrize("name", sorted(IMPORTED_RENDER_NAMES))
def test_render_imported_name_resolves(name: str) -> None:
    """Every name imported from ``tripll.skw.render`` resolves on the façade."""
    _assert_resolves(render_mod, name)


@pytest.mark.parametrize("name", DOCUMENTED_RENDER_EXPORTS)
def test_render_symbol_name_matches_attribute(name: str) -> None:
    """Documented exports keep ``obj.__name__ == attr`` (naming contract)."""
    obj = getattr(render_mod, name)
    if isinstance(obj, type) or callable(obj):
        assert obj.__name__ == name
