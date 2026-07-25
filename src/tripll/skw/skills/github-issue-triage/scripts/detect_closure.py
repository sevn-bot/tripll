#!/usr/bin/env python3
"""Deterministic maintainer-gated issue closure detection.

Usage:
  detect_closure.py --issue-json path.json [--timeline-json path.json]
                    [--comments-json path.json] [--prs-json path.json]

Pure decision function: :func:`decide_closure`. CLI loads JSON fixtures or
live ``gh`` payloads and prints a decision object.

Decision shape:
  {
    "number": 21,
    "should_close": true,
    "reason": "merged_pr" | "maintainer_comment" | "closing_commit" | null,
    "evidence": ["PR #42 merged by alice (MEMBER)", ...],
    "maintainer": "alice",
    "assoc": "MEMBER",
    "close_reason": "completed"
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# GitHub closing keywords (case-insensitive) that auto-close when a PR merges.
_CLOSING_KW = re.compile(
    r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s+#(\d+)\b",
    re.IGNORECASE,
)

_RESOLVED_COMMENT = re.compile(
    r"\b(?:fixed|resolved|shipped|completed|done|closing)\b",
    re.IGNORECASE,
)


def _is_maintainer(assoc: str | None) -> bool:
    return (assoc or "").upper() in MAINTAINER_ASSOCIATIONS


def _extract_assoc(obj: dict[str, Any]) -> str:
    for key in ("authorAssociation", "author_association", "assoc"):
        val = obj.get(key)
        if isinstance(val, str):
            return val.upper()
    author = obj.get("author")
    if isinstance(author, dict):
        for key in ("authorAssociation", "author_association"):
            val = author.get(key)
            if isinstance(val, str):
                return val.upper()
    return ""


def _extract_login(obj: dict[str, Any]) -> str:
    for key in ("login", "user", "author", "mergedBy", "merged_by"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            login = val.get("login")
            if isinstance(login, str) and login.strip():
                return login.strip()
    return ""


def decide_closure(
    issue: dict[str, Any],
    *,
    timeline: list[dict[str, Any]] | None = None,
    comments: list[dict[str, Any]] | None = None,
    prs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Decide whether an open issue should be closed (maintainer-gated).

    Args:
        issue: Issue payload (number, state, title, …).
        timeline: Optional timeline events from GitHub API.
        comments: Optional issue comments (with author_association).
        prs: Optional related PRs (merged, body/title with closing keywords).

    Returns:
        Decision dict with should_close, reason, evidence, maintainer, assoc.
    """
    number = int(issue.get("number") or 0)
    state = str(issue.get("state") or "").upper()
    base: dict[str, Any] = {
        "number": number,
        "should_close": False,
        "reason": None,
        "evidence": [],
        "maintainer": None,
        "assoc": None,
        "close_reason": "completed",
    }
    if state in {"CLOSED", "CLOSE"}:
        return base

    # 1) Merged PRs with closing keywords referencing this issue.
    for pr in prs or []:
        if not isinstance(pr, dict):
            continue
        merged = pr.get("merged") or pr.get("mergedAt") or pr.get("merged_at")
        if not merged:
            continue
        pr_num = pr.get("number")
        body = " ".join(str(x) for x in (pr.get("title") or "", pr.get("body") or "") if x)
        refs = {int(m) for m in _CLOSING_KW.findall(body)}
        if number not in refs and number not in {
            int(x)
            for x in (pr.get("closingIssues") or pr.get("closing_issues") or [])
            if str(x).isdigit()
        }:
            # Also accept explicit closingIssuesNumbers list
            closing = pr.get("closingIssuesReferences") or []
            if isinstance(closing, list):
                refs |= {
                    int(c["number"])
                    for c in closing
                    if isinstance(c, dict) and isinstance(c.get("number"), int)
                }
        if number not in refs:
            continue
        assoc = _extract_assoc(pr)
        # Prefer merger association if present
        merger = pr.get("mergedBy") or pr.get("merged_by") or {}
        if isinstance(merger, dict) and merger.get("author_association"):
            assoc = str(merger["author_association"]).upper()
        login = _extract_login(merger) if merger else _extract_login(pr)
        if not _is_maintainer(assoc):
            # Non-maintainer merged PR: do not auto-close (require maintainer signal)
            continue
        base.update(
            {
                "should_close": True,
                "reason": "merged_pr",
                "evidence": [f"PR #{pr_num} merged by {login} ({assoc})"],
                "maintainer": login or None,
                "assoc": assoc,
            }
        )
        return base

    # 2) Timeline: referenced/closed events from maintainers with closing keywords.
    for ev in timeline or []:
        if not isinstance(ev, dict):
            continue
        event = str(ev.get("event") or "").lower()
        if event not in {"referenced", "closed", "cross-referenced", "connected"}:
            continue
        commit = ev.get("commit_id") or ev.get("sha") or ""
        source = ev.get("source") or {}
        body = str(ev.get("body") or "")
        if isinstance(source, dict):
            issue_src = source.get("issue") or {}
            if isinstance(issue_src, dict) and issue_src.get("pull_request"):
                # Cross-ref from a PR — handled via prs list preferably
                pass
            body = body or str(issue_src.get("body") or "")
        msg = body or str(
            ev.get("commit", {}).get("message", "") if isinstance(ev.get("commit"), dict) else ""
        )
        refs = {int(m) for m in _CLOSING_KW.findall(msg)}
        if number not in refs and event != "closed":
            continue
        assoc = _extract_assoc(ev)
        login = _extract_login(ev)
        if event == "closed" and _is_maintainer(assoc):
            base.update(
                {
                    "should_close": True,
                    "reason": "closing_commit" if commit else "maintainer_comment",
                    "evidence": [
                        f"timeline {event} by {login} ({assoc})"
                        + (f" commit {commit[:7]}" if commit else "")
                    ],
                    "maintainer": login or None,
                    "assoc": assoc,
                }
            )
            return base
        if number in refs and _is_maintainer(assoc):
            base.update(
                {
                    "should_close": True,
                    "reason": "closing_commit",
                    "evidence": [
                        f"closing keyword in timeline by {login} ({assoc})"
                        + (f" commit {commit[:7]}" if commit else "")
                    ],
                    "maintainer": login or None,
                    "assoc": assoc,
                }
            )
            return base

    # 3) Maintainer comments stating resolution.
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        assoc = _extract_assoc(c)
        if not _is_maintainer(assoc):
            continue
        body = str(c.get("body") or "")
        if not _RESOLVED_COMMENT.search(body):
            continue
        # Prefer explicit close intent over casual "fixed a typo" — require #N or "this issue"
        if not (
            re.search(rf"#\s*{number}\b", body)
            or re.search(r"\bthis issue\b", body, re.IGNORECASE)
            or re.search(r"\b(closing|closed)\b", body, re.IGNORECASE)
        ):
            continue
        login = _extract_login(c)
        cid = c.get("id") or c.get("url") or ""
        base.update(
            {
                "should_close": True,
                "reason": "maintainer_comment",
                "evidence": [f"comment by {login} ({assoc})" + (f" id={cid}" if cid else "")],
                "maintainer": login or None,
                "assoc": assoc,
            }
        )
        return base

    return base


def main(argv: list[str] | None = None) -> int:
    """CLI: load JSON inputs and print closure decision."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue-json", required=True, help="path to issue JSON object")
    ap.add_argument("--timeline-json", default=None)
    ap.add_argument("--comments-json", default=None)
    ap.add_argument("--prs-json", default=None)
    args = ap.parse_args(argv)

    def _load(path: str | None) -> Any:
        if not path:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    issue = _load(args.issue_json)
    if not isinstance(issue, dict):
        sys.exit("issue JSON must be an object")
    timeline = _load(args.timeline_json)
    comments = _load(args.comments_json)
    prs = _load(args.prs_json)
    decision = decide_closure(
        issue,
        timeline=timeline if isinstance(timeline, list) else None,
        comments=comments if isinstance(comments, list) else None,
        prs=prs if isinstance(prs, list) else None,
    )
    json.dump(decision, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
