"""tripll.repo_root — locate the target git checkout for worktrees.

Exports:
    resolve_repo_root — walk up from CWD or honor ``TRIPLL_REPO_ROOT``.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_repo_root(*, cwd: Path | None = None) -> Path:
    """Return the git repository root used for ``git worktree add``.

    Honors ``TRIPLL_REPO_ROOT`` when set. Otherwise walks up from *cwd* (or
    ``Path.cwd()``) looking for a ``.git`` directory.

    Args:
        cwd (Path | None): Starting directory; defaults to process CWD.

    Returns:
        Path: Resolved repository root (may equal *cwd* if no ``.git`` found).
    """
    env = os.environ.get("TRIPLL_REPO_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    start = (cwd or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start
