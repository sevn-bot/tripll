"""Tests for tracing and logging no-op / verbose behavior (Wave W1.5)."""

from __future__ import annotations

import os

import pytest

from tripll.skw.logging import configure_logging
from tripll.skw.tracing import configure_tracing, span


def test_tracing_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKW_TRACE", raising=False)
    configure_tracing(enabled=False)
    with span("pipeline.validate", wave_id="W1"):
        pass


def test_tracing_noop_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKW_TRACE", raising=False)
    configure_tracing(enabled=os.environ.get("SKW_TRACE") == "1")
    with span("driver.run_agent"):
        pass


def test_logging_noop_when_not_verbose() -> None:
    configure_logging(verbose=False)


def test_verbose_installs_colored_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKW_VERBOSE", "1")
    assert configure_logging(verbose=True) is True


def test_tracing_enabled_with_skw_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKW_TRACE", "1")
    assert configure_tracing(enabled=True) is True
