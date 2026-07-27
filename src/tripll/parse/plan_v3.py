"""Parse shims — delegate legacy and v3 plan reads to ``tripll.plan``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tripll.plan.compat_v1_v2 import read_legacy_plan
from tripll.plan.format_v3 import emit_plan_v3, parse_plan_v3
from tripll.plan.shape_checks import compile_plan, derive_one_writer_map

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "compile_plan_v3",
    "derive_one_writer_map",
    "emit_plan_v3",
    "parse_plan_v3",
    "read_legacy_plan",
]


def compile_plan_v3(plan: dict[str, Any]) -> dict[str, Any]:
    """Run v3 compile-time shape checks (fake-edge, stop-rule, one-writer)."""
    return compile_plan(plan)


def read_plan_file(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read any supported plan format and return a v3 dict."""
    from pathlib import Path as PathCls

    plan_path = PathCls(path)
    text = plan_path.read_text(encoding="utf-8")
    if text.lstrip().startswith("waveorch_format = 3"):
        return parse_plan_v3(text), []
    return read_legacy_plan(plan_path)
