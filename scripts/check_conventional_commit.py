#!/usr/bin/env python3
"""Validate commit messages against Conventional Commits 1.0.0 (commit-msg hook).

Module: scripts.check_conventional_commit
Depends: argparse, pathlib, re, sys

Exports:
    validate_commit_message — check subject against Conventional Commits 1.0.0.
    main — CLI entry; reads commit message file or ``--message``.

Examples:
    >>> main(["--message", "feat: add hook"]) in (0, 1)
    True
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_TYPES = frozenset(
    {
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "perf",
        "test",
        "build",
        "ci",
        "chore",
        "revert",
    }
)

# Conventional Commits 1.0.0 subject: type(scope)!: description
_SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9._-]+)\))?(?P<bang>!)?: (?P<desc>.+)$"
)

_MERGE_PREFIXES = (
    "Merge branch",
    "Merge pull request",
    "Merge remote-tracking",
    "Merge tag",
    "Merge commit",
)

_MAX_SUBJECT_LEN = 72


def _subject_line(message: str) -> str:
    """Return the first non-empty, non-comment line of a commit message.

    Args:
        message (str): Full commit message text.

    Returns:
        str: Subject line or empty string.

    Examples:
        >>> _subject_line("# comment\\n\\nfeat: x")
        'feat: x'
    """
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


def _should_skip(subject: str) -> bool:
    """Return whether merge commits should bypass validation.

    Args:
        subject (str): Commit subject line.

    Returns:
        bool: True for git-generated merge subjects.

    Examples:
        >>> _should_skip("Merge branch 'main'")
        True
        >>> _should_skip("feat: ok")
        False
    """
    return subject.startswith(_MERGE_PREFIXES)


def validate_commit_message(message: str) -> list[str]:
    """Validate a commit message subject against Conventional Commits.

    Args:
        message (str): Full commit message (subject + optional body).

    Returns:
        list[str]: Human-readable errors; empty when valid or skipped.

    Examples:
        >>> validate_commit_message("feat(gateway): add hook")
        []
        >>> validate_commit_message("bad message")
        ['subject must match Conventional Commits 1.0.0: <type>[(scope)][!]: <description>']
    """
    subject = _subject_line(message)
    if not subject:
        return ["commit message is empty"]
    if _should_skip(subject):
        return []

    errors: list[str] = []
    if len(subject) > _MAX_SUBJECT_LEN:
        errors.append(
            f"subject is {len(subject)} characters; keep the first line ≤ {_MAX_SUBJECT_LEN}"
        )

    match = _SUBJECT_RE.match(subject)
    if match is None:
        errors.append(
            "subject must match Conventional Commits 1.0.0: <type>[(scope)][!]: <description>"
        )
        return errors

    commit_type = match.group("type")
    description = match.group("desc")
    if commit_type not in _TYPES:
        errors.append(
            f"type '{commit_type}' is not allowed; use one of: {', '.join(sorted(_TYPES))}"
        )
    if description.endswith("."):
        errors.append("description must not end with a period")
    if description != description.strip():
        errors.append("description must not have leading or trailing whitespace")
    if not description:
        errors.append("description must not be empty")

    return errors


def _read_message_file(path: Path) -> str:
    """Read a commit message file from disk.

    Args:
        path (Path): Path passed by the commit-msg hook.

    Returns:
        str: File contents.

    Raises:
        OSError: When the file cannot be read.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "msg"
        ...     _ = p.write_text("feat: ok\\n", encoding="utf-8")
        ...     _read_message_file(p)
        'feat: ok\\n'
    """
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the commit message validator.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` when valid, ``1`` when invalid.

    Examples:
        >>> main(["--message", "feat: ok"])
        0
        >>> main(["--message", "nope"])
        1
    """
    parser = argparse.ArgumentParser(description="Validate Conventional Commits subject")
    parser.add_argument(
        "commit_msg_file",
        nargs="?",
        help="Path to commit message file (commit-msg hook)",
    )
    parser.add_argument(
        "--message",
        "-m",
        dest="inline_message",
        help="Validate a message string (for make commit-msg-check)",
    )
    args = parser.parse_args(argv)

    if args.inline_message is not None:
        text = args.inline_message
    elif args.commit_msg_file:
        text = _read_message_file(Path(args.commit_msg_file))
    else:
        text = sys.stdin.read()

    errors = validate_commit_message(text)
    if not errors:
        return 0

    print("conventional-commits: commit message rejected:\n", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    print("\nSee https://www.conventionalcommits.org/en/v1.0.0/", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
