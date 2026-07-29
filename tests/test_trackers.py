"""Tracker protocol and idempotent plan publish (W1.7, R30)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.rules._helpers import require_attr

pytestmark = pytest.mark.tier1


@dataclass
class _FakeEpic:
    ref: str
    title: str
    body: str = ""


@dataclass
class _FakeTicket:
    ref: str
    title: str
    body: str = ""


@dataclass
class FakeTracker:
    """In-memory Tracker for protocol conformance (R30 — no base.py edits)."""

    epic: _FakeEpic
    children: list[_FakeTicket] = field(default_factory=list)
    published: list[str] = field(default_factory=list)
    create_log: list[str] = field(default_factory=list)

    def fetch_epic(self, ref: str) -> _FakeEpic:
        assert ref == self.epic.ref
        return self.epic

    def list_children(self, ref: str) -> list[_FakeTicket]:
        assert ref == self.epic.ref
        return list(self.children)

    def create_child(self, parent: str, ticket: Any) -> str:
        assert parent == self.epic.ref
        title = getattr(ticket, "title", str(ticket))
        for existing in self.children:
            if existing.title == title:
                return existing.ref
        ref = f"{parent}#{len(self.children) + 1}"
        self.children.append(_FakeTicket(ref=ref, title=title))
        self.create_log.append(title)
        return ref

    def publish_breakdown(self, parent: str, markdown: str) -> str | None:
        assert parent == self.epic.ref
        self.published.append(markdown)
        return f"{parent}#summary"


@pytest.mark.xfail(reason="green after W6: fake tracker conforms to protocol", strict=False)
def test_fake_tracker_protocol_conformance_without_editing_base() -> None:
    """A second Tracker implementation requires no edit to base.py (R30)."""
    tracker_protocol = require_attr("tripll.trackers.base", "Tracker")
    fake = FakeTracker(epic=_FakeEpic(ref="EPIC-1", title="AI layer"))
    assert isinstance(fake, tracker_protocol)
    epic = fake.fetch_epic("EPIC-1")
    assert epic.title == "AI layer"
    ref = fake.create_child("EPIC-1", _FakeTicket(ref="", title="W2 — rules derive"))
    assert ref.startswith("EPIC-1#")


@pytest.mark.xfail(
    reason="green after W6: idempotent publish creates nothing on second run",
    strict=False,
)
def test_publish_idempotent_second_run_creates_nothing(tmp_path: Path) -> None:
    """Second publish lists existing children and creates zero tickets (spec step 3)."""
    publish_plan_breakdown = require_attr("tripll.trackers.publish", "publish_plan_breakdown")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n\n## Wave W2\n\n- [ ] task\n", encoding="utf-8")
    tracker = FakeTracker(
        epic=_FakeEpic(ref="EPIC-42", title="Compounding"),
        children=[_FakeTicket(ref="EPIC-42#1", title="W2 — rules derive")],
    )
    first = publish_plan_breakdown(
        tracker=tracker,
        plan_path=plan_path,
        parent_ref="EPIC-42",
    )
    assert first.created == 0 or first.skipped >= 1

    before = len(tracker.children)
    second = publish_plan_breakdown(
        tracker=tracker,
        plan_path=plan_path,
        parent_ref="EPIC-42",
    )
    assert len(tracker.children) == before
    assert second.created == 0
    assert second.skipped >= 1


@pytest.mark.tier2
@pytest.mark.xfail(reason="green after W6: real gh scratch publish", strict=False)
def test_real_gh_tracker_publish_dry_run() -> None:
    """Tier-2: gh-backed tracker when RUN_LIVE=1 and gh available."""
    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("tier-2 requires RUN_LIVE=1")
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        pytest.skip(f"gh not authenticated: {proc.stderr.strip()}")
    github_tracker_cls = require_attr("tripll.trackers.github", "GitHubTracker")
    tracker = github_tracker_cls()
    assert hasattr(tracker, "fetch_epic")


@pytest.mark.tier4
def test_github_reachability_canary() -> None:
    """Tier-4 canary: gh auth status (never blocks CI)."""
    proc = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode in (0, 1)
