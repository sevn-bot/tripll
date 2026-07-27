#!/usr/bin/env python3
"""Reconcile merged PRs that close issues — draft 'fixed by #PR' + close plan.

Usage:
  reconcile_prs.py --issues-json path.json --prs-json path.json

Pure function: :func:`reconcile_merged_prs`. Emits a list of staged plans
compatible with post_issue_update.py (comment + close), draft-only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

_CLOSING_KW = re.compile(
    r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s+#(\d+)\b",
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
    merger = obj.get("mergedBy") or obj.get("merged_by")
    if isinstance(merger, dict):
        for key in ("authorAssociation", "author_association"):
            val = merger.get(key)
            if isinstance(val, str):
                return val.upper()
    return ""


def _closing_issue_numbers(pr: dict[str, Any]) -> set[int]:
    refs: set[int] = set()
    body = " ".join(str(x) for x in (pr.get("title") or "", pr.get("body") or "") if x)
    refs |= {int(m) for m in _CLOSING_KW.findall(body)}
    for key in ("closingIssuesReferences", "closingIssues", "closing_issues"):
        raw = pr.get(key) or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("number") is not None:
                    refs.add(int(item["number"]))
                elif isinstance(item, int):
                    refs.add(item)
                elif isinstance(item, str) and item.isdigit():
                    refs.add(int(item))
    return refs


def reconcile_merged_prs(
    issues: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    *,
    require_maintainer: bool = True,
) -> list[dict[str, Any]]:
    """Match merged PRs to open issues and stage fixed-by comments + closes.

    Args:
        issues: Open (or recently updated) issues.
        prs: PR payloads including merged flag/body.
        require_maintainer: When True, only act on maintainer-associated merges.

    Returns:
        List of staged update plans:
        ``{issue, pr, comment, close, close_reason, plan}``.
    """
    open_by_num = {
        int(i["number"]): i
        for i in issues
        if isinstance(i, dict)
        and i.get("number") is not None
        and str(i.get("state") or "OPEN").upper() in {"OPEN", ""}
    }
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for pr in prs:
        if not isinstance(pr, dict):
            continue
        merged = pr.get("merged") or pr.get("mergedAt") or pr.get("merged_at")
        if not merged:
            continue
        pr_num = int(pr.get("number") or 0)
        if not pr_num:
            continue
        assoc = _extract_assoc(pr)
        if require_maintainer and not _is_maintainer(assoc):
            continue
        for issue_num in _closing_issue_numbers(pr):
            if issue_num not in open_by_num:
                continue
            key = (issue_num, pr_num)
            if key in seen:
                continue
            seen.add(key)
            comment = f"Fixed by #{pr_num}. Closing as completed (merged PR with closing keyword)."
            plan = {
                "comment": comment,
                "close": True,
                "close_reason": "completed",
            }
            results.append(
                {
                    "issue": issue_num,
                    "pr": pr_num,
                    "comment": comment,
                    "close": True,
                    "close_reason": "completed",
                    "assoc": assoc or None,
                    "plan": plan,
                }
            )
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI: print staged PR↔issue reconciliation plans as JSON."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issues-json", required=True)
    ap.add_argument("--prs-json", required=True)
    ap.add_argument(
        "--allow-non-maintainer",
        action="store_true",
        help="also stage closes for non-maintainer merges (default: maintainer only)",
    )
    args = ap.parse_args(argv)

    with open(args.issues_json, encoding="utf-8") as fh:
        issues = json.load(fh)
    with open(args.prs_json, encoding="utf-8") as fh:
        prs = json.load(fh)
    if not isinstance(issues, list) or not isinstance(prs, list):
        sys.exit("issues/prs JSON must be lists")
    out = reconcile_merged_prs(
        issues,
        prs,
        require_maintainer=not args.allow_non_maintainer,
    )
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
