#!/usr/bin/env python3
"""Apply GitHub issue triage updates (labels, comment, close) with dry-run default.

Usage:
  post_issue_update.py <owner/repo> <issue_number> plan.json [--apply]

plan.json shape:
  {
    "comment": "optional public comment body",
    "labels": ["bug", "needs-info"],
    "add_labels": ["bug"],
    "remove_labels": ["question"],
    "close": false,
    "close_reason": "not planned",
    "assignees": ["login"]
  }

Without --apply, prints the planned gh commands only (maintainer-safe default).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def run(cmd: list[str], *, apply: bool) -> None:
    line = " ".join(cmd)
    if apply:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            sys.exit(f"failed: {line}\n{proc.stderr}")
        print(f"ok: {line}")
    else:
        print(f"dry-run: {line}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply issue triage plan via gh")
    ap.add_argument("repo", help="owner/repo")
    ap.add_argument("issue", type=int, help="issue number")
    ap.add_argument("plan", help="path to plan JSON")
    ap.add_argument("--apply", action="store_true", help="execute gh commands (default: dry-run)")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)

    repo = args.repo
    num = str(args.issue)
    apply = args.apply

    labels: list[str] = list(plan.get("labels") or [])
    add_labels: list[str] = list(plan.get("add_labels") or [])
    remove_labels: list[str] = list(plan.get("remove_labels") or [])

    if labels:
        run(
            ["gh", "issue", "edit", num, "--repo", repo, "--add-label", ",".join(labels)],
            apply=apply,
        )
    for label in add_labels:
        run(["gh", "issue", "edit", num, "--repo", repo, "--add-label", label], apply=apply)
    for label in remove_labels:
        run(["gh", "issue", "edit", num, "--repo", repo, "--remove-label", label], apply=apply)

    assignees: list[str] = list(plan.get("assignees") or [])
    if assignees:
        run(
            ["gh", "issue", "edit", num, "--repo", repo, "--add-assignee", ",".join(assignees)],
            apply=apply,
        )

    comment = plan.get("comment")
    if isinstance(comment, str) and comment.strip():
        proc_input = comment.encode()
        if apply:
            proc = subprocess.run(
                ["gh", "issue", "comment", num, "--repo", repo, "--body-file", "-"],
                input=proc_input,
                capture_output=True,
                check=False,
            )
            if proc.returncode != 0:
                sys.exit(f"comment failed:\n{proc.stderr.decode()}")
            print(f"ok: comment on #{num}")
        else:
            print(
                f"dry-run: gh issue comment {num} --repo {repo} --body-file -  # {len(comment)} chars"
            )

    if plan.get("close"):
        reason = plan.get("close_reason") or "completed"
        run(["gh", "issue", "close", num, "--repo", repo, "--reason", reason], apply=apply)

    if not apply:
        print("dry-run complete — re-run with --apply after maintainer approval")


if __name__ == "__main__":
    main()
