"""Changelog validator — Keep a Changelog + Unreleased (stdlib only).

Enforces the sevn.bot changelog contract:

* structural lint of ``CHANGELOG.md`` (Keep-a-Changelog categories, Unreleased heading);
* deterministic entry-row lint of every row under ``## [Unreleased]``;
* a diff gate: code changes under required globs must add a new Unreleased entry.

Two gate modes share the required/exempt globs:

* ``check_diff_gate`` — branch vs base (``--base``), for CI on the integration branch.
* ``check_staged_gate`` — staged index vs HEAD (``--staged``), for the local
  ``commit-msg`` hook; checks what is about to be committed with no remote ref.

Exports (mirrors ``skw.prd_validate``):
    load_changelog_rules — read ``changelog-rules.toml`` merged with defaults.
    parse_changelog — split a Keep-a-Changelog document into version sections.
    lint_entries — deterministic row lint for one Unreleased section.
    check_diff_gate — branch-vs-base "no code change without an entry" gate (CI).
    check_staged_gate — staged-index-vs-HEAD gate for the local commit-msg hook.
    validate_changelog — structural lint + the selected change gate.
    main — CLI (``--base`` for CI, ``--staged`` for the hook, ``--json``/``--changelog``).

Canonical validator for ``skw`` and the repo ``scripts/changelog_validate.py`` shim.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

VERSION_HEADING_RE = re.compile(r"^##\s+\[([^\]]+)\]\s*(?:[-–—]\s*(\S+))?\s*$")
CATEGORY_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^-\s+(.*\S)\s*$")
_REF_TOKEN_RE = re.compile(r"#[A-Za-z0-9_]+")

_DEFAULT_RULES: dict[str, Any] = {
    "structure": {
        "categories": ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"],
        "unreleased_heading": "Unreleased",
    },
    "entry": {
        "min_len": 12,
        "forbid_trailing_period": True,
        "require_sentence_case": True,
        "ref_pattern": r"#\d+",
        "require_datestamp": True,
        "datestamp_pattern": r"^\[\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}Z)?\]",
    },
    "diff_gate": {
        "base": "origin/main",
        "required_globs": ["src/sevn/**", "scripts/**"],
        "exempt_globs": [
            "**/tests/**",
            "*.md",
            "docs/**",
            "specs/**",
            "about-sevn.bot/**",
            "CHANGELOG.md",
        ],
        "skip_trailer": "changelog: skip",
    },
    "eval": {
        "structured_min": 7,
        "unstructured_min": 7,
        "rubric_dimensions": [
            "specificity",
            "user_impact_clarity",
            "category_correctness",
            "diff_equivalence",
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


def _default_rules_path() -> Path:
    """Return the bundled ``spec-kit-wave/changelog-rules.toml``."""
    return Path(__file__).resolve().parents[2] / "changelog-rules.toml"


def load_changelog_rules(path: Path | str | None = None) -> dict[str, Any]:
    """Load ``changelog-rules.toml`` merged with built-in defaults.

    Args:
        path: Explicit toml path, or ``None`` to use the bundled default.

    Returns:
        The merged rules mapping (defaults if the file is absent).
    """
    toml_path = Path(path) if path is not None else _default_rules_path()
    if not toml_path.is_file():
        return _DEFAULT_RULES
    with toml_path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return _deep_merge(_DEFAULT_RULES, loaded)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_changelog(text: str) -> dict[str, Any]:
    """Parse a Keep-a-Changelog document into structured version sections.

    Args:
        text: Full ``CHANGELOG.md`` contents.

    Returns:
        ``{"versions": [ {"name", "date", "line",
        "categories": [ {"name", "line", "lines": [ {"raw", "line"} ]} ]} ]}``
        where ``lines`` are the non-empty content rows under a category heading.
    """
    versions: list[dict[str, Any]] = []
    current_version: dict[str, Any] | None = None
    current_category: dict[str, Any] | None = None

    for index, raw_line in enumerate(text.splitlines(), start=1):
        version_match = VERSION_HEADING_RE.match(raw_line)
        if version_match:
            current_version = {
                "name": version_match.group(1).strip(),
                "date": (version_match.group(2) or None),
                "line": index,
                "categories": [],
            }
            versions.append(current_version)
            current_category = None
            continue

        category_match = CATEGORY_HEADING_RE.match(raw_line)
        if category_match and current_version is not None:
            current_category = {
                "name": category_match.group(1).strip(),
                "line": index,
                "lines": [],
            }
            current_version["categories"].append(current_category)
            continue

        stripped = raw_line.strip()
        if not stripped:
            continue
        # Content line: only meaningful when inside a version + category.
        if current_version is not None and current_category is not None:
            current_category["lines"].append({"raw": raw_line.rstrip(), "line": index})

    return {"versions": versions}


def _find_version(parsed: dict[str, Any], name: str) -> dict[str, Any] | None:
    for version in parsed["versions"]:
        if str(version["name"]).lower() == name.lower():
            return dict(version)
    return None


def _bullet_body(raw: str) -> str | None:
    """Return the entry body (text after ``- ``) or ``None`` for a non-bullet row."""
    match = BULLET_RE.match(raw.strip())
    return match.group(1).strip() if match else None


def _is_unreleased_version(version: dict[str, Any], rules: dict[str, Any]) -> bool:
    heading = str(rules["structure"]["unreleased_heading"])
    return str(version["name"]).lower() == heading.lower()


def _strip_leading_datestamp(body: str, pattern: str) -> tuple[str | None, str | None]:
    """Return ``(remainder, error)`` — error set when the leading stamp is missing/invalid."""
    datestamp_re = re.compile(pattern)
    match = datestamp_re.match(body)
    if not match:
        return None, f"missing or invalid leading datestamp (expected pattern {pattern!r})"
    return body[match.end() :].lstrip(), None


def unreleased_entries(text: str, unreleased_heading: str = "Unreleased") -> set[str]:
    """Return the set of normalized bullet-entry bodies under ``## [Unreleased]``."""
    parsed = parse_changelog(text)
    version = _find_version(parsed, unreleased_heading)
    if version is None:
        return set()
    rules = load_changelog_rules()
    entry_rules = rules["entry"]
    datestamp_pattern = str(entry_rules.get("datestamp_pattern", ""))
    require_datestamp = bool(entry_rules.get("require_datestamp", False))
    bodies: set[str] = set()
    for category in version["categories"]:
        for row in category["lines"]:
            body = _bullet_body(row["raw"])
            if not body:
                continue
            if require_datestamp and datestamp_pattern:
                remainder, _stamp_err = _strip_leading_datestamp(body, datestamp_pattern)
                if remainder:
                    bodies.add(remainder)
                continue
            bodies.add(body)
    return bodies


# ---------------------------------------------------------------------------
# Entry-row lint
# ---------------------------------------------------------------------------


def lint_entries(
    version: dict[str, Any],
    rules: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Deterministically lint every content row under one version section.

    Args:
        version: A version dict from :func:`parse_changelog` (typically Unreleased).
        rules: Merged rules; defaults are loaded when ``None``.

    Returns:
        ``(errors, warnings)`` for the section's rows.
    """
    if rules is None:
        rules = load_changelog_rules()
    entry_rules = rules["entry"]
    ref_re = re.compile(entry_rules["ref_pattern"])
    min_len = int(entry_rules["min_len"])
    require_datestamp = _is_unreleased_version(version, rules) and entry_rules.get(
        "require_datestamp", False
    )
    datestamp_pattern = str(entry_rules.get("datestamp_pattern", ""))

    errors: list[str] = []
    warnings: list[str] = []

    for category in version["categories"]:
        for row in category["lines"]:
            raw = row["raw"]
            line_no = row["line"]
            prefix = f"line {line_no}: entry"
            body = _bullet_body(raw)
            if body is None:
                errors.append(
                    f"{prefix} row must be a markdown bullet (start with '- '): {raw.strip()!r}"
                )
                continue

            lint_body = body
            if require_datestamp:
                if not datestamp_pattern:
                    errors.append(f"{prefix} datestamp required but datestamp_pattern is missing")
                    continue
                remainder, stamp_err = _strip_leading_datestamp(body, datestamp_pattern)
                if stamp_err:
                    errors.append(f"{prefix} {stamp_err}: {body!r}")
                    continue
                lint_body = remainder or ""

            if len(lint_body) < min_len:
                errors.append(f"{prefix} too short ({len(lint_body)} < {min_len} chars): {body!r}")

            if entry_rules.get("require_sentence_case", True) and lint_body:
                first = lint_body[0]
                if not lint_body.startswith("`") and first.isalpha() and first.islower():
                    errors.append(
                        f"{prefix} must be sentence case (uppercase first letter): {body!r}"
                    )

            if (
                entry_rules.get("forbid_trailing_period", True)
                and body.endswith(".")
                and not body.endswith("...")
            ):
                errors.append(f"{prefix} must not end with a period: {body!r}")

            for token in _REF_TOKEN_RE.findall(body):
                if not ref_re.fullmatch(token):
                    warnings.append(
                        f"{prefix} issue/PR ref {token!r} should match "
                        f"{entry_rules['ref_pattern']!r}"
                    )

    return errors, warnings


# ---------------------------------------------------------------------------
# Structural lint
# ---------------------------------------------------------------------------


def _lint_structure(
    parsed: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    structure = rules["structure"]
    allowed = {c.lower() for c in structure["categories"]}
    heading = structure["unreleased_heading"]

    unreleased = _find_version(parsed, heading)
    if unreleased is None:
        errors.append(f"missing '## [{heading}]' section")
        return errors, warnings

    for category in unreleased["categories"]:
        if category["name"].lower() not in allowed:
            errors.append(
                f"line {category['line']}: unknown category "
                f"'### {category['name']}' (allowed: {', '.join(structure['categories'])})"
            )
    return errors, warnings


# ---------------------------------------------------------------------------
# Glob matching (git-style, stdlib only)
# ---------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> str:
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                out.append(".*")
                i = j
                continue
            out.append("[^/]*")
            i += 1
            continue
        if char == "?":
            out.append("[^/]")
        elif char == "/":
            out.append("/")
        else:
            out.append(re.escape(char))
        i += 1
    return "^" + "".join(out) + "$"


def _matches_glob(path: str, pattern: str) -> bool:
    regex = re.compile(_glob_to_regex(pattern))
    if regex.match(path):
        return True
    # Also match the basename so patterns like ``*.md`` catch nested files.
    return bool(regex.match(path.rsplit("/", 1)[-1]))


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(_matches_glob(path, pattern) for pattern in patterns)


# ---------------------------------------------------------------------------
# Diff gate (git-backed)
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return 1, ""
    return result.returncode, result.stdout


def _resolve_base(repo_root: Path, base: str) -> str | None:
    """Return a verifiable base ref, trying ``base`` then a stripped ``origin/`` form."""
    candidates = [base]
    if base.startswith("origin/"):
        candidates.append(base[len("origin/") :])
    else:
        candidates.append(f"origin/{base}")
    for candidate in candidates:
        code, _ = _git(repo_root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
        if code == 0:
            return candidate
    return None


def check_diff_gate(
    repo_root: Path,
    base: str,
    rules: dict[str, Any] | None = None,
    changelog_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Enforce "no code change without an Unreleased entry".

    Degrades gracefully (empty errors + an informational note) when there is no
    git repo, no resolvable base ref, or no ``CHANGELOG.md`` at the base commit.

    Args:
        repo_root: Repository root to diff.
        base: Base ref (e.g. ``origin/main``); ``origin/`` stripping is attempted.
        rules: Merged rules; defaults loaded when ``None``.
        changelog_path: Current changelog path (default ``<repo_root>/CHANGELOG.md``).

    Returns:
        ``(errors, notes)`` — a non-empty ``notes`` with empty ``errors`` means skipped.
    """
    if rules is None:
        rules = load_changelog_rules()
    gate = rules["diff_gate"]
    heading = rules["structure"]["unreleased_heading"]
    if changelog_path is None:
        changelog_path = repo_root / "CHANGELOG.md"

    errors: list[str] = []
    notes: list[str] = []

    code, _ = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        notes.append(f"diff gate skipped: {repo_root} is not a git work tree")
        return errors, notes

    resolved = _resolve_base(repo_root, base)
    if resolved is None:
        notes.append(f"diff gate skipped: base ref {base!r} not found")
        return errors, notes

    # Escape hatch: `changelog: skip` anywhere in commit subjects/bodies base..HEAD.
    skip_trailer = str(gate["skip_trailer"]).lower()
    _, log = _git(repo_root, "log", "--format=%B", f"{resolved}..HEAD")
    if skip_trailer in log.lower():
        notes.append(f"diff gate skipped: {gate['skip_trailer']!r} trailer present")
        return errors, notes

    code, diff = _git(repo_root, "diff", "--name-only", f"{resolved}...HEAD")
    if code != 0:
        notes.append(f"diff gate skipped: unable to diff {resolved}...HEAD")
        return errors, notes

    changed = [line.strip() for line in diff.splitlines() if line.strip()]
    required_globs = list(gate["required_globs"])
    exempt_globs = list(gate["exempt_globs"])
    code_changes = [
        path
        for path in changed
        if _matches_any(path, required_globs) and not _matches_any(path, exempt_globs)
    ]

    if not code_changes:
        notes.append("diff gate: no code changes require a changelog entry")
        return errors, notes

    # CHANGELOG.md at base — absent means first structured changelog; skip.
    show_code, base_text = _git(repo_root, "show", f"{resolved}:CHANGELOG.md")
    if show_code != 0:
        notes.append("diff gate skipped: CHANGELOG.md absent at base ref")
        return errors, notes

    if not changelog_path.is_file():
        errors.append(f"diff gate: CHANGELOG.md not found at {changelog_path}")
        return errors, notes

    current_text = changelog_path.read_text(encoding="utf-8")
    base_entries = unreleased_entries(base_text, heading)
    current_entries = unreleased_entries(current_text, heading)
    new_entries = current_entries - base_entries

    if not new_entries:
        sample = ", ".join(code_changes[:5])
        more = "" if len(code_changes) <= 5 else f" (+{len(code_changes) - 5} more)"
        errors.append(
            f"code changed under required paths ({sample}{more}) but no new "
            f"'## [{heading}]' changelog entry was added vs {base}. "
            f"Add an entry, or use a 'changelog: skip' commit trailer to bypass."
        )
    else:
        notes.append(f"diff gate: {len(new_entries)} new Unreleased entry(ies) added")

    return errors, notes


# ---------------------------------------------------------------------------
# Staged gate (local pre-commit / commit-msg — index vs HEAD, no remote base)
# ---------------------------------------------------------------------------


def _repo_relative(repo_root: Path, path: Path) -> str:
    """Return ``path`` as a forward-slash path relative to ``repo_root`` (basename fallback)."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _index_text(repo_root: Path, rel: str) -> tuple[str | None, str | None]:
    """Return the staged (index) contents of ``rel``, or ``(None, note)`` when unstaged."""
    code, out = _git(repo_root, "show", f":{rel}")
    if code != 0:
        return None, f"{rel} is not staged in the index"
    return out, None


def _skip_requested(gate: dict[str, Any], commit_msg_file: Path | str | None) -> bool:
    """True when the commit opts out via the skip trailer or ``SEVN_CHANGELOG_SKIP``."""
    if os.environ.get("SEVN_CHANGELOG_SKIP", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if commit_msg_file:
        try:
            message = Path(commit_msg_file).read_text(encoding="utf-8")
        except OSError:
            message = ""
        if str(gate["skip_trailer"]).lower() in message.lower():
            return True
    return False


def check_staged_gate(
    repo_root: Path,
    rules: dict[str, Any] | None = None,
    changelog_path: Path | None = None,
    commit_msg_file: Path | str | None = None,
) -> tuple[list[str], list[str]]:
    """Enforce "no *staged* code change without a *staged* Unreleased entry".

    Unlike :func:`check_diff_gate` (branch-vs-base, for CI), this inspects what is
    about to be committed: ``git diff --cached`` for changed paths and the index
    copy of ``CHANGELOG.md`` (``:CHANGELOG.md``) against ``HEAD:CHANGELOG.md``. It
    needs no remote ref, so it is correct at the local ``commit-msg`` hook stage.

    Args:
        repo_root: Repository root.
        rules: Merged rules; defaults loaded when ``None``.
        changelog_path: Current changelog path (default ``<repo_root>/CHANGELOG.md``).
        commit_msg_file: Commit message file (skip-trailer source); ``None`` to skip.

    Returns:
        ``(errors, notes)`` — a non-empty ``notes`` with empty ``errors`` means skipped.
    """
    if rules is None:
        rules = load_changelog_rules()
    gate = rules["diff_gate"]
    heading = rules["structure"]["unreleased_heading"]
    if changelog_path is None:
        changelog_path = repo_root / "CHANGELOG.md"

    errors: list[str] = []
    notes: list[str] = []

    code, _ = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        notes.append(f"staged gate skipped: {repo_root} is not a git work tree")
        return errors, notes

    if _skip_requested(gate, commit_msg_file):
        notes.append(
            f"staged gate skipped: {gate['skip_trailer']!r} trailer or SEVN_CHANGELOG_SKIP set"
        )
        return errors, notes

    code, diff = _git(repo_root, "diff", "--cached", "--name-only")
    if code != 0:
        notes.append("staged gate skipped: unable to read the staged diff")
        return errors, notes

    changed = [line.strip() for line in diff.splitlines() if line.strip()]
    required_globs = list(gate["required_globs"])
    exempt_globs = list(gate["exempt_globs"])
    code_changes = [
        path
        for path in changed
        if _matches_any(path, required_globs) and not _matches_any(path, exempt_globs)
    ]

    if not code_changes:
        notes.append("staged gate: no staged code changes require a changelog entry")
        return errors, notes

    rel = _repo_relative(repo_root, changelog_path)
    index_text, index_note = _index_text(repo_root, rel)
    head_code, head_text = _git(repo_root, "show", f"HEAD:{rel}")
    base_entries = unreleased_entries(head_text, heading) if head_code == 0 else set()
    current_entries = unreleased_entries(index_text, heading) if index_text is not None else set()
    new_entries = current_entries - base_entries

    if not new_entries:
        sample = ", ".join(code_changes[:5])
        more = "" if len(code_changes) <= 5 else f" (+{len(code_changes) - 5} more)"
        detail = f" ({index_note})" if index_note else ""
        errors.append(
            f"staged code under required paths ({sample}{more}) but no new "
            f"'## [{heading}]' changelog entry is staged{detail}. Stage a CHANGELOG.md "
            f"entry, or add a 'changelog: skip' trailer to the commit message."
        )
    else:
        notes.append(f"staged gate: {len(new_entries)} new Unreleased entry(ies) staged")

    return errors, notes


# ---------------------------------------------------------------------------
# Top-level validation
# ---------------------------------------------------------------------------


def validate_changelog(
    repo_root: Path,
    base: str | None,
    rules: dict[str, Any] | None = None,
    changelog_path: Path | None = None,
    *,
    staged: bool = False,
    commit_msg_file: Path | str | None = None,
) -> tuple[list[str], list[str]]:
    """Run structural lint (+ entry lint) and the appropriate change gate.

    Gate selection:
        * ``staged=True`` — the staged gate (index vs HEAD); ``base`` is ignored.
          Lints the *staged* copy of the changelog so uncommitted edits are ignored.
        * else ``base`` set — the branch-vs-base diff gate (for CI).
        * else — structure/entry lint only.

    Args:
        repo_root: Repository root.
        base: Base ref for the diff gate, or ``None`` to skip it.
        rules: Merged rules; defaults loaded when ``None``.
        changelog_path: Changelog path (default ``<repo_root>/CHANGELOG.md``).
        staged: Run the local staged gate instead of the base diff gate.
        commit_msg_file: Commit message file for the skip trailer (staged mode).

    Returns:
        ``(errors, warnings)``. Gate skip reasons surface as warnings.
    """
    if rules is None:
        rules = load_changelog_rules()
    if changelog_path is None:
        changelog_path = repo_root / "CHANGELOG.md"

    errors: list[str] = []
    warnings: list[str] = []

    # Choose the text to lint: the staged (index) copy in staged mode, else the
    # working-tree file. Staged mode falls back to the working file when the
    # changelog is not itself staged (e.g. code staged, changelog edited earlier).
    if staged:
        rel = _repo_relative(repo_root, changelog_path)
        text, index_note = _index_text(repo_root, rel)
        if text is None:
            if changelog_path.is_file():
                text = changelog_path.read_text(encoding="utf-8")
                if index_note:
                    warnings.append(f"{index_note}; linting the working-tree copy")
            else:
                errors.append(f"CHANGELOG.md not found at {changelog_path}")
                return errors, warnings
    else:
        if not changelog_path.is_file():
            errors.append(f"CHANGELOG.md not found at {changelog_path}")
            return errors, warnings
        text = changelog_path.read_text(encoding="utf-8")

    parsed = parse_changelog(text)

    struct_errors, struct_warnings = _lint_structure(parsed, rules)
    errors.extend(struct_errors)
    warnings.extend(struct_warnings)

    heading = rules["structure"]["unreleased_heading"]
    unreleased = _find_version(parsed, heading)
    if unreleased is not None:
        row_errors, row_warnings = lint_entries(unreleased, rules)
        errors.extend(row_errors)
        warnings.extend(row_warnings)

    if staged:
        gate_errors, gate_notes = check_staged_gate(
            repo_root, rules, changelog_path, commit_msg_file
        )
        errors.extend(gate_errors)
        warnings.extend(gate_notes)
    elif base:
        gate_errors, gate_notes = check_diff_gate(repo_root, base, rules, changelog_path)
        errors.extend(gate_errors)
        warnings.extend(gate_notes)

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    """CLI entry for changelog validation."""
    parser = argparse.ArgumentParser(description="Validate sevn.bot CHANGELOG.md")
    parser.add_argument("--repo", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--base",
        default=os.environ.get("SEVN_CI_BASE"),
        help="Diff-gate base ref (default: $SEVN_CI_BASE, else diff gate is skipped)",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Local commit-msg/pre-commit gate: check staged (index) changes, not --base",
    )
    parser.add_argument(
        "--commit-msg-file",
        default=None,
        help="Commit message file (skip-trailer source in --staged mode)",
    )
    parser.add_argument(
        "commit_msg_file_pos",
        nargs="?",
        default=None,
        help=argparse.SUPPRESS,  # pre-commit's commit-msg stage appends the message path
    )
    parser.add_argument(
        "--changelog",
        default=None,
        help="Changelog path (default: <repo>/CHANGELOG.md). Structure-only unless --base/--staged.",
    )
    parser.add_argument("--rules", default=None, help="Path to changelog-rules.toml")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    changelog_path = (
        Path(args.changelog).resolve() if args.changelog else repo_root / "CHANGELOG.md"
    )
    rules = load_changelog_rules(args.rules)
    commit_msg_file = args.commit_msg_file or args.commit_msg_file_pos

    errors, warnings = validate_changelog(
        repo_root,
        args.base,
        rules,
        changelog_path,
        staged=args.staged,
        commit_msg_file=commit_msg_file,
    )
    ok = not errors

    if args.json:
        print(
            json.dumps(
                {
                    "changelog": str(changelog_path),
                    "repo": str(repo_root),
                    "base": args.base,
                    "staged": args.staged,
                    "ok": ok,
                    "errors": errors,
                    "warnings": warnings,
                },
                indent=2,
            )
        )
        return 0 if ok else 1

    print(str(changelog_path))
    for err in errors:
        print(f"  ERROR: {err}")
    for warn in warnings:
        print(f"  WARN: {warn}")
    if ok and not warnings:
        print("  OK")
    elif ok:
        print("  OK (with warnings)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
