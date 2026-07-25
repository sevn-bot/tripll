#!/usr/bin/env python3
"""Find stale needs-info issues past the documented nudge window (never auto-close).

Usage:
  find_stale.py --issues-json path.json --now ISO8601
                [--window-days 14] [--state-json path/to/state.json]

Pure function: :func:`find_stale_needs_info`. Emits nudge drafts only —
maintainer-gated comment plans for post_issue_update.py. Never sets close=true.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_WINDOW_DAYS = 14


def _parse_iso(value: str) -> datetime:
    """Parse ISO-8601 (Z or offset) into aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _label_names(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for lab in issue.get("labels") or []:
        if isinstance(lab, str):
            names.add(lab.lower())
        elif isinstance(lab, dict) and lab.get("name"):
            names.add(str(lab["name"]).lower())
    return names


def _last_activity_at(issue: dict[str, Any]) -> datetime | None:
    """Prefer last comment timestamp, else updatedAt/createdAt."""
    comments = issue.get("comments")
    if isinstance(comments, list) and comments:
        stamps: list[datetime] = []
        for c in comments:
            if not isinstance(c, dict):
                continue
            for key in ("createdAt", "created_at", "updatedAt", "updated_at"):
                val = c.get(key)
                if isinstance(val, str) and val.strip():
                    try:
                        stamps.append(_parse_iso(val))
                    except ValueError:
                        pass
                    break
        if stamps:
            return max(stamps)
    for key in ("updatedAt", "updated_at", "createdAt", "created_at"):
        val = issue.get(key)
        if isinstance(val, str) and val.strip():
            try:
                return _parse_iso(val)
            except ValueError:
                continue
    return None


def _author_login(issue: dict[str, Any]) -> str:
    author = issue.get("author") or issue.get("user")
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        return str(author.get("login") or "")
    return ""


def find_stale_needs_info(
    issues: list[dict[str, Any]],
    *,
    now: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    nudge_timestamps: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Find needs-info issues past the wait window with no recent reporter activity.

    Args:
        issues: Open issues (should include labels + comments when available).
        now: Current UTC ISO-8601 (for age math only — not written as GitHub anchor).
        window_days: Days after last activity before a nudge is due.
        nudge_timestamps: Map of issue number → last nudge ISO (skip if still fresh).

    Returns:
        List of nudge drafts:
        ``{issue, days_stale, last_activity, comment, plan, close: false}``.
        Never includes close=true.
    """
    now_dt = _parse_iso(now)
    nudges = nudge_timestamps or {}
    results: list[dict[str, Any]] = []

    for issue in issues:
        if not isinstance(issue, dict) or issue.get("number") is None:
            continue
        if str(issue.get("state") or "OPEN").upper() not in {"OPEN", ""}:
            continue
        labels = _label_names(issue)
        if "needs-info" not in labels and "needs_info" not in labels:
            continue
        num = int(issue["number"])
        last = _last_activity_at(issue)
        if last is None:
            continue
        age = now_dt - last
        if age < timedelta(days=window_days):
            continue
        # Skip if we already nudged within the same window
        prev = nudges.get(str(num))
        if prev:
            try:
                if now_dt - _parse_iso(prev) < timedelta(days=window_days):
                    continue
            except ValueError:
                pass
        days = int(age.total_seconds() // 86400)
        reporter = _author_login(issue)
        mention = f"@{reporter} " if reporter else ""
        comment = (
            f"## Needs info — gentle nudge\n\n"
            f"{mention}This issue is labeled `needs-info` and has had no update "
            f"for about {days} days. Could you share the smallest missing detail "
            f"(version/commit, steps, expected vs actual)?\n\n"
            f"We will not close this automatically — reply when you can, or say "
            f"if this is no longer relevant."
        )
        plan = {
            "comment": comment,
            "close": False,
        }
        results.append(
            {
                "issue": num,
                "days_stale": days,
                "last_activity": last.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "comment": comment,
                "close": False,
                "plan": plan,
                "title": issue.get("title"),
                "url": issue.get("url"),
            }
        )
    results.sort(key=lambda r: (-int(r["days_stale"]), int(r["issue"])))
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI: print stale needs-info nudge drafts as JSON."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issues-json", required=True)
    ap.add_argument("--now", required=True, help="UTC ISO-8601 for age math")
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument("--state-json", default=None, help="optional state.json for nudge_timestamps")
    args = ap.parse_args(argv)

    with open(args.issues_json, encoding="utf-8") as fh:
        issues = json.load(fh)
    if not isinstance(issues, list):
        sys.exit("issues JSON must be a list")
    nudges: dict[str, str] = {}
    if args.state_json:
        with open(args.state_json, encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            raw = state.get("nudge_timestamps") or {}
            if isinstance(raw, dict):
                nudges = {str(k): str(v) for k, v in raw.items()}
    out = find_stale_needs_info(
        issues,
        now=args.now,
        window_days=args.window_days,
        nudge_timestamps=nudges,
    )
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
