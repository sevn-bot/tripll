"""Fail when the pullfrog-py pin drifts between the workflow and the Makefile.

The CI review action (``.github/workflows/pullfrog.yml``) pins
``alexhawat/pullfrog-py@<sha>``; the ``Makefile``'s ``PULLFROG_PY_REF`` default
must match it so local ``make review`` runs the same reviewed code as CI.

Module: scripts.check_pullfrog_ref_parity
Exports:
    main — CLI entry; compares the two pinned refs and reports drift.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pullfrog.yml"
MAKEFILE = REPO_ROOT / "Makefile"

_WORKFLOW_RE = re.compile(r"uses:\s*alexhawat/pullfrog-py@(?P<ref>[0-9a-fA-F]{7,40})\b")
_MAKEFILE_RE = re.compile(
    r"PULLFROG_PY_REF\s*\?=\s*\$\(if\s*\$\(TRIPLL_PULLFROG_PY_REF\)\s*,\s*"
    r"\$\(TRIPLL_PULLFROG_PY_REF\)\s*,\s*(?P<ref>[^),\s]+)\s*\)"
)


def main() -> int:
    """Compare the workflow and Makefile pullfrog-py pins.

    Returns:
        int: ``0`` when the two refs match, ``1`` on drift or a missing pin.
    """

    def extract(pattern: re.Pattern[str], path: Path, what: str) -> str | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"pullfrog-ref-check: cannot read {path}: {exc}", file=sys.stderr)
            return None
        match = pattern.search(text)
        if match is None:
            print(f"pullfrog-ref-check: no {what} pin found in {path}", file=sys.stderr)
            return None
        return match.group("ref")

    workflow_ref = extract(_WORKFLOW_RE, WORKFLOW, "workflow action")
    makefile_ref = extract(_MAKEFILE_RE, MAKEFILE, "PULLFROG_PY_REF default")
    if workflow_ref is None or makefile_ref is None:
        return 1
    if workflow_ref != makefile_ref:
        print(
            "pullfrog-ref-check: pullfrog-py pin drift —\n"
            f"  workflow (.github/workflows/pullfrog.yml): {workflow_ref}\n"
            f"  Makefile (PULLFROG_PY_REF default):        {makefile_ref}\n"
            "Bump both to the same SHA so local `make review` matches CI.",
            file=sys.stderr,
        )
        return 1
    print(f"pullfrog-ref-check: ok — both pinned to {workflow_ref}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
