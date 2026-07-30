"""Fixtures and sample data for rules / calibrate / tracker RED tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

SAMPLE_RULE_FRONTMATTER = """\
---
rule_id: no-stdlib-logging
state: active
origin: codebase://src/widget.py:1
scope: ["src/**"]
executable: ast-grep
severity: error
---

Use loguru; never stdlib `logging`.
"""

SAMPLE_RULE_BODY = (
    "Use loguru; never stdlib `logging`.\n\n"
    "**Why:** bypasses log redaction.\n"
    "**Evidence:** `src/widget.py:1`.\n"
)


def init_git_repo(root: Path, *, files: dict[str, str] | None = None) -> Path:
    """Create a minimal git repo under *root* with optional tracked files.

    Args:
        root (Path): Directory to initialize.
        files (dict[str, str] | None, optional): Relative path → file contents.

    Returns:
        Path: The initialized repository root.

    Examples:
        >>> p = init_git_repo(Path("/tmp/x"), files={"README": "hi"})
        >>> p.name
        'x'
    """
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "init",
        ],
        cwd=root,
        check=True,
    )
    return root


@pytest.fixture
def rules_foreign_repo(tmp_path: Path) -> Path:
    """Foreign fixture repo (neither tripll nor sevn) with stdlib logging."""
    return init_git_repo(
        tmp_path / "widget-co",
        files={
            "src/widget.py": "import logging\nlog = logging.getLogger(__name__)\n",
            "README.md": "# Widget Co\n",
        },
    )


@pytest.fixture
def rules_foreign_repo_no_tests(tmp_path: Path) -> Path:
    """Foreign repo with application code but no unit tests (R32 honesty)."""
    return init_git_repo(
        tmp_path / "acme-widgets",
        files={
            "src/app.py": "def run() -> None:\n    pass\n",
        },
    )


def require_attr(module_name: str, attr: str) -> Any:
    """Import *module_name* and return *attr*, failing the test if missing."""
    from tests.conftest import require_module

    mod = require_module(module_name)
    if not hasattr(mod, attr):
        pytest.fail(f"{module_name}.{attr} not implemented")
    return getattr(mod, attr)
