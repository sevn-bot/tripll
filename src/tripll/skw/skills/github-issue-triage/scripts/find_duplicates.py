#!/usr/bin/env python3
"""Find duplicate candidates across a new-issue batch (+ optional corpus).

Usage:
  find_duplicates.py --new-json path.json [--corpus-json path.json] [--threshold 0.45]

Pure function: :func:`find_duplicate_candidates`. Uses simple token Jaccard
similarity on title (+ optional body prefix). Emits candidate canonical links
for maintainer-safe cross-linking (never auto-closes).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "is",
        "are",
        "with",
        "from",
        "this",
        "that",
        "it",
        "be",
        "as",
        "at",
        "by",
        "not",
        "no",
        "when",
        "how",
        "what",
        "why",
        "does",
        "do",
        "can",
        "sevn",
        "bot",
    }
)


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens minus stopwords."""
    return {t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in _STOP and len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def issue_text(issue: dict[str, Any], *, body_chars: int = 400) -> str:
    """Combine title + body prefix for similarity."""
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")[:body_chars]
    return f"{title}\n{body}"


def find_duplicate_candidates(
    new_issues: list[dict[str, Any]],
    corpus: list[dict[str, Any]] | None = None,
    *,
    threshold: float = 0.45,
) -> list[dict[str, Any]]:
    """Find likely duplicates within the new batch and against a corpus.

    Args:
        new_issues: Issues opened in this sweep.
        corpus: Open + recently closed issues for comparison (may include new).
        threshold: Minimum Jaccard score to report.

    Returns:
        List of ``{issue, candidate, score, same_batch, reason}`` sorted by score desc.
        Never suggests an issue as its own duplicate.
    """
    corpus = list(corpus or [])
    # Dedupe corpus by number; prefer keeping first occurrence
    seen_nums: set[int] = set()
    corpus_clean: list[dict[str, Any]] = []
    for c in corpus:
        if not isinstance(c, dict) or c.get("number") is None:
            continue
        n = int(c["number"])
        if n in seen_nums:
            continue
        seen_nums.add(n)
        corpus_clean.append(c)

    new_nums = {
        int(i["number"]) for i in new_issues if isinstance(i, dict) and i.get("number") is not None
    }

    # Also compare within the new batch
    for i in new_issues:
        if isinstance(i, dict) and i.get("number") is not None:
            n = int(i["number"])
            if n not in seen_nums:
                corpus_clean.append(i)
                seen_nums.add(n)

    tokens_by_num = {
        int(c["number"]): tokenize(issue_text(c))
        for c in corpus_clean
        if c.get("number") is not None
    }

    results: list[dict[str, Any]] = []
    reported: set[tuple[int, int]] = set()

    for issue in new_issues:
        if not isinstance(issue, dict) or issue.get("number") is None:
            continue
        num = int(issue["number"])
        toks = tokens_by_num.get(num) or tokenize(issue_text(issue))
        best: dict[str, Any] | None = None
        for other in corpus_clean:
            other_num = int(other["number"])
            if other_num == num:
                continue
            pair = (min(num, other_num), max(num, other_num))
            if pair in reported:
                continue
            score = jaccard(toks, tokens_by_num.get(other_num, set()))
            if score < threshold:
                continue
            # Prefer older / corpus issue as canonical when not same-batch pair
            same_batch = other_num in new_nums and num in new_nums
            candidate_num = other_num
            # If both new, pick lower number as canonical
            if same_batch and num < other_num:
                # report from higher → lower elsewhere; skip this orientation
                continue
            entry = {
                "issue": num,
                "candidate": candidate_num,
                "score": round(score, 4),
                "same_batch": same_batch,
                "reason": (f"title/body Jaccard {score:.2f} vs #{candidate_num}"),
                "issue_title": issue.get("title"),
                "candidate_title": other.get("title"),
                "issue_url": issue.get("url"),
                "candidate_url": other.get("url"),
            }
            if best is None or entry["score"] > best["score"]:
                best = entry
        if best is not None:
            pair = (min(best["issue"], best["candidate"]), max(best["issue"], best["candidate"]))
            reported.add(pair)
            results.append(best)

    results.sort(key=lambda r: (-float(r["score"]), int(r["issue"])))
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI: print duplicate candidates as JSON."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new-json", required=True, help="new issues this sweep")
    ap.add_argument("--corpus-json", default=None, help="open + 90-day closed corpus")
    ap.add_argument("--threshold", type=float, default=0.45)
    args = ap.parse_args(argv)

    with open(args.new_json, encoding="utf-8") as fh:
        new_issues = json.load(fh)
    if not isinstance(new_issues, list):
        sys.exit("new JSON must be a list")
    corpus = None
    if args.corpus_json:
        with open(args.corpus_json, encoding="utf-8") as fh:
            corpus = json.load(fh)
        if not isinstance(corpus, list):
            sys.exit("corpus JSON must be a list")
    out = find_duplicate_candidates(new_issues, corpus, threshold=args.threshold)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
