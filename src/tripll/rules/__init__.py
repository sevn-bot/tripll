"""Derived rules and on-demand context modules (W2-W3).

Exports:
    model — Rule dataclass, frontmatter parse/render, origin validation.
    store — read/write ``.tripll/rules`` and ``.tripll/context``.
    derive — ``tripll rules derive`` backend consuming evaluation findings.
    pack — scope-aware brief packing under a token budget.
    promote — finding → proposed rule; operator promote/retire (R27).
    postmortem — contract vs attempt reconciliation (RULE-03).
"""

from __future__ import annotations

__all__ = ["derive", "model", "pack", "postmortem", "promote", "store"]
