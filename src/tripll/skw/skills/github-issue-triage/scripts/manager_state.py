#!/usr/bin/env python3
"""Read/write github-issue-manager state.json with GitHub-sourced window anchors.

Usage:
  manager_state.py read --dir <path>
  manager_state.py write --dir <path> --repo owner/repo \\
    --anchor <ISO8601> [--nudge-issue N --nudge-at ISO] [--weekly-digest YYYY-MM-DD]
  manager_state.py compute-anchor --issues-json path/to/issues.json

State shape (state.json):
  {
    "repo": "owner/repo",
    "last_checked_at": "2026-07-19T09:00:00Z" | null,
    "last_weekly_digest": "2026-07-13" | null,
    "nudge_timestamps": {"21": "2026-07-10T12:00:00Z"}
  }

The window anchor is the max GitHub ``updatedAt``/``createdAt`` from the last
fetched page — never local wall clock. Anchor advances only via ``write`` after
a successful sweep.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
DEFAULT_WEEKLY_DIGEST_DAYS = 7


def default_state(repo: str = "") -> dict[str, Any]:
    """Return an empty state dict.

    Args:
        repo: Optional owner/repo slug.

    Returns:
        Fresh state with null anchors.
    """
    return {
        "repo": repo,
        "last_checked_at": None,
        "last_weekly_digest": None,
        "nudge_timestamps": {},
    }


def load_state(path: Path) -> dict[str, Any]:
    """Load state.json or return a default empty state.

    Args:
        path: Path to state.json.

    Returns:
        Parsed state dict.
    """
    if not path.is_file():
        return default_state()
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return default_state()
    out = default_state(str(data.get("repo") or ""))
    out["last_checked_at"] = data.get("last_checked_at")
    out["last_weekly_digest"] = data.get("last_weekly_digest")
    nudges = data.get("nudge_timestamps") or {}
    if isinstance(nudges, dict):
        out["nudge_timestamps"] = {str(k): str(v) for k, v in nudges.items()}
    return out


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON via temp file + os.replace.

    Args:
        path: Destination path.
        data: JSON-serializable dict.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist state atomically.

    Args:
        path: Path to state.json.
        state: State dict.
    """
    atomic_write_json(path, state)


def compute_anchor_from_issues(issues: list[dict[str, Any]]) -> str | None:
    """Return the max GitHub ``updatedAt``/``createdAt`` across issues.

    Args:
        issues: List of issue dicts with GitHub timestamps.

    Returns:
        ISO-8601 timestamp string, or None if empty.
    """
    stamps: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for key in ("updatedAt", "createdAt", "updated_at", "created_at"):
            val = issue.get(key)
            if isinstance(val, str) and val.strip():
                stamps.append(val.strip())
    if not stamps:
        return None
    # ISO-8601 Z timestamps sort lexicographically.
    return max(stamps)


def window_since(state: dict[str, Any]) -> str | None:
    """Return the search window start (``last_checked_at``), or None on first run.

    Args:
        state: Loaded state dict.

    Returns:
        ISO-8601 string or None.
    """
    val = state.get("last_checked_at")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def weekly_digest_due(
    state: dict[str, Any],
    *,
    today: str,
    cadence_days: int = DEFAULT_WEEKLY_DIGEST_DAYS,
) -> bool:
    """Return True when a weekly digest should be appended.

    Args:
        state: Loaded state.
        today: YYYY-MM-DD (UTC).
        cadence_days: Days between digests (default 7).

    Returns:
        True if digest is due.
    """
    last = state.get("last_weekly_digest")
    if not isinstance(last, str) or not last.strip():
        return True
    try:
        from datetime import date, timedelta

        last_d = date.fromisoformat(last.strip()[:10])
        today_d = date.fromisoformat(today[:10])
    except ValueError:
        return True
    return today_d >= last_d + timedelta(days=cadence_days)


def apply_nudge(state: dict[str, Any], issue_number: int, at: str) -> dict[str, Any]:
    """Record a nudge timestamp for an issue.

    Args:
        state: State dict (mutated copy returned).
        issue_number: Issue number.
        at: ISO-8601 timestamp.

    Returns:
        Updated state.
    """
    out = dict(state)
    nudges = dict(out.get("nudge_timestamps") or {})
    nudges[str(issue_number)] = at
    out["nudge_timestamps"] = nudges
    return out


def state_path(directory: Path) -> Path:
    """Return ``<directory>/state.json``."""
    return directory / "state.json"


def main(argv: list[str] | None = None) -> int:
    """CLI entry for manager state read/write/compute-anchor."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_read = sub.add_parser("read", help="print state.json")
    p_read.add_argument("--dir", required=True, help="manager directory")

    p_write = sub.add_parser("write", help="write/update state.json")
    p_write.add_argument("--dir", required=True)
    p_write.add_argument("--repo", default="")
    p_write.add_argument("--anchor", default=None, help="GitHub-sourced last_checked_at")
    p_write.add_argument("--weekly-digest", default=None, help="YYYY-MM-DD")
    p_write.add_argument("--nudge-issue", type=int, default=None)
    p_write.add_argument("--nudge-at", default=None)

    p_anchor = sub.add_parser("compute-anchor", help="max updatedAt/createdAt from issues JSON")
    p_anchor.add_argument("--issues-json", required=True)

    p_due = sub.add_parser("digest-due", help="exit 0 if weekly digest due")
    p_due.add_argument("--dir", required=True)
    p_due.add_argument("--today", required=True, help="YYYY-MM-DD")
    p_due.add_argument("--cadence-days", type=int, default=DEFAULT_WEEKLY_DIGEST_DAYS)

    args = ap.parse_args(argv)

    if args.cmd == "read":
        st = load_state(state_path(Path(args.dir)))
        json.dump(st, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.cmd == "write":
        path = state_path(Path(args.dir))
        st = load_state(path)
        if args.repo:
            st["repo"] = args.repo
        if args.anchor is not None:
            st["last_checked_at"] = args.anchor or None
        if args.weekly_digest is not None:
            st["last_weekly_digest"] = args.weekly_digest or None
        if args.nudge_issue is not None and args.nudge_at:
            st = apply_nudge(st, args.nudge_issue, args.nudge_at)
        save_state(path, st)
        json.dump(st, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.cmd == "compute-anchor":
        with open(args.issues_json, encoding="utf-8") as fh:
            issues = json.load(fh)
        if not isinstance(issues, list):
            sys.exit("issues JSON must be a list")
        anchor = compute_anchor_from_issues(issues)
        print(anchor or "")
        return 0

    if args.cmd == "digest-due":
        st = load_state(state_path(Path(args.dir)))
        due = weekly_digest_due(st, today=args.today, cadence_days=args.cadence_days)
        print("yes" if due else "no")
        return 0 if due else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
