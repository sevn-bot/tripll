"""Sync GitHub PR checks and review threads into the Finding graph."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tripll.github.checks import fetch_check_runs, normalize_check_runs
from tripll.github.findings import (
    list_findings_from_store,
    sync_findings_to_store,
    triage_finding,
)
from tripll.github.learnings import export_learnings
from tripll.github.reviews import fetch_review_comments, normalize_review_comments
from tripll.graphstore import GraphStore, SqliteGraphStore


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


def _repo_slug() -> tuple[str, str]:
    data = _gh_json(["repo", "view", "--json", "owner,name"])
    if not isinstance(data, dict):
        raise RuntimeError("could not resolve GitHub repo")
    owner = data.get("owner") or {}
    name = str(data.get("name") or "")
    login = owner.get("login") if isinstance(owner, dict) else str(owner)
    return str(login), name


def _pr_head_sha(owner: str, repo: str, pr_number: int) -> str:
    data = _gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "headRefOid",
        ]
    )
    if isinstance(data, dict) and data.get("headRefOid"):
        return str(data["headRefOid"])
    raise RuntimeError(f"PR #{pr_number} head sha not found")


def sync_pr_findings(
    pr_number: int,
    store: GraphStore,
    *,
    run_id: str = "local",
    repo_slug: str = "tripll",
) -> int:
    """Fetch checks + review comments for a PR and upsert Finding nodes."""
    owner, repo = _repo_slug()
    head_sha = _pr_head_sha(owner, repo, pr_number)
    check_runs = fetch_check_runs(owner, repo, head_sha)
    comments = fetch_review_comments(owner, repo, pr_number)
    findings: list[dict[str, Any]] = []
    findings.extend(normalize_check_runs(check_runs, run_id=run_id))
    findings.extend(normalize_review_comments(comments, run_id=run_id))
    for finding in findings:
        finding.setdefault("head_sha", head_sha)
        finding["pr_number"] = pr_number
    return sync_findings_to_store(findings, store, repo=repo_slug)


def default_graph_db() -> Path:
    return Path(".tripll/graph.db")


def open_store(db: Path | str | None = None) -> SqliteGraphStore:
    path = str(db or default_graph_db())
    return SqliteGraphStore(path)


def triage_and_export(
    finding: dict[str, Any],
    store: GraphStore,
    *,
    state: str,
    rationale: str | None = None,
    learnings_path: Path | None = None,
    repo: str = "tripll",
) -> dict[str, Any]:
    """Triage one finding, persist, and export learnings when rejected."""
    from tripll.github.findings import finding_to_graph_nodes

    updated = triage_finding(finding, state=state, rationale=rationale)
    node, edges = finding_to_graph_nodes(updated, repo=repo)
    store.upsert_nodes([node])
    if edges:
        store.upsert_edges(edges)
    if state == "rejected":
        path = learnings_path or Path(".mergecraft/learnings.md")
        all_findings = list_findings_from_store(store)
        from tripll.repo_root import resolve_repo_root
        from tripll.rules.store import RuleStore

        active_rules = RuleStore(resolve_repo_root()).list_active()
        export_learnings(all_findings, path=path, active_rules=active_rules)
    return updated
