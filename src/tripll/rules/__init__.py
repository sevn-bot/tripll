"""Derived rules and on-demand context modules (W2).

Exports:
    model — Rule dataclass, frontmatter parse/render, origin validation.
    store — read/write ``.tripll/rules`` and ``.tripll/context``.
    derive — ``tripll rules derive`` backend consuming evaluation findings.
    pack — scope-aware brief packing under a token budget.
"""

from __future__ import annotations

__all__ = ["derive", "model", "pack", "store"]
