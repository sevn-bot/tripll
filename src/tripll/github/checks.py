"""GitHub check-run ingestion — fetch, log capture, flake classification."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from tripll.github.findings import normalize_check_run

_INFRA_FLAKES = (
    "timed out",
    "timeout",
    "cancelled",
    "runner",
    "connection reset",
    "503",
    "502",
    "rate limit",
    "billing",
    "no space left",
)


def _gh_json(args: list[str], *, cwd: str | None = None) -> Any:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh failed")
    return json.loads(proc.stdout or "null")


def fetch_check_runs(
    owner: str,
    repo: str,
    head_sha: str,
) -> list[dict[str, Any]]:
    """Return check-runs for *head_sha* via the GitHub REST API."""
    data = _gh_json(
        [
            "api",
            f"repos/{owner}/{repo}/commits/{head_sha}/check-runs",
            "--paginate",
        ]
    )
    if isinstance(data, list):
        merged: list[dict[str, Any]] = []
        for page in data:
            if isinstance(page, dict):
                merged.extend(page.get("check_runs") or [])
        return merged
    if isinstance(data, dict):
        return list(data.get("check_runs") or [])
    return []


def fetch_failed_run_log(run_id: int | str) -> str:
    """Capture ``gh run view --log-failed`` output for a workflow run."""
    proc = subprocess.run(
        ["gh", "run", "view", str(run_id), "--log-failed"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout or proc.stderr or ""


def classify_infrastructure_flake(check_run: dict[str, Any]) -> bool:
    """Heuristic: infrastructure flake vs real defect."""
    conclusion = str(check_run.get("conclusion") or "").lower()
    if conclusion not in ("failure", "timed_out", "cancelled", "action_required"):
        return False
    blob = " ".join(
        str(check_run.get(key) or "") for key in ("name", "status", "conclusion")
    ).lower()
    output = check_run.get("output") or {}
    blob += " " + str(output.get("title") or "").lower()
    blob += " " + str(output.get("summary") or "").lower()
    blob += " " + str(output.get("text") or "").lower()
    return any(marker in blob for marker in _INFRA_FLAKES)


def normalize_check_runs(
    check_runs: list[dict[str, Any]],
    *,
    run_id: str = "local",
) -> list[dict[str, Any]]:
    """Normalize check-runs, attaching flake classification metadata."""
    findings: list[dict[str, Any]] = []
    for raw in check_runs:
        finding = normalize_check_run(raw, run_id=run_id)
        if classify_infrastructure_flake(raw):
            finding["severity"] = "info"
            finding["state"] = "deferred"
            finding["message_normalized"] = (
                finding.get("message_normalized", "") + " [infra-flake]"
            ).strip()
        findings.append(finding)
    return findings
