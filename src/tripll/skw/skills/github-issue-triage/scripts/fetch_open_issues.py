#!/usr/bin/env python3
"""Fetch open GitHub issues as JSON for triage workflows.

Usage:
  fetch_open_issues.py [--repo owner/repo] [--limit N] [--label LABEL] [--search QUERY]

Defaults:
  --repo  from `gh repo view --json nameWithOwner` when omitted
  --limit 100
  --state open

Prints a JSON array to stdout. Requires `gh` authenticated for the target repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def gh_json(args: list[str]) -> object:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def detect_repo() -> str:
    data = gh_json(["repo", "view", "--json", "nameWithOwner"])
    if not isinstance(data, dict):
        sys.exit("unexpected gh repo view response")
    repo = data.get("nameWithOwner")
    if not isinstance(repo, str) or not repo:
        sys.exit("could not detect repo; pass --repo owner/repo")
    return repo


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch open GitHub issues as JSON")
    ap.add_argument("--repo", default=None, help="owner/repo (default: current repo)")
    ap.add_argument("--limit", type=int, default=100, help="max issues (default 100)")
    ap.add_argument("--label", action="append", default=[], help="filter by label (repeatable)")
    ap.add_argument("--search", default=None, help="extra gh issue list --search terms")
    ap.add_argument("--state", default="open", choices=("open", "closed", "all"))
    args = ap.parse_args()

    repo = args.repo or detect_repo()
    cmd = [
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        args.state,
        "--limit",
        str(args.limit),
        "--json",
        "number,title,body,labels,state,author,createdAt,updatedAt,comments,assignees,milestone",
    ]
    if args.label:
        cmd.extend(["--label", ",".join(args.label)])
    if args.search:
        cmd.extend(["--search", args.search])

    issues = gh_json(cmd)
    if not isinstance(issues, list):
        sys.exit("unexpected gh issue list response")
    json.dump(issues, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
