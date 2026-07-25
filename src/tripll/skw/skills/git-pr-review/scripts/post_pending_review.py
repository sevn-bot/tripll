#!/usr/bin/env python3
"""Create a PENDING (draft) PR review with inline comments. Never submits.

Usage:
  post_pending_review.py <owner/repo> <pr_number> <comments.json> [--body "summary"]

comments.json is a JSON array of objects:
  {"path": "dir/file.go", "line": 42, "body": "...", "side": "RIGHT", "start_line": 40}
  - side defaults to "RIGHT" (use "LEFT" for removed lines).
  - line must fall inside the PR diff or GitHub rejects the whole call (422).

Resolves the PR head SHA, posts one pending review, prints id/state/url, and
verifies the drafts are not publicly visible. Exits non-zero if not PENDING.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def gh(args: list[str], stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.decode()
        sys.exit(f"gh {' '.join(args)} failed:\n{stderr}")
    return proc.stdout


def published_count(repo: str, pr: int) -> int:
    data = json.loads(gh(["api", f"repos/{repo}/pulls/{pr}/comments", "--paginate"]))
    return len(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="owner/repo")
    ap.add_argument("pr", type=int)
    ap.add_argument("comments", help="path to comments JSON array")
    ap.add_argument("--body", default="", help="review summary (only shown if submitted)")
    args = ap.parse_args()

    with open(args.comments, encoding="utf-8") as fh:
        comments = json.load(fh)
    for comment in comments:
        comment.setdefault("side", "RIGHT")

    head = gh(["api", f"repos/{args.repo}/pulls/{args.pr}", "--jq", ".head.sha"]).decode().strip()
    payload = {"commit_id": head, "body": args.body, "comments": comments}

    before = published_count(args.repo, args.pr)
    review = json.loads(
        gh(
            ["api", f"repos/{args.repo}/pulls/{args.pr}/reviews", "--input", "-"],
            stdin=json.dumps(payload).encode(),
        )
    )
    after = published_count(args.repo, args.pr)

    review_id = review.get("id")
    state = review.get("state")
    login = review.get("user", {}).get("login")
    print(f"review {review_id} state={state} ({login})")
    print(review.get("html_url", ""))
    print(f"comments posted: {len(comments)} | published delta: {after - before} (must be 0)")

    if state != "PENDING" or after != before:
        sys.exit("ERROR: review is not a private draft, check it on GitHub")


if __name__ == "__main__":
    main()
