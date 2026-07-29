"""GitHub work-item helpers for the tracker layer (wraps ``gh``, no new HTTP client).

Exports:
    view_epic — fetch parent metadata.
    list_child_tickets — children linked via tripll parent labels.
    create_child_ticket — create a labelled child ticket.
    publish_breakdown_comment — post breakdown markdown on the parent.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from loguru import logger

__all__ = [
    "create_child_ticket",
    "list_child_tickets",
    "publish_breakdown_comment",
    "view_epic",
]

_PARENT_LABEL_PREFIX = "tripll-parent-"


def _dry_run() -> bool:
    return os.environ.get("TRIPLL_PR_DRY_RUN", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _gh_json(args: list[str], *, repo: str | None = None) -> Any:
    cmd = ["gh", *args]
    if repo:
        cmd.extend(["--repo", repo])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh failed")
    return json.loads(proc.stdout or "null")


def _repo_slug(repo: str | None) -> str:
    if repo:
        return repo
    data = _gh_json(["repo", "view", "--json", "nameWithOwner"])
    if isinstance(data, dict) and data.get("nameWithOwner"):
        return str(data["nameWithOwner"])
    raise RuntimeError("could not resolve GitHub repo")


def _parent_label(parent_ref: str) -> str:
    return f"{_PARENT_LABEL_PREFIX}{parent_ref.strip().lstrip('#')}"


def view_epic(ref: str, *, repo: str | None = None) -> dict[str, str]:
    """Return title and body for a parent work item.

    Args:
        ref (str): Numeric ref or ``owner/repo#number`` form.
        repo (str | None, optional): ``owner/repo`` override.

    Returns:
        dict[str, str]: ``ref``, ``title``, and ``body`` keys.

    Examples:
        >>> view_epic("1")  # doctest: +SKIP
        {'ref': '1', 'title': 'Epic', 'body': ''}
    """
    slug = _repo_slug(repo)
    number = ref.split("#")[-1].strip().lstrip("#")
    data = _gh_json(
        ["issue", "view", number, "--json", "number,title,body"],
        repo=slug,
    )
    if not isinstance(data, dict):
        raise RuntimeError(f"work item {ref!r} not found")
    return {
        "ref": str(data.get("number") or number),
        "title": str(data.get("title") or ""),
        "body": str(data.get("body") or ""),
    }


def list_child_tickets(parent_ref: str, *, repo: str | None = None) -> list[dict[str, str]]:
    """List child tickets labelled for *parent_ref*.

    Args:
        parent_ref (str): Parent numeric ref.
        repo (str | None, optional): ``owner/repo`` override.

    Returns:
        list[dict[str, str]]: Child rows with ``ref``, ``title``, and ``body``.
    """
    slug = _repo_slug(repo)
    label = _parent_label(parent_ref)
    data = _gh_json(
        [
            "issue",
            "list",
            "--label",
            label,
            "--state",
            "all",
            "--json",
            "number,title,body",
            "--limit",
            "200",
        ],
        repo=slug,
    )
    if not isinstance(data, list):
        return []
    rows: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "ref": str(item.get("number") or ""),
                "title": str(item.get("title") or ""),
                "body": str(item.get("body") or ""),
            }
        )
    return rows


def create_child_ticket(
    parent_ref: str,
    *,
    title: str,
    body: str = "",
    repo: str | None = None,
) -> str:
    """Create a labelled child ticket under *parent_ref*.

    Args:
        parent_ref (str): Parent numeric ref.
        title (str): Child title.
        body (str, optional): Child body markdown.
        repo (str | None, optional): ``owner/repo`` override.

    Returns:
        str: Created child ref (issue number).
    """
    if _dry_run():
        logger.warning(
            "TRIPLL_PR_DRY_RUN=1 — skipping child ticket creation for parent {}",
            parent_ref,
        )
        return "dry-run"
    slug = _repo_slug(repo)
    label = _parent_label(parent_ref)
    parent_num = parent_ref.strip().lstrip("#")
    full_body = body.strip()
    if full_body:
        full_body = f"{full_body}\n\n---\nParent: #{parent_num}\n"
    else:
        full_body = f"Parent: #{parent_num}\n"
    proc = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            slug,
            "--title",
            title,
            "--body",
            full_body,
            "--label",
            label,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh failed")
    url = (proc.stdout or "").strip()
    number = url.rstrip("/").split("/")[-1]
    return number


def publish_breakdown_comment(
    parent_ref: str,
    markdown: str,
    *,
    repo: str | None = None,
) -> str | None:
    """Post *markdown* as a comment on the parent work item.

    Args:
        parent_ref (str): Parent numeric ref.
        markdown (str): Breakdown summary markdown.
        repo (str | None, optional): ``owner/repo`` override.

    Returns:
        str | None: Comment URL when created; ``None`` in dry-run mode.
    """
    if _dry_run():
        logger.warning(
            "TRIPLL_PR_DRY_RUN=1 — skipping breakdown comment for parent {}",
            parent_ref,
        )
        return None
    slug = _repo_slug(repo)
    number = parent_ref.strip().lstrip("#")
    proc = subprocess.run(
        [
            "gh",
            "issue",
            "comment",
            number,
            "--repo",
            slug,
            "--body",
            markdown,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh failed")
    return (proc.stdout or "").strip() or None
