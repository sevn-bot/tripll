"""spec-kit-wave spec validator — about-sevn.bot committed spec format (stdlib only).

Exports:
    load_spec_rules — read ``spec-templates/spec-rules.toml`` merged with defaults.
    parse_spec_frontmatter — split YAML frontmatter (incl. nested ``interfaces``) and body.
    validate_spec_file — return ``ok``/``errors``/``warnings`` for one spec markdown file.
    validate_spec_file_json — JSON-serialisable report for one spec file.
    main — CLI entry (``--json`` mode for CI).

Examples:
    >>> from tripll.skw.spec_validate import load_spec_rules
    >>> "frontmatter" in load_spec_rules()
    True
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from tripll.skw.prd_validate import H2_HEADING_RE, _deep_merge, parse_frontmatter

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SCALAR_LINE_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

_DEFAULT_RULES: dict[str, Any] = {
    "frontmatter": {
        "required": [
            "id",
            "kind",
            "title",
            "status",
            "owner",
            "summary",
            "last_updated",
            "parent_prd",
            "sources",
            "fingerprint",
        ],
        "id_pattern": r"^spec-\d{2}-[a-z0-9-]+$",
        "kind": "spec",
        "status_enum": ["draft", "scaffold", "done", "rejected"],
        "summary_max_len": 200,
        "parent_prd_pattern": r"^prd-\d{2}-[a-z0-9-]+$",
        "forbidden_whole_repo_sources": ["src/sevn/**"],
    },
    "sections": {
        "required": [
            "Purpose",
            "Public Interface",
            "Data Model",
            "Internal Architecture",
            "Behavior",
            "Failure Modes",
            "Test Strategy",
        ],
    },
    "scaffold": {
        "forbidden_when_ready": [
            "Offline scaffold for",
            "[NEEDS CLARIFICATION:",
            "TBD",
            "Initial draft for",
        ],
    },
    "score": {
        "frontmatter_completeness": 20,
        "required_sections": 15,
        "no_scaffold_phrase": 25,
        "status_honesty": 15,
        "interfaces_sources_resolve": 15,
        "link_id_hygiene": 10,
    },
}


def _default_kit_root() -> Path:
    """Return the bundled spec-kit-wave root directory.

    Returns:
        Path: Parent of ``src/`` inside the installed package tree.

    Examples:
        >>> _default_kit_root().name
        'skw'
    """
    return Path(__file__).resolve().parent


def load_spec_rules(kit_root: Path | None = None) -> dict[str, Any]:
    """Load ``spec-templates/spec-rules.toml`` merged with built-in defaults.

    Args:
        kit_root (Path | None, optional): spec-kit-wave root. Defaults to the
            bundled package parent.

    Returns:
        dict[str, Any]: Merged rules mapping.

    Examples:
        >>> rules = load_spec_rules()
        >>> "sections" in rules
        True
    """
    root = kit_root or _default_kit_root()
    path = root / "spec-templates" / "spec-rules.toml"
    if not path.is_file():
        return _DEFAULT_RULES
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return _deep_merge(_DEFAULT_RULES, loaded)


def _parse_nested_list_of_dicts(raw_yaml: str, key: str) -> list[dict[str, str]]:
    """Parse a YAML list-of-mappings block for ``key`` without a full YAML loader.

    Args:
        raw_yaml (str): Frontmatter YAML text.
        key (str): Top-level key (for example ``interfaces``).

    Returns:
        list[dict[str, str]]: Parsed mapping rows.

    Examples:
        >>> raw = "interfaces:\\n  - name: run_turn\\n    file: a.py\\n    symbol: run_turn"
        >>> rows = _parse_nested_list_of_dicts(raw, "interfaces")
        >>> rows[0]["name"]
        'run_turn'
    """
    items: list[dict[str, str]] = []
    lines = raw_yaml.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != f"{key}:":
            index += 1
            continue
        index += 1
        current: dict[str, str] = {}
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if stripped and not line.startswith((" ", "\t")) and not stripped.startswith("- "):
                break
            if stripped.startswith("- "):
                if current:
                    items.append(current)
                current = {}
                rest = stripped[2:].strip()
                if ":" in rest:
                    field, value = rest.split(":", 1)
                    current[field.strip()] = value.strip()
                index += 1
                continue
            match = _SCALAR_LINE_RE.match(line)
            if match and match.group(1) and current is not None:
                field = match.group(2)
                value = match.group(3).strip()
                current[field] = value
            index += 1
        if current:
            items.append(current)
        break
    return items


def _strip_yaml_block(raw_yaml: str, key: str) -> str:
    """Replace a nested YAML block with an empty list placeholder for scalar parsing.

    Args:
        raw_yaml (str): Frontmatter YAML text.
        key (str): Top-level key to strip.

    Returns:
        str: YAML text safe for the lightweight scalar parser.

    Examples:
        >>> _strip_yaml_block("interfaces:\\n  - name: x\\nid: spec-01-x", "interfaces")
        'interfaces: []\\nid: spec-01-x'
    """
    lines = raw_yaml.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == f"{key}:":
            index += 1
            while index < len(lines):
                line = lines[index]
                stripped = line.strip()
                if stripped and not line.startswith((" ", "\t")) and not stripped.startswith("- "):
                    break
                index += 1
            kept.append(f"{key}: []")
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept)


def parse_spec_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """Parse YAML frontmatter including nested ``interfaces`` entries.

    Args:
        text (str): Full markdown file contents.

    Returns:
        tuple[dict[str, Any], str, str | None]: ``(meta, body, error)``.

    Examples:
        >>> text = "---\\nid: spec-01-x\\nkind: spec\\n---\\n\\n## Purpose\\n"
        >>> meta, body, err = parse_spec_frontmatter(text)
        >>> err is None and meta["id"] == "spec-01-x"
        True
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text, "missing YAML frontmatter (expected opening --- fence)"
    raw_yaml = match.group(1)
    interfaces = _parse_nested_list_of_dicts(raw_yaml, "interfaces")
    simplified = _strip_yaml_block(raw_yaml, "interfaces")
    simplified_text = f"---\n{simplified}\n---\n{text[match.end() :]}"
    meta, body, error = parse_frontmatter(simplified_text)
    if error:
        return meta, body, error
    meta["interfaces"] = interfaces
    sources = meta.get("sources")
    if isinstance(sources, str):
        meta["sources"] = [sources]
    elif isinstance(sources, list):
        meta["sources"] = [item for item in sources if isinstance(item, str)]
    return meta, body, None


def _h2_order(body: str) -> list[str]:
    """Extract level-2 heading titles in document order.

    Args:
        body (str): Markdown body after frontmatter.

    Returns:
        list[str]: Heading titles in appearance order.

    Examples:
        >>> _h2_order("## Purpose\\n\\n## Behavior\\n")
        ['Purpose', 'Behavior']
    """
    return [match.group(1).strip() for match in H2_HEADING_RE.finditer(body)]


def _numeric_spec_id(doc_id: str) -> str | None:
    """Return the two-digit numeric segment from a spec id.

    Args:
        doc_id (str): Frontmatter ``id`` value.

    Returns:
        str | None: Numeric segment (for example ``"17"``) or ``None``.

    Examples:
        >>> _numeric_spec_id("spec-17-gateway")
        '17'
    """
    match = re.fullmatch(r"spec-(\d{2})-[a-z0-9-]+", doc_id)
    return match.group(1) if match else None


def _validate_frontmatter(
    meta: dict[str, Any],
    rules: dict[str, Any],
    *,
    path: Path,
    siblings: list[Path] | None,
) -> tuple[list[str], list[str]]:
    """Validate spec frontmatter against kit rules.

    Args:
        meta (dict[str, Any]): Parsed frontmatter mapping.
        rules (dict[str, Any]): Merged kit rules.
        path (Path): File being validated.
        siblings (list[Path] | None): Other specs in the same folder.

    Returns:
        tuple[list[str], list[str]]: ``(errors, warnings)``.

    Examples:
        >>> _validate_frontmatter.__name__
        '_validate_frontmatter'
    """
    errors: list[str] = []
    warnings: list[str] = []
    fm = rules["frontmatter"]

    for key in fm["required"]:
        if key not in meta:
            errors.append(f"frontmatter missing required key: {key!r}")

    if meta.get("kind") != fm["kind"]:
        errors.append(f"frontmatter kind must be {fm['kind']!r}, got {meta.get('kind')!r}")

    doc_id = meta.get("id")
    if isinstance(doc_id, str) and not re.fullmatch(fm["id_pattern"], doc_id):
        errors.append(f"frontmatter id {doc_id!r} does not match pattern {fm['id_pattern']!r}")

    status = meta.get("status")
    if status not in fm["status_enum"]:
        errors.append(f"frontmatter status {status!r} not in {fm['status_enum']!r}")

    summary = meta.get("summary")
    if isinstance(summary, str) and len(summary) > fm["summary_max_len"]:
        errors.append(
            f"frontmatter summary length {len(summary)} exceeds max {fm['summary_max_len']}"
        )

    parent = meta.get("parent_prd")
    if parent is None:
        errors.append("parent_prd is required for kind: spec")
    elif isinstance(parent, str) and not re.fullmatch(fm["parent_prd_pattern"], parent):
        errors.append(f"parent_prd {parent!r} does not match pattern")

    sources = meta.get("sources")
    if sources in (None, []):
        errors.append("frontmatter sources must be a non-empty list")
    elif isinstance(sources, list):
        forbidden = set(fm.get("forbidden_whole_repo_sources", []))
        for item in sources:
            if not isinstance(item, str):
                errors.append("frontmatter sources entries must be strings")
                continue
            if item in forbidden:
                errors.append(
                    f"sources glob {item!r} is forbidden (whole-repo dump); "
                    "narrow to the packages this spec owns"
                )

    fingerprint = meta.get("fingerprint")
    if fingerprint in (None, ""):
        errors.append("frontmatter missing required key: 'fingerprint'")

    if isinstance(doc_id, str) and siblings:
        numeric = _numeric_spec_id(doc_id)
        if numeric:
            duplicates = [sibling for sibling in siblings if sibling != path and sibling.is_file()]
            for sibling in duplicates:
                sib_text = sibling.read_text(encoding="utf-8")
                sib_meta, _, sib_err = parse_spec_frontmatter(sib_text)
                if sib_err:
                    continue
                sib_id = sib_meta.get("id")
                if isinstance(sib_id, str) and _numeric_spec_id(sib_id) == numeric:
                    errors.append(
                        f"duplicate spec numeric id {numeric!r} — "
                        f"folder must have unique spec-NN-* ids "
                        f"(conflicts with {sibling.name})"
                    )
                    break

    last_updated = meta.get("last_updated")
    if isinstance(last_updated, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_updated):
        warnings.append(f"last_updated {last_updated!r} is not ISO date YYYY-MM-DD")

    return errors, warnings


def _validate_section_order(body: str, required: list[str]) -> list[str]:
    """Validate required H2 sections appear in order.

    Args:
        body (str): Markdown body after frontmatter.
        required (list[str]): Required section titles.

    Returns:
        list[str]: Validation errors (empty when OK).

    Examples:
        >>> _validate_section_order("## Purpose\\n\\n## Behavior\\n", ["Purpose", "Behavior"])
        []
    """
    errors: list[str] = []
    found = _h2_order(body)
    if not found:
        return ["body has no H2 sections"]
    req_index = 0
    for heading in found:
        if req_index >= len(required):
            break
        if heading.lower() == required[req_index].lower():
            req_index += 1
        elif heading in required:
            errors.append(
                f"missing required H2 section: {required[req_index]!r} "
                f"(found {heading!r} out of order)"
            )
    if req_index < len(required):
        missing = required[req_index:]
        errors.append(f"missing required H2 sections: {', '.join(missing)!r}")
    return errors


def _validate_scaffold(body: str, meta: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    """Reject scaffold phrases when ``status`` is ``done``.

    Args:
        body (str): Markdown body after frontmatter.
        meta (dict[str, Any]): Parsed frontmatter mapping.
        rules (dict[str, Any]): Merged kit rules.

    Returns:
        list[str]: Validation errors (empty when OK).

    Examples:
        >>> _validate_scaffold("real prose", {"status": "draft"}, {"scaffold": {"forbidden_when_ready": ["TBD"]}})
        []
    """
    errors: list[str] = []
    if meta.get("status") != "done":
        return errors
    for phrase in rules["scaffold"]["forbidden_when_ready"]:
        if phrase in body:
            errors.append(f"status=done but body contains scaffold phrase: {phrase!r}")
    return errors


def _symbol_exists(file_path: Path, symbol: str) -> bool:
    """Return whether ``symbol`` names a top-level class or function in ``file_path``.

    Args:
        file_path (Path): Python source file.
        symbol (str): Symbol name to locate.

    Returns:
        bool: ``True`` when the symbol exists at module scope.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        ...     _ = handle.write("def run_turn(): pass")
        ...     path = Path(handle.name)
        >>> _symbol_exists(path, "run_turn")
        True
    """
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol
        ):
            return True
    return False


def _validate_interfaces(
    meta: dict[str, Any],
    repo_root: Path,
) -> list[str]:
    """Validate ``interfaces`` rows resolve to real files and symbols.

    Args:
        meta (dict[str, Any]): Parsed frontmatter mapping.
        repo_root (Path): Repository root for path resolution.

    Returns:
        list[str]: Validation errors (empty when OK).

    Examples:
        >>> _validate_interfaces({"interfaces": []}, Path("."))
        []
    """
    errors: list[str] = []
    interfaces = meta.get("interfaces")
    if interfaces in (None, []):
        return errors
    if not isinstance(interfaces, list):
        errors.append("frontmatter interfaces must be a list")
        return errors
    for index, row in enumerate(interfaces):
        if not isinstance(row, dict):
            errors.append(f"interfaces[{index}] must be a mapping")
            continue
        file_ref = row.get("file")
        symbol = row.get("symbol") or row.get("name")
        if not isinstance(file_ref, str) or not file_ref:
            errors.append(f"interfaces[{index}] missing file")
            continue
        if not isinstance(symbol, str) or not symbol:
            errors.append(f"interfaces[{index}] missing symbol")
            continue
        resolved = repo_root / file_ref
        if not resolved.is_file():
            errors.append(f"interface {row.get('name', symbol)!r} file not found: {file_ref}")
            continue
        if not _symbol_exists(resolved, symbol):
            errors.append(
                f"interface {row.get('name', symbol)!r} symbol {symbol!r} not found in {file_ref}"
            )
    return errors


def _validate_spec_content(
    path: Path,
    *,
    repo_root: Path,
    siblings: list[Path] | None,
    rules: dict[str, Any] | None = None,
    kit_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Validate one spec file's frontmatter, sections, and interface references.

    Args:
        path (Path): Spec markdown file.
        repo_root (Path): Repository root for interface resolution.
        siblings (list[Path] | None): Other specs in the same folder.
        rules (dict[str, Any] | None): Pre-loaded rules or ``None`` to load defaults.
        kit_root (Path | None): spec-kit-wave root when loading rules.

    Returns:
        tuple[list[str], list[str]]: ``(errors, warnings)``.

    Examples:
        >>> _validate_spec_content.__name__
        '_validate_spec_content'
    """
    if rules is None:
        rules = load_spec_rules(kit_root)
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    meta, body, fm_err = parse_spec_frontmatter(text)
    if fm_err:
        errors.append(fm_err)
        return errors, warnings

    fm_errors, fm_warnings = _validate_frontmatter(meta, rules, path=path, siblings=siblings)
    errors.extend(fm_errors)
    warnings.extend(fm_warnings)
    if fm_errors:
        return errors, warnings

    errors.extend(_validate_section_order(body, rules["sections"]["required"]))
    errors.extend(_validate_scaffold(body, meta, rules))
    errors.extend(_validate_interfaces(meta, repo_root))

    return errors, warnings


def validate_spec_file(
    path: Path,
    *,
    repo_root: Path,
    siblings: list[Path] | None = None,
    kit_root: Path | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one spec markdown file against kit rules.

    Args:
        path (Path): Spec markdown file.
        repo_root (Path): Repository root for interface resolution.
        siblings (list[Path] | None, optional): Other specs in the same folder.
        kit_root (Path | None, optional): spec-kit-wave root.
        rules (dict[str, Any] | None, optional): Pre-loaded rules.

    Returns:
        dict[str, Any]: Report with ``ok``, ``errors``, ``warnings``, and ``score``.

    Examples:
        >>> validate_spec_file.__name__
        'validate_spec_file'
    """
    errors, warnings = _validate_spec_content(
        path,
        repo_root=repo_root,
        siblings=siblings,
        rules=rules,
        kit_root=kit_root,
    )
    from tripll.skw.doc_score import SCORE_THRESHOLD, score_doc

    scored = score_doc(
        path,
        "spec",
        repo_root=repo_root,
        siblings=siblings,
        kit_root=kit_root,
    )
    return {
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "score": {
            "total": scored.total,
            "components": scored.components,
            "threshold": scored.total >= SCORE_THRESHOLD,
        },
    }


def validate_spec_file_json(
    path: Path,
    *,
    repo_root: Path,
    siblings: list[Path] | None = None,
    kit_root: Path | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-serialisable validation report for one spec file.

    Args:
        path (Path): Spec markdown file.
        repo_root (Path): Repository root for interface resolution.
        siblings (list[Path] | None, optional): Other specs in the same folder.
        kit_root (Path | None, optional): spec-kit-wave root.
        rules (dict[str, Any] | None, optional): Pre-loaded rules.

    Returns:
        dict[str, Any]: Same shape as :func:`validate_spec_file`.

    Examples:
        >>> validate_spec_file_json.__name__
        'validate_spec_file_json'
    """
    return validate_spec_file(
        path,
        repo_root=repo_root,
        siblings=siblings,
        kit_root=kit_root,
        rules=rules,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry for spec validation.

    Args:
        argv (list[str] | None, optional): CLI arguments. Defaults to ``sys.argv``.

    Returns:
        int: Process exit code (``0`` when all files pass).

    Examples:
        >>> main.__name__
        'main'
    """
    parser = argparse.ArgumentParser(description="Validate sevn.bot spec markdown files")
    parser.add_argument("paths", nargs="+", help="One or more spec .md files")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root for interface resolution (default: cwd)",
    )
    parser.add_argument(
        "--spec-dir",
        type=Path,
        default=None,
        help="Sibling spec folder for folder-scoped id uniqueness",
    )
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=_default_kit_root(),
        help="spec-kit-wave root (default: parent of src/)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    kit_root = args.kit_root.resolve()
    rules = load_spec_rules(kit_root)
    spec_dir = args.spec_dir.resolve() if args.spec_dir else None
    siblings = list(spec_dir.glob("*.md")) if spec_dir and spec_dir.is_dir() else None

    reports: list[dict[str, Any]] = []
    exit_code = 0

    for raw in args.paths:
        path = Path(raw).resolve()
        if not path.is_file():
            report = {
                "path": str(path),
                "ok": False,
                "errors": [f"file not found: {path}"],
                "warnings": [],
            }
            reports.append(report)
            exit_code = 1
            continue
        report = validate_spec_file(
            path,
            repo_root=repo_root,
            siblings=siblings,
            kit_root=kit_root,
            rules=rules,
        )
        if not report["ok"]:
            exit_code = 1
        reports.append(report)

    if args.json:
        print(json.dumps({"reports": reports}, indent=2))
        return exit_code

    for report in reports:
        print(report["path"])
        score = report.get("score")
        if isinstance(score, dict):
            print(f"  SCORE: {score['total']}/100")
        errors_list = report.get("errors")
        warnings_list = report.get("warnings")
        if not isinstance(errors_list, list):
            errors_list = []
        if not isinstance(warnings_list, list):
            warnings_list = []
        for err in errors_list:
            print(f"  ERROR: {err}")
        for warn in warnings_list:
            print(f"  WARN: {warn}")
        if report["ok"] and not report["warnings"]:
            print("  OK")
        elif report["ok"]:
            print("  OK (with warnings)")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
