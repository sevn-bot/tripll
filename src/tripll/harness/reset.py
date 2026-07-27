"""Reset receipts — capture contamination before cleaning (§7.9.2)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["ResetReceipt", "capture_reset_receipt"]


@dataclass(frozen=True, slots=True)
class ResetReceipt:
    """Evidence that the workspace was reset before an attempt."""

    workspace: str
    services: str
    fixtures: str
    cache: str
    credentials: str
    verify_git_clean_at: str
    expected_listeners: str
    contaminated_state: dict[str, Any]
    captured_at: str


def _git_status(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_head(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def capture_reset_receipt(
    *,
    repo_root: Path | str,
    expected_sha: str | None = None,
    services: str = "none",
    fixtures: str = "default",
    cache: str = "cleared",
    credentials: str = "scoped",
    expected_listeners: str = "none",
) -> ResetReceipt:
    """Capture contaminated state, then record a reset receipt.

    Contaminated state (working tree dirt, untracked files) is captured **before**
    any cleaning so recurrence can be diagnosed.

    Args:
        repo_root (Path | str): Git checkout to inspect.
        expected_sha (str | None): Commit sha for ``VERIFY git clean at <sha>``.
        services (str): Running services snapshot label.
        fixtures (str): Fixture set version label.
        cache (str): Cache state label.
        credentials (str): Credential scope label.
        expected_listeners (str): Expected background listeners.

    Returns:
        ResetReceipt: Receipt including pre-clean contamination evidence.
    """
    root = Path(repo_root)
    head = expected_sha or _git_head(root)
    dirty = _git_status(root)
    contaminated: dict[str, Any] = {
        "working_tree_dirty": bool(dirty),
        "status_porcelain": dirty,
        "head_sha": head,
    }
    return ResetReceipt(
        workspace=str(root),
        services=services,
        fixtures=fixtures,
        cache=cache,
        credentials=credentials,
        verify_git_clean_at=f"VERIFY git clean at {head}",
        expected_listeners=expected_listeners,
        contaminated_state=contaminated,
        captured_at=datetime.now(tz=UTC).isoformat(),
    )


def reset_receipt_to_json(receipt: ResetReceipt) -> str:
    """Serialise a reset receipt for ledger or run-dir storage."""
    return json.dumps(asdict(receipt), sort_keys=True)
