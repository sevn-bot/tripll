"""Minimal demo package for delivery fixture-repo walkthrough."""

from __future__ import annotations

__all__ = ["greet"]


def greet() -> str:
    """Return a fixed greeting string."""
    return "delivery-fixture"
