"""tripll.workspace — narrow workspace scope helpers for dispatch briefs.

Exports:
    TOOLCHAIN_PATHS — repo paths agents may read for verify/tooling.
    compute_workspace_scope — owned paths + plan slice + toolchain files.
"""

from __future__ import annotations

TOOLCHAIN_PATHS: tuple[str, ...] = (
    "Makefile",
    "pyproject.toml",
    "infra/sevn.schema.json",
    "plan/tripll",
)


def compute_workspace_scope(owned_paths: list[str]) -> list[str]:
    """Build the narrow filesystem scope list for one wave dispatch.

    Args:
        owned_paths (list[str]): Lane owned paths from the wave plan.

    Returns:
        list[str]: Relative paths under the worktree root (deduped, stable order).

    Examples:
        >>> "src/sevn/foo/" in compute_workspace_scope(["src/sevn/foo/"])
        True
        >>> "plan/tripll" in compute_workspace_scope([])
        True
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in [*owned_paths, *TOOLCHAIN_PATHS]:
        rel = raw.strip().rstrip("/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out
