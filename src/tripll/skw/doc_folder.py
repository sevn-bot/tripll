"""Folder-level validate / score for specs and PRDs (D6, ONB-05).

Exports:
    FileResult — per-file validate/score outcome.
    FolderResult — folder command outcome with rollup.
    run_docs_command — dispatch ``validate`` or ``score``.
    main — CLI entry for ``skw docs``.

Examples:
    >>> from tripll.skw.doc_folder import run_docs_command
    >>> run_docs_command.__name__
    'run_docs_command'
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tripll.skw.doc_score import SCORE_THRESHOLD, ScoreResult, rollup_scores, score_doc
from tripll.skw.doc_validate import validate_doc_file
from tripll.skw.prd_validate import parse_frontmatter
from tripll.skw.spec_validate import parse_spec_frontmatter

_TERMINAL_STATUSES = frozenset({"done", "ready"})
_SUPPORTED_KINDS = frozenset({"spec", "prd"})


@dataclass
class FileResult:
    """Outcome for one markdown file in a folder command."""

    path: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: ScoreResult | None = None


@dataclass
class FolderResult:
    """Outcome for a folder-level docs command."""

    exit_code: int
    files: list[FileResult]
    rollup: dict[str, Any]


def _doc_status(path: Path, kind: str) -> str | None:
    """Read ``status`` from one doc file's frontmatter.

    Args:
        path (Path): Markdown file to inspect.
        kind (str): ``"spec"`` or ``"prd"``.

    Returns:
        str | None: Frontmatter ``status`` when present and a string.

    Examples:
        >>> _doc_status.__name__
        '_doc_status'
    """
    text = path.read_text(encoding="utf-8")
    if kind == "spec":
        meta, _, _ = parse_spec_frontmatter(text)
    else:
        meta, _, _ = parse_frontmatter(text)
    status = meta.get("status")
    return status if isinstance(status, str) else None


def _iter_doc_files(directory: Path) -> list[Path]:
    """List markdown docs in ``directory`` excluding ``README.md``.

    Args:
        directory (Path): Folder to scan.

    Returns:
        list[Path]: Sorted ``*.md`` paths (non-recursive).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     (root / "a.md").write_text("---\\nid: x\\n---\\n")
        ...     (root / "README.md").write_text("# index")
        ...     names = [p.name for p in _iter_doc_files(root)]
        ...     names
        ['a.md']
    """
    return sorted(
        path for path in directory.glob("*.md") if path.is_file() and path.name != "README.md"
    )


def _file_ok(
    *,
    kind: str,
    validation_ok: bool,
    score_total: int,
    status: str | None,
    command: str,
) -> bool:
    """Return whether one file passes the folder command gate.

    Args:
        kind (str): ``"spec"`` or ``"prd"``.
        validation_ok (bool): Structural validation outcome.
        score_total (int): Deterministic validity score.
        status (str | None): Frontmatter status value.
        command (str): ``validate``, ``score``, or ``sync``.

    Returns:
        bool: ``True`` when the file satisfies the command-specific policy.

    Examples:
        >>> _file_ok(kind="prd", validation_ok=True, score_total=90, status="done", command="validate")
        True
    """
    terminal = status in _TERMINAL_STATUSES
    score_ok = score_total >= SCORE_THRESHOLD
    if command == "validate":
        if kind == "spec":
            return validation_ok and (not terminal or score_ok)
        return not terminal or score_ok
    if kind == "prd":
        return validation_ok and (not terminal or score_ok)
    return not terminal or score_ok


def run_docs_command(
    command: str,
    *,
    kind: str,
    directory: Path,
    repo_root: Path,
    kit_root: Path | None = None,
) -> FolderResult:
    """Run ``validate`` or ``score`` over a docs folder.

    Args:
        command (str): ``validate`` or ``score``.
        kind (str): ``"spec"`` or ``"prd"``.
        directory (Path): Folder of markdown docs.
        repo_root (Path): Repository root for resolution.
        kit_root (Path | None, optional): spec-kit-wave root. Defaults to the
            bundled package parent.

    Returns:
        FolderResult: Per-file outcomes and folder rollup.

    Raises:
        ValueError: When ``kind`` or ``command`` is unsupported.

    Examples:
        >>> run_docs_command.__name__
        'run_docs_command'
    """
    if kind not in _SUPPORTED_KINDS:
        msg = f"unsupported kind: {kind!r} (expected 'spec' or 'prd')"
        raise ValueError(msg)
    if command == "sync":
        msg = (
            "sync was removed (ONB-05). Use `tripll init` for brownfield doc scaffolding "
            "or edit docs manually."
        )
        raise ValueError(msg)

    directory = directory.resolve()
    repo_root = repo_root.resolve()
    siblings = _iter_doc_files(directory)
    file_results: list[FileResult] = []
    scores: list[ScoreResult] = []

    for path in siblings:
        validation = validate_doc_file(
            path,
            kind,
            repo_root=repo_root,
            siblings=siblings,
            kit_root=kit_root,
        )
        scored = score_doc(
            path,
            kind,
            repo_root=repo_root,
            siblings=siblings,
            kit_root=kit_root,
        )
        scores.append(scored)
        status = _doc_status(path, kind)
        ok = _file_ok(
            kind=kind,
            validation_ok=validation["ok"],
            score_total=scored.total,
            status=status,
            command=command,
        )
        errors = list(validation["errors"]) if kind == "spec" or command == "score" else []
        if status in _TERMINAL_STATUSES and scored.total < SCORE_THRESHOLD:
            errors.append(f"score {scored.total} below threshold {SCORE_THRESHOLD}")
        file_results.append(
            FileResult(
                path=str(path),
                ok=ok,
                errors=errors,
                warnings=list(validation.get("warnings", [])),
                score=scored,
            )
        )

    rollup = rollup_scores(scores)
    below = set(rollup["below_threshold"])
    for item, _scored in zip(file_results, scores, strict=True):
        status = _doc_status(Path(item.path), kind)
        if status in _TERMINAL_STATUSES and not item.ok:
            below.add(item.path)
    rollup["below_threshold"] = sorted(below)
    rollup["error_count"] = sum(1 for item in file_results if not item.ok)
    exit_code = 1 if rollup["error_count"] else 0
    return FolderResult(exit_code=exit_code, files=file_results, rollup=rollup)


def _print_human(result: FolderResult, *, command: str) -> None:
    """Print a human-readable folder command report to stdout.

    Args:
        result (FolderResult): Command outcome to render.
        command (str): Command name for context (unused in output today).

    Examples:
        >>> _print_human.__name__
        '_print_human'
    """
    _ = command
    for item in result.files:
        score_text = item.score.total if item.score else "n/a"
        state = "OK" if item.ok else "FAIL"
        print(f"{item.path}  score={score_text}  {state}")
        for err in item.errors:
            print(f"  ERROR: {err}")
        for warn in item.warnings:
            print(f"  WARN: {warn}")
    print(
        f"rollup: files={result.rollup['file_count']} "
        f"avg={result.rollup['average_total']} "
        f"errors={result.rollup['error_count']} "
        f"below_threshold={len(result.rollup['below_threshold'])}"
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``skw docs`` argparse parser.

    Returns:
        argparse.ArgumentParser: Parser with ``validate``, ``score``, and ``sync`` subcommands.

    Examples:
        >>> parser = _build_parser()
        >>> parser.prog
        'doc_folder.py'
    """
    parser = argparse.ArgumentParser(description="spec-kit-wave docs folder tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("validate", "score"):
        cmd = subparsers.add_parser(name, help=f"{name} every doc in a folder")
        cmd.add_argument("--kind", required=True, choices=sorted(_SUPPORTED_KINDS))
        cmd.add_argument("--dir", type=Path, required=True, help="Folder of *.md docs")
        cmd.add_argument(
            "--repo-root",
            type=Path,
            default=Path.cwd(),
            help="Repository root for interface/source resolution",
        )
        cmd.add_argument(
            "--kit-root",
            type=Path,
            default=Path(__file__).resolve().parent,
            help="spec-kit-wave root",
        )
        cmd.add_argument("--json", action="store_true", help="Emit JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``skw docs validate|score|sync``.

    Args:
        argv (list[str] | None, optional): Arguments after ``docs``. Defaults to
            ``sys.argv`` tail when invoked as ``__main__``.

    Returns:
        int: Process exit code from :func:`run_docs_command`.

    Examples:
        >>> main.__name__
        'main'
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    result = run_docs_command(
        args.command,
        kind=args.kind,
        directory=args.dir,
        repo_root=args.repo_root,
        kit_root=args.kit_root.resolve(),
    )
    if args.json:
        payload = {
            "command": args.command,
            "exit_code": result.exit_code,
            "files": [
                {
                    "path": item.path,
                    "ok": item.ok,
                    "errors": item.errors,
                    "warnings": item.warnings,
                    "score": {
                        "total": item.score.total,
                        "components": item.score.components,
                    }
                    if item.score
                    else None,
                }
                for item in result.files
            ],
            "rollup": result.rollup,
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_human(result, command=args.command)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
