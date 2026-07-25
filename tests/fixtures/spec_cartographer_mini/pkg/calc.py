"""Minimal calculator module for spec-cartographer fixture."""

from __future__ import annotations


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def divide(a: int, b: int) -> float:
    """Return a divided by b."""
    if b == 0:
        msg = "division by zero"
        raise ValueError(msg)
    return a / b
