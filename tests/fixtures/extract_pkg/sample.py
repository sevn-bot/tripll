"""Minimal Python package for deterministic AST extractor fixtures."""

from __future__ import annotations


def helper() -> int:
    return 1


def caller() -> int:
    return helper()
