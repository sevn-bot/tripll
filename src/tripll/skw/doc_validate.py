"""Shared doc validation entry points for spec-kit-wave folder tooling.

Exports:
    validate_doc_file — dispatch validation to the per-kind validator.

Examples:
    >>> from tripll.skw.doc_validate import validate_doc_file
    >>> validate_doc_file.__name__
    'validate_doc_file'
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tripll.skw.prd_validate import load_prd_rules, validate_prd_file
from tripll.skw.spec_validate import validate_spec_file


def validate_doc_file(
    path: Path,
    kind: str,
    *,
    repo_root: Path,
    siblings: list[Path] | None = None,
    kit_root: Path | None = None,
) -> dict[str, Any]:
    """Validate one markdown doc file for ``kind`` (``spec`` or ``prd``).

    Args:
        path (Path): Markdown file to validate.
        kind (str): ``"spec"`` or ``"prd"``.
        repo_root (Path): Repository root for interface/source resolution.
        siblings (list[Path] | None, optional): Sibling docs for folder-scoped
            checks. Defaults to ``None``.
        kit_root (Path | None, optional): spec-kit-wave root. Defaults to the
            bundled package parent.

    Returns:
        dict[str, Any]: Report with ``path``, ``ok``, ``errors``, and ``warnings``.

    Raises:
        ValueError: When ``kind`` is not ``spec`` or ``prd``.

    Examples:
        >>> from pathlib import Path
        >>> validate_doc_file.__defaults__ is not None
        True
    """
    if kind == "spec":
        return validate_spec_file(
            path,
            repo_root=repo_root,
            siblings=siblings,
            kit_root=kit_root,
        )
    if kind == "prd":
        root = kit_root or Path(__file__).resolve().parent
        errors, warnings = validate_prd_file(path, root, rules=load_prd_rules(root))
        return {
            "path": str(path),
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
        }
    msg = f"unsupported kind: {kind!r} (expected 'spec' or 'prd')"
    raise ValueError(msg)
