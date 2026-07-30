"""Provider-neutral tracker protocol for epic breakdown round trips (R30, ADR 016).

Exports:
    Epic — parent work item metadata.
    Ticket — child work item metadata.
    Tracker — protocol for fetch/list/create/publish operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["Epic", "Ticket", "Tracker"]


@dataclass(frozen=True)
class Epic:
    """Parent work item returned by :meth:`Tracker.fetch_epic`."""

    ref: str
    title: str
    body: str = ""


@dataclass(frozen=True)
class Ticket:
    """Child work item returned by :meth:`Tracker.list_children` or passed to create."""

    ref: str
    title: str
    body: str = ""


@runtime_checkable
class Tracker(Protocol):
    """Seam for reading an epic and publishing a wave breakdown downstream."""

    def fetch_epic(self, ref: str) -> Epic:
        """Load the parent work item identified by *ref*."""
        ...

    def list_children(self, ref: str) -> list[Ticket]:
        """Return existing child items linked to the parent *ref*."""
        ...

    def create_child(self, parent: str, ticket: Ticket) -> str:
        """Create one child under *parent* and return its ref."""
        ...

    def publish_breakdown(self, parent: str, markdown: str) -> str | None:
        """Publish a breakdown summary on *parent*; return a ref when available."""
        ...
