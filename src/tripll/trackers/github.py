"""GitHub-backed :class:`~tripll.trackers.base.Tracker` (wraps ``github.issues``)."""

from __future__ import annotations

from tripll.github import issues
from tripll.trackers.base import Epic, Ticket

__all__ = ["GitHubTracker"]


class GitHubTracker:
    """Tracker implementation that delegates to the existing ``github/`` module."""

    def __init__(self, *, repo: str | None = None) -> None:
        self._repo = repo

    def fetch_epic(self, ref: str) -> Epic:
        row = issues.view_epic(ref, repo=self._repo)
        return Epic(ref=row["ref"], title=row["title"], body=row["body"])

    def list_children(self, ref: str) -> list[Ticket]:
        rows = issues.list_child_tickets(ref, repo=self._repo)
        return [Ticket(ref=row["ref"], title=row["title"], body=row["body"]) for row in rows]

    def create_child(self, parent: str, ticket: Ticket) -> str:
        return issues.create_child_ticket(
            parent,
            title=ticket.title,
            body=ticket.body,
            repo=self._repo,
        )

    def publish_breakdown(self, parent: str, markdown: str) -> str | None:
        return issues.publish_breakdown_comment(parent, markdown, repo=self._repo)
