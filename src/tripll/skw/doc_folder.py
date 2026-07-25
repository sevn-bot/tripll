"""Folder-level validate / score / sync for specs and PRDs (D6).

Exports:
    FileResult — per-file validate/score outcome.
    FolderResult — folder command outcome with rollup.
    run_docs_command — dispatch ``validate`` / ``score`` / ``sync``.
    main — CLI entry for ``skw docs``.

Examples:
    >>> from tripll.skw.doc_folder import run_docs_command
    >>> run_docs_command.__name__
    'run_docs_command'
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
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


def _ensure_sevn_importable(repo_root: Path) -> None:
    """Add ``repo_root/src`` to ``sys.path`` so about-docs helpers import.

    Args:
        repo_root (Path): Repository root containing ``src/sevn``.

    Examples:
        >>> import sys
        >>> before = len(sys.path)
        >>> _ensure_sevn_importable(Path("."))
        >>> len(sys.path) >= before
        True
    """
    src = repo_root.resolve() / "src"
    if src.is_dir():
        src_str = str(src)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


def _load_about_docs_helpers(repo_root: Path) -> tuple[Any, ...]:
    """Import about-docs sync helpers from the sevn package.

    Args:
        repo_root (Path): Repository root containing ``src/sevn``.

    Returns:
        tuple[Any, ...]: ``AboutDoc``, provider, dump/load, extract, generate,
        and manifest helpers.

    Examples:
        >>> _load_about_docs_helpers.__name__
        '_load_about_docs_helpers'
    """
    _ensure_sevn_importable(repo_root)
    from sevn.docs.about.extract import extract_fields
    from sevn.docs.about.generate import generate_body
    from sevn.docs.about.loader import dump_doc, load_doc
    from sevn.docs.about.model import AboutDoc
    from sevn.docs.about.registry import load_manifest_entries
    from sevn.docs.readme.providers import OfflineProvider

    return (
        AboutDoc,
        OfflineProvider,
        dump_doc,
        extract_fields,
        generate_body,
        load_doc,
        load_manifest_entries,
    )


def _doc_from_manifest(row: dict[str, Any]) -> Any:
    """Build an :class:`AboutDoc` from a manifest row with ``status: scaffold``.

    Args:
        row (dict[str, Any]): Manifest entry for one about-doc.

    Returns:
        AboutDoc: Validated scaffold document model.

    Examples:
        >>> row = {"id": "spec-99-x", "kind": "spec", "title": "X"}
        >>> doc = _doc_from_manifest(row)
        >>> doc.status
        'scaffold'
    """
    from sevn.docs.about.model import AboutDoc

    kind = str(row.get("kind", "spec"))
    payload: dict[str, Any] = {
        "id": str(row["id"]),
        "kind": kind,
        "title": str(row.get("title", row["id"])),
        "status": "scaffold",
        "owner": str(row.get("owner", "Alex")),
        "summary": str(row.get("summary", f"Scaffold for {row.get('title', row['id'])}."))[:200],
        "last_updated": date.today(),
        "sources": list(row.get("sources") or []),
        "related": list(row.get("related") or []),
    }
    if kind == "spec":
        payload["parent_prd"] = row.get("parent_prd")
        payload["depends_on"] = list(row.get("depends_on") or [])
        payload["build_phase"] = row.get("build_phase")
    else:
        payload["parent_prd"] = row.get("parent_prd")
        payload["specs"] = list(row.get("specs") or [])
        payload["personas"] = list(row.get("personas") or [])
        profile = row.get("prd_profile")
        payload["prd_profile"] = profile if profile in {"standard", "ai-native"} else "standard"
    return AboutDoc.model_validate(payload)


def _manifest_missing_paths(
    repo_root: Path,
    *,
    kind: str,
    directory: Path,
    load_manifest_entries: Any,
) -> list[tuple[str, Path]]:
    """Return manifest entries for ``kind`` under ``directory`` that are absent.

    Args:
        repo_root (Path): Repository root for manifest lookup.
        kind (str): ``"spec"`` or ``"prd"``.
        directory (Path): Target docs folder.
        load_manifest_entries (Any): Callable returning manifest rows by id.

    Returns:
        list[tuple[str, Path]]: ``(doc_id, target_path)`` pairs to scaffold.

    Examples:
        >>> _manifest_missing_paths.__name__
        '_manifest_missing_paths'
    """
    directory = directory.resolve()
    missing: list[tuple[str, Path]] = []
    for doc_id, row in load_manifest_entries(repo_root).items():
        if str(row.get("kind", "")) != kind:
            continue
        new_path = str(row.get("new_path", "")).strip()
        if not new_path:
            continue
        path = (repo_root / new_path).resolve()
        if path.parent != directory or path.is_file():
            continue
        missing.append((doc_id, path))
    return sorted(missing, key=lambda item: item[1].name)


def _merge_extracted(doc: Any, extracted: dict[str, Any]) -> Any:
    """Merge code-owned extract fields onto an existing :class:`AboutDoc`.

    Args:
        doc (AboutDoc): Existing document model.
        extracted (dict[str, Any]): Fields from :func:`extract_fields`.

    Returns:
        AboutDoc: Re-validated model with extracted fields applied.

    Examples:
        >>> _merge_extracted.__name__
        '_merge_extracted'
    """
    from sevn.docs.about.model import AboutDoc

    payload = doc.model_dump(mode="json")
    payload.update(extracted)
    return AboutDoc.model_validate(payload)


def _sync_one_file(
    path: Path,
    *,
    repo_root: Path,
    helpers: tuple[Any, ...],
) -> None:
    """Refresh frontmatter for one existing about-doc file (D8 — body unchanged).

    Args:
        path (Path): Existing markdown file to update in place.
        repo_root (Path): Repository root for extraction.
        helpers (tuple[Any, ...]): Tuple from :func:`_load_about_docs_helpers`.

    Examples:
        >>> _sync_one_file.__name__
        '_sync_one_file'
    """
    _about_doc, _offline, dump_doc, extract_fields, _generate_body, load_doc, _manifest = helpers
    doc, body = load_doc(path)
    extracted = extract_fields(repo_root, doc.model_dump(mode="json"))
    updated = _merge_extracted(doc, extracted)
    path.write_text(dump_doc(updated, body), encoding="utf-8")


def _create_from_template(
    path: Path,
    row: dict[str, Any],
    *,
    repo_root: Path,
    helpers: tuple[Any, ...],
) -> None:
    """Scaffold a missing doc from manifest metadata without fabricating prose (D8).

    Args:
        path (Path): Target markdown path to create.
        row (dict[str, Any]): Manifest entry for the missing doc.
        repo_root (Path): Repository root for extraction.
        helpers (tuple[Any, ...]): Tuple from :func:`_load_about_docs_helpers`.

    Examples:
        >>> _create_from_template.__name__
        '_create_from_template'
    """
    _about_doc, offline_provider, dump_doc, extract_fields, generate_body, _load_doc, _manifest = (
        helpers
    )
    doc = _doc_from_manifest(row)
    body = generate_body(doc, offline_provider())
    merged = _merge_extracted(doc, extract_fields(repo_root, doc.model_dump(mode="json")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_doc(merged, body), encoding="utf-8")


def _run_sync(
    *,
    kind: str,
    directory: Path,
    repo_root: Path,
    kit_root: Path | None,
) -> FolderResult:
    """Sync every doc in ``directory``: refresh frontmatter and scaffold missing files.

    Args:
        kind (str): ``"spec"`` or ``"prd"``.
        directory (Path): Folder of markdown docs.
        repo_root (Path): Repository root for about-docs helpers.
        kit_root (Path | None): spec-kit-wave root for validation.

    Returns:
        FolderResult: Post-sync validation outcome.

    Examples:
        >>> _run_sync.__name__
        '_run_sync'
    """
    directory = directory.resolve()
    repo_root = repo_root.resolve()
    helpers = _load_about_docs_helpers(repo_root)
    _about_doc, _offline, _dump, _extract, _generate, _load, load_manifest_entries = helpers

    for path in _iter_doc_files(directory):
        _sync_one_file(path, repo_root=repo_root, helpers=helpers)

    for doc_id, path in _manifest_missing_paths(
        repo_root,
        kind=kind,
        directory=directory,
        load_manifest_entries=load_manifest_entries,
    ):
        row = load_manifest_entries(repo_root)[doc_id]
        _create_from_template(path, row, repo_root=repo_root, helpers=helpers)
        _ = doc_id

    return run_docs_command(
        "validate",
        kind=kind,
        directory=directory,
        repo_root=repo_root,
        kit_root=kit_root,
    )


def run_docs_command(
    command: str,
    *,
    kind: str,
    directory: Path,
    repo_root: Path,
    kit_root: Path | None = None,
) -> FolderResult:
    """Run ``validate``, ``score``, or ``sync`` over a docs folder.

    Args:
        command (str): ``validate``, ``score``, or ``sync``.
        kind (str): ``"spec"`` or ``"prd"``.
        directory (Path): Folder of markdown docs.
        repo_root (Path): Repository root for resolution.
        kit_root (Path | None, optional): spec-kit-wave root. Defaults to the
            bundled package parent.

    Returns:
        FolderResult: Per-file outcomes and folder rollup.

    Raises:
        ValueError: When ``kind`` is unsupported.

    Examples:
        >>> run_docs_command.__name__
        'run_docs_command'
    """
    if kind not in _SUPPORTED_KINDS:
        msg = f"unsupported kind: {kind!r} (expected 'spec' or 'prd')"
        raise ValueError(msg)
    if command == "sync":
        return _run_sync(
            kind=kind,
            directory=directory,
            repo_root=repo_root,
            kit_root=kit_root,
        )

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

    for name in ("validate", "score", "sync"):
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
