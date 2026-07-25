"""GitHub PR review ingestion — comments, threads, merge signals."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from tripll.github.findings import normalize_review_comment

_PULLFROG_APPROVAL = "pullfrog-approval"


def _gh_json(args: list[str]) -> Any:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh failed")
    return json.loads(proc.stdout or "null")


def fetch_review_comments(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch inline review comments for a pull request."""
    data = _gh_json(
        [
            "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
            "--paginate",
        ]
    )
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "id" in data[0]:
            return data
        merged: list[dict[str, Any]] = []
        for page in data:
            if isinstance(page, list):
                merged.extend(page)
        return merged
    return []


def fetch_reviews(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch PR reviews (pullfrog, human, Bugbot)."""
    data = _gh_json(
        [
            "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            "--paginate",
        ]
    )
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "id" in data[0]:
            return data
        merged: list[dict[str, Any]] = []
        for page in data:
            if isinstance(page, list):
                merged.extend(page)
        return merged
    return []


def fetch_review_decision(owner: str, repo: str, pr_number: int) -> str | None:
    """Return ``reviewDecision`` from ``gh pr view --json``."""
    data = _gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "reviewDecision,headRefOid",
        ]
    )
    if isinstance(data, dict):
        decision = data.get("reviewDecision")
        return str(decision) if decision else None
    return None


def pullfrog_merge_signal(check_runs: list[dict[str, Any]]) -> str | None:
    """Return conclusion of the ``pullfrog-approval`` check-run, if present."""
    for run in check_runs:
        if str(run.get("name") or "").lower() == _PULLFROG_APPROVAL:
            return str(run.get("conclusion") or run.get("status") or "")
    return None


def normalize_review_comments(
    comments: list[dict[str, Any]],
    *,
    run_id: str = "local",
) -> list[dict[str, Any]]:
    """Normalize review comment payloads into Finding dicts."""
    return [normalize_review_comment(c, run_id=run_id) for c in comments]
