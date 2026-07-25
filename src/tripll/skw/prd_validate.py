"""spec-kit-wave PRD validator — about-sevn.bot PRD template (stdlib only).

Exports:
    H2_HEADING_RE — regex for level-2 markdown headings.
    H3_HEADING_RE — regex for level-3 markdown headings.
    load_prd_rules — read ``prd-rules.toml`` merged with defaults.
    parse_frontmatter — split YAML frontmatter and body.
    validate_prd_file — return errors and warnings for one PRD markdown file.
    main — CLI entry (``--json`` mode for CI).
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any

H2_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
H3_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_INLINE_LIST_RE = re.compile(r"^\s*-\s+(.+)$")
_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

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
        ],
        "id_pattern": r"^(prd|spec)-\d{2}-[a-z0-9-]+$",
        "kind": "prd",
        "status_enum": ["draft", "scaffold", "ready", "done", "rejected"],
        "summary_max_len": 200,
        "parent_prd_pattern": r"^prd-\d{2}-[a-z0-9-]+$",
        "spec_id_pattern": r"^spec-\d{2}-[a-z0-9-]+$",
        "doc_id_pattern": r"^(prd|spec)-\d{2}-[a-z0-9-]+$",
        "profile_enum": ["standard", "ai-native"],
        "forbidden_keys": ["depends_on", "build_phase", "interfaces"],
    },
    "sections": {
        "required": [
            "Problem & Motivation",
            "Users & Use Cases",
            "Goals",
            "Non-Goals",
            "Experience",
            "Success Metrics",
            "Traceability",
        ],
        "recommended_ready": ["Open Questions"],
        "ai_native": ["AI Behavior & Eval", "Failure & Degradation"],
        "traceability": {"required_h3": ["Implementing Specs", "Change Log"]},
    },
    "ids": {
        "uj": r"^UJ-\d{3,}$",
        "fr": r"^FR-\d{3,}$",
        "kpi": r"^KPI-\d{3,}$",
        "risk": r"^RISK-\d{3,}$",
        "oq": r"^OQ-\d{3,}$",
    },
    "change_log": {"delta_pattern": r"^(ADDED|MODIFIED|REMOVED|RENAMED)\s+"},
    "scaffold": {
        "forbidden_when_ready": [
            "Offline scaffold for",
            "[NEEDS CLARIFICATION:",
            "TBD",
            "{placeholder}",
        ],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_prd_rules(kit_root: Path) -> dict[str, Any]:
    """Load ``prd-templates/prd-rules.toml`` merged with built-in defaults."""
    path = kit_root / "prd-templates" / "prd-rules.toml"
    if not path.is_file():
        return _DEFAULT_RULES
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return _deep_merge(_DEFAULT_RULES, loaded)


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text in {"null", "~"}:
        return None
    if text == "[]":
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        parts = [part.strip().strip("'\"") for part in inner.split(",")]
        return [part for part in parts if part]
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    return text


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """Parse YAML frontmatter and return metadata, body, and optional error."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text, "missing YAML frontmatter (expected opening --- fence)"
    raw = match.group(1)
    body = text[match.end() :]
    meta: dict[str, Any] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if (line.startswith(" ") or line.startswith("\t")) and current_key is not None:
            list_match = _INLINE_LIST_RE.match(line)
            if list_match:
                bucket = meta.setdefault(current_key, [])
                if not isinstance(bucket, list):
                    return {}, body, f"frontmatter key {current_key!r}: mixed scalar and list"
                bucket.append(_parse_scalar(list_match.group(1)))
                continue
            prev = meta.get(current_key)
            if isinstance(prev, str):
                meta[current_key] = f"{prev}\n{stripped}" if "\n" in prev else f"{prev} {stripped}"
                continue
            return {}, body, f"invalid frontmatter continuation for key {current_key!r}: {line!r}"
        list_match = _INLINE_LIST_RE.match(line)
        if list_match and current_key is not None:
            bucket = meta.setdefault(current_key, [])
            if not isinstance(bucket, list):
                return {}, body, f"frontmatter key {current_key!r}: mixed scalar and list"
            bucket.append(_parse_scalar(list_match.group(1)))
            continue
        scalar_match = _SCALAR_RE.match(line)
        if not scalar_match:
            return {}, body, f"invalid frontmatter line: {line!r}"
        key, value = scalar_match.group(1), scalar_match.group(2)
        current_key = key
        if value == "":
            meta[key] = []
        else:
            meta[key] = _parse_scalar(value)
    for key, value in list(meta.items()):
        if isinstance(value, str) and len(value) >= 2:
            if (value.startswith("'") and value.endswith("'")) or (
                value.startswith('"') and value.endswith('"')
            ):
                meta[key] = value[1:-1]
    return meta, body, None


def _section_slice(body: str, heading: str, level: int = 2) -> str:
    pattern = re.compile(
        rf"^{'#' * level}\s+{re.escape(heading)}\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(rf"^{'#' * min(level, 2)}\s+", body[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(body)
    return body[start:end]


def _h2_order(body: str) -> list[str]:
    return [match.group(1).strip() for match in H2_HEADING_RE.finditer(body)]


def _h3_in_section(section_text: str) -> list[str]:
    return [match.group(1).strip() for match in H3_HEADING_RE.finditer(section_text)]


def _validate_frontmatter(
    meta: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[list[str], list[str]]:
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
    if isinstance(doc_id, str) and not doc_id.startswith("prd-"):
        errors.append(f"frontmatter id must start with prd-, got {doc_id!r}")

    status = meta.get("status")
    if status not in fm["status_enum"]:
        errors.append(f"frontmatter status {status!r} not in {fm['status_enum']!r}")

    summary = meta.get("summary")
    if isinstance(summary, str) and len(summary) > fm["summary_max_len"]:
        errors.append(
            f"frontmatter summary length {len(summary)} exceeds max {fm['summary_max_len']}"
        )

    parent = meta.get("parent_prd")
    if doc_id == "prd-00-main":
        if parent is not None:
            errors.append("prd-00-main must have parent_prd: null")
    elif parent is None:
        errors.append("parent_prd is required (use null only for prd-00-main)")
    elif isinstance(parent, str) and not re.fullmatch(fm["parent_prd_pattern"], parent):
        errors.append(f"parent_prd {parent!r} does not match pattern")

    profile = meta.get("prd_profile", "standard")
    if profile not in fm["profile_enum"]:
        errors.append(f"prd_profile {profile!r} not in {fm['profile_enum']!r}")

    for forbidden in fm["forbidden_keys"]:
        if forbidden not in meta:
            continue
        val = meta[forbidden]
        if val in (None, [], {}):
            warnings.append(
                f"legacy spec-only frontmatter key {forbidden!r} — remove on PRD rewrite"
            )
        else:
            errors.append(f"frontmatter forbids spec-only key with value: {forbidden!r}")

    for key in ("related", "specs"):
        values = meta.get(key, [])
        if values is None:
            continue
        if not isinstance(values, list):
            errors.append(f"frontmatter {key} must be a list")
            continue
        for item in values:
            if not isinstance(item, str) or not re.fullmatch(fm["doc_id_pattern"], item):
                errors.append(f"frontmatter {key} entry {item!r} invalid doc id")
            if key == "specs" and isinstance(item, str):
                if not re.fullmatch(fm["spec_id_pattern"], item):
                    errors.append(f"frontmatter specs entry must be spec-NN-slug, got {item!r}")

    last_updated = meta.get("last_updated")
    if isinstance(last_updated, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_updated):
        warnings.append(f"last_updated {last_updated!r} is not ISO date YYYY-MM-DD")

    return errors, warnings


def _validate_section_order(body: str, required: list[str]) -> list[str]:
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
                f"H2 section {heading!r} appears out of order "
                f"(expected {required[req_index]!r} next)"
            )
    if req_index < len(required):
        missing = required[req_index:]
        errors.append(f"missing required H2 sections: {', '.join(missing)!r}")
    return errors


def _validate_traceability(body: str, rules: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    trace_rules = rules["sections"].get("traceability", {})
    required_h3: list[str] = trace_rules.get("required_h3", [])
    trace_section = _section_slice(body, "Traceability", level=2)
    if not trace_section:
        return errors
    h3s = _h3_in_section(trace_section)
    for needed in required_h3:
        if not any(h.lower() == needed.lower() for h in h3s):
            errors.append(f"Traceability missing required H3: {needed!r}")
    return errors


def _validate_stable_ids(body: str, rules: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    id_rules: dict[str, str] = rules.get("ids", {})
    prefix_map = {"uj": "UJ", "fr": "FR", "kpi": "KPI", "risk": "RISK", "oq": "OQ"}
    for key, pattern in id_rules.items():
        token = prefix_map.get(key, key.upper())
        for match in re.finditer(rf"\b({token}-\d+)\b", body, re.IGNORECASE):
            value = match.group(1).upper()
            if not re.fullmatch(pattern, value):
                warnings.append(f"suspicious stable id {match.group(1)!r} (expected {pattern})")
    return warnings


def _validate_change_log_deltas(body: str, rules: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    trace = _section_slice(body, "Traceability", level=2)
    change = _section_slice(trace, "Change Log", level=3)
    if not change:
        return warnings
    delta_re = re.compile(rules["change_log"]["delta_pattern"])
    for line in change.splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if len(cells) < 4:
            continue
        delta_cell = cells[-1]
        if delta_cell in {"—", "-", "–"}:
            continue
        if "spec-" in delta_cell and not delta_re.search(delta_cell):
            warnings.append(
                f"Change Log delta {delta_cell!r} should start with "
                "ADDED|MODIFIED|REMOVED|RENAMED (OpenSpec-style)"
            )
    return warnings


def _validate_scaffold(body: str, meta: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = meta.get("status")
    if status not in {"ready", "done"}:
        return errors
    forbidden = rules["scaffold"]["forbidden_when_ready"]
    for phrase in forbidden:
        if phrase in body:
            errors.append(f"status={status!r} but body contains scaffold phrase: {phrase!r}")
    return errors


def _validate_open_questions(body: str, meta: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if meta.get("status") not in {"ready", "done"}:
        return errors
    oq_section = _section_slice(body, "Open Questions", level=2)
    if not oq_section.strip():
        errors.append("status ready/done requires ## Open Questions section")
        return errors
    open_rows = 0
    for line in oq_section.splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) >= 5 and cells[0].upper().startswith("OQ-"):
            status_cell = cells[-1].lower()
            if status_cell == "open":
                open_rows += 1
    if open_rows > 0:
        errors.append(
            f"Open Questions has {open_rows} unresolved open row(s) for status ready/done"
        )
    return errors


def _validate_specs_consistency(meta: dict[str, Any], body: str) -> list[str]:
    warnings: list[str] = []
    fm_specs = meta.get("specs") or []
    if not isinstance(fm_specs, list):
        return warnings
    trace = _section_slice(body, "Traceability", level=2)
    impl = _section_slice(trace, "Implementing Specs", level=3)
    table_specs: set[str] = set()
    for match in re.finditer(r"\bspec-\d{2}-[a-z0-9-]+\b", impl):
        table_specs.add(match.group(0))
    fm_set = set(fm_specs)
    if fm_set and table_specs and fm_set != table_specs:
        only_fm = fm_set - table_specs
        only_table = table_specs - fm_set
        if only_fm:
            warnings.append(
                f"specs in frontmatter but not Implementing Specs table: {sorted(only_fm)}"
            )
        if only_table:
            warnings.append(f"specs in table but not frontmatter specs: {sorted(only_table)}")
    return warnings


def validate_prd_file(
    path: Path,
    kit_root: Path,
    *,
    rules: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate one PRD markdown file against kit rules."""
    if rules is None:
        rules = load_prd_rules(kit_root)
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    meta, body, fm_err = parse_frontmatter(text)
    if fm_err:
        errors.append(fm_err)
        return errors, warnings

    fm_errors, fm_warnings = _validate_frontmatter(meta, rules)
    errors.extend(fm_errors)
    warnings.extend(fm_warnings)
    if fm_errors:
        return errors, warnings

    sec_rules = rules["sections"]
    errors.extend(_validate_section_order(body, sec_rules["required"]))

    profile = meta.get("prd_profile", "standard")
    if profile == "ai-native":
        found_h2 = {h.lower() for h in _h2_order(body)}
        for needed in sec_rules["ai_native"]:
            if needed.lower() not in found_h2:
                errors.append(f"prd_profile=ai-native requires H2 section: {needed!r}")

    if meta.get("status") in {"ready", "done"}:
        found_h2 = {h.lower() for h in _h2_order(body)}
        for rec in sec_rules.get("recommended_ready", []):
            if rec.lower() not in found_h2:
                warnings.append(f"status ready/done recommends H2 section: {rec!r}")

    errors.extend(_validate_traceability(body, rules))
    warnings.extend(_validate_stable_ids(body, rules))
    warnings.extend(_validate_change_log_deltas(body, rules))
    errors.extend(_validate_scaffold(body, meta, rules))
    errors.extend(_validate_open_questions(body, meta))
    warnings.extend(_validate_specs_consistency(meta, body))

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    """CLI entry for PRD validation."""
    parser = argparse.ArgumentParser(description="Validate sevn.bot PRD markdown files")
    parser.add_argument("paths", nargs="+", help="One or more PRD .md files")
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="spec-kit-wave root (default: parent of src/)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    kit_root = args.kit_root.resolve()
    rules = load_prd_rules(kit_root)
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
        errors, warnings = validate_prd_file(path, kit_root, rules=rules)
        ok = not errors
        if not ok:
            exit_code = 1
        reports.append(
            {
                "path": str(path),
                "ok": ok,
                "errors": errors,
                "warnings": warnings,
            }
        )

    if args.json:
        print(json.dumps({"reports": reports}, indent=2))
        return exit_code

    for report in reports:
        print(report["path"])
        errors_list = report["errors"]
        warnings_list = report["warnings"]
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
