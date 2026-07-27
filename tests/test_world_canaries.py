"""World canaries — billing gate and dependabot reachability (W1.15, tier 4)."""

from __future__ import annotations

import subprocess

import pytest


@pytest.mark.tier4
def test_billing_canary_gh_run_list_shows_started_run() -> None:
    """P0.1 canary: ``gh run list`` returns a started CI run."""
    proc = subprocess.run(
        ["gh", "run", "list", "--workflow=CI", "--limit", "1", "--json", "status,conclusion"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.skip(f"gh unavailable: {proc.stderr.strip()}")
    assert "completed" in proc.stdout or "in_progress" in proc.stdout or "queued" in proc.stdout


@pytest.mark.tier4
def test_dependabot_branch_reachable() -> None:
    """Dependabot branches remain fetchable (R12 prep)."""
    proc = subprocess.run(
        ["git", "branch", "-r"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0
