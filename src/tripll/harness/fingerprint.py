"""Environment fingerprint — 13-field versioned input per attempt (§7.9.2)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["EnvFingerprint", "capture_env_fingerprint", "fingerprint_hash"]


@dataclass(frozen=True, slots=True)
class EnvFingerprint:
    """Thirteen fields recorded per attempt as an ``EnvFingerprint`` node."""

    task_id: str
    model_id: str
    instruction_version: str
    repository_commit: str
    working_tree_status: str
    container_or_image_id: str
    dependency_lock_hash: str
    fixture_version: str
    available_tools: str
    permission_profile: str
    network_policy: str
    secret_scope: str
    started_at: str


def fingerprint_hash(fp: EnvFingerprint) -> str:
    """Return a stable hash for graph ``natural_key`` linkage."""
    payload = json.dumps(asdict(fp), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _git_output(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _lock_hash(repo_root: Path) -> str:
    for name in ("uv.lock", "poetry.lock", "Pipfile.lock"):
        path = repo_root / name
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return ""


def capture_env_fingerprint(
    *,
    task_id: str,
    model_id: str = "",
    instruction_version: str = "",
    repo_root: Path | str | None = None,
    attempt_id: str = "",
) -> EnvFingerprint:
    """Capture the 13-field environment fingerprint for one attempt.

    Args:
        task_id (str): Stable task identifier (``run_id:node_id``).
        model_id (str): Provider model id when known.
        instruction_version (str): Prompt or brief version hash.
        repo_root (Path | str | None): Git checkout root; cwd when omitted.
        attempt_id (str): Attempt uuid for fixture versioning.

    Returns:
        EnvFingerprint: Snapshot linked to the attempt via ``RAN_IN``.
    """
    root = Path(repo_root or os.getcwd())
    commit = _git_output(root, "rev-parse", "HEAD") or "unknown"
    status = _git_output(root, "status", "--porcelain") or "clean"
    tools = ",".join(
        name
        for name, path in (
            ("git", shutil_which("git")),
            ("make", shutil_which("make")),
            ("uv", shutil_which("uv")),
        )
        if path
    )
    return EnvFingerprint(
        task_id=task_id,
        model_id=model_id or "unknown",
        instruction_version=instruction_version or "brief.v1",
        repository_commit=commit,
        working_tree_status=status or "clean",
        container_or_image_id=os.environ.get("TRIPLL_CONTAINER_ID", "host"),
        dependency_lock_hash=_lock_hash(root),
        fixture_version=attempt_id[:8] if attempt_id else "none",
        available_tools=tools or "unknown",
        permission_profile=os.environ.get("TRIPLL_PERMISSION_PROFILE", "default"),
        network_policy=os.environ.get("TRIPLL_NETWORK_POLICY", "default"),
        secret_scope=os.environ.get("TRIPLL_SECRET_SCOPE", "run-local"),
        started_at=datetime.now(tz=UTC).isoformat(),
    )


def shutil_which(name: str) -> str | None:
    """Thin wrapper so fingerprint capture stays import-light in tests."""
    import shutil

    return shutil.which(name)


def fingerprint_to_json(fp: EnvFingerprint) -> str:
    """Serialise *fp* for ledger storage."""
    return json.dumps(asdict(fp), sort_keys=True)


def fingerprint_from_json(raw: str | None) -> EnvFingerprint | None:
    """Hydrate an ``EnvFingerprint`` from ledger JSON."""
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    return EnvFingerprint(**data)
