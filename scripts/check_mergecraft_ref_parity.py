"""Fail when the mergeCraft pin drifts between the workflow and the Makefile.

The CI review action (``.github/workflows/mergecraft.yml``) pins
``alexhawat/mergeCraft@<sha>``; the ``Makefile``'s ``MERGECRAFT_REF`` default
must match it so local ``make review`` runs the same reviewed code as CI.

Module: scripts.check_mergecraft_ref_parity
Exports:
    main — CLI entry; compares the two pinned refs and reports drift.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "mergecraft.yml"
MAKEFILE = REPO_ROOT / "Makefile"

DEFAULT_PARITY_REF = "origin/main"
WORKFLOW_GIT_PATH = ".github/workflows/mergecraft.yml"

_WORKFLOW_RE = re.compile(r"uses:\s*alexhawat/mergeCraft@(?P<ref>[0-9a-fA-F]{7,40})\b")
_MAKEFILE_RE = re.compile(
    r"MERGECRAFT_REF\s*\?=\s*\$\(if\s*\$\(TRIPLL_MERGECRAFT_REF\)\s*,\s*"
    r"\$\(TRIPLL_MERGECRAFT_REF\)\s*,\s*(?P<ref>[^),\s]+)\s*\)"
)


def _parity_ref() -> str:
    return (
        os.environ.get("TRIPLL_MERGECRAFT_PARITY_REF", DEFAULT_PARITY_REF).strip()
        or DEFAULT_PARITY_REF
    )


def _parity_ref_explicit() -> bool:
    return bool(os.environ.get("TRIPLL_MERGECRAFT_PARITY_REF", "").strip())


def _ci_mode() -> bool:
    return bool(os.environ.get("CI"))


def _git_show(repo_root: Path, ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    return None


def _git_fetch_default_branch(repo_root: Path) -> None:
    subprocess.run(
        ["git", "fetch", "--depth=1", "origin", "main"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def _workflow_text_from_ref(repo_root: Path, ref: str) -> tuple[str | None, bool]:
    """Load workflow YAML from a git ref.

    Returns:
        tuple[str | None, bool]: ``(text, unreachable)`` where ``unreachable`` is
        ``True`` when the configured ref cannot be resolved even after one fetch.
    """
    text = _git_show(repo_root, ref, WORKFLOW_GIT_PATH)
    if text is not None:
        return text, False

    _git_fetch_default_branch(repo_root)
    text = _git_show(repo_root, ref, WORKFLOW_GIT_PATH)
    if text is not None:
        return text, False

    if not _parity_ref_explicit() and ref == DEFAULT_PARITY_REF:
        text = _git_show(repo_root, "HEAD", WORKFLOW_GIT_PATH)
        if text is not None:
            return text, False

    return None, True


def _extract(pattern: re.Pattern[str], text: str, source: str, what: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        print(f"mergecraft-ref-check: no {what} pin found in {source}", file=sys.stderr)
        return None
    return match.group("ref")


def _extract_makefile(path: Path, what: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"mergecraft-ref-check: cannot read {path}: {exc}", file=sys.stderr)
        return None
    return _extract(_MAKEFILE_RE, text, str(path), what)


def main() -> int:
    """Compare the workflow and Makefile mergeCraft pins.

    Returns:
        int: ``0`` when the two refs match, ``1`` on drift or a missing pin.
    """
    ref = _parity_ref()
    workflow_text, unreachable = _workflow_text_from_ref(REPO_ROOT, ref)
    if unreachable:
        message = (
            f"mergecraft-ref-check: warning — cannot read workflow pin from git ref {ref!r}; "
            "skipping parity check"
        )
        if _ci_mode():
            print(
                f"mergecraft-ref-check: cannot read workflow pin from git ref {ref!r} under CI",
                file=sys.stderr,
            )
            return 1
        print(message, file=sys.stderr)
        return 0

    workflow_ref = _extract(
        _WORKFLOW_RE, workflow_text, f"git show {ref}:{WORKFLOW_GIT_PATH}", "workflow action"
    )
    makefile_ref = _extract_makefile(MAKEFILE, "MERGECRAFT_REF default")
    if workflow_ref is None or makefile_ref is None:
        return 1
    if workflow_ref != makefile_ref:
        print(
            "mergecraft-ref-check: mergeCraft pin drift —\n"
            f"  workflow (.github/workflows/mergecraft.yml): {workflow_ref}\n"
            f"  Makefile (MERGECRAFT_REF default):           {makefile_ref}\n"
            "Bump both to the same SHA so local `make review` matches CI.",
            file=sys.stderr,
        )
        return 1
    print(f"mergecraft-ref-check: ok — both pinned to {workflow_ref}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
